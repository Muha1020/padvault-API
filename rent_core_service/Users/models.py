from django.db import models
from django.conf import settings
from django.utils import timezone as django_timezone
import bcrypt, time, uuid
from datetime import datetime, timedelta, timezone
import jwt

class User(models.Model):
    ROLE_CHOICES = [
        ('landlord', 'Landlord'),
        ('tenant', 'Tenant'),
        ('admin', 'Admin'),
    ]
    firstname = models.CharField(max_length=50, blank=True)
    lastname = models.CharField(max_length=50, blank=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    phone = models.CharField(max_length=15, blank=True, null=True)
    
    REGISTRATION_STEPS = [
        ('basic', 'Basic'),
        ('kyc', 'KYC Pending'),
        ('complete', 'Complete'),
    ]
    registration_step = models.CharField(max_length=20, choices=REGISTRATION_STEPS, default='basic')

    ADMIN_LEVEL_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('moderator', 'Moderator'),
        ('support', 'Support'),
    ]
    admin_level = models.CharField(max_length=20, choices=ADMIN_LEVEL_CHOICES, blank=True, null=True)

    # Monnify / Bank Details
    monnify_subaccount_code = models.CharField(max_length=100, blank=True, null=True)

    # Verification Fields
    email_verified = models.BooleanField(default=False)
    email_otp = models.CharField(max_length=6, blank=True, null=True)
    otp_expires_at = models.DateTimeField(blank=True, null=True)

    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_code = models.CharField(max_length=10, blank=True, null=True)
    account_number = models.CharField(max_length=20, blank=True, null=True)
    account_name = models.CharField(max_length=150, blank=True, null=True)
    
    SUBSCRIPTION_TIERS = [
        ('free', 'Free'),
        ('premium', 'Premium'),
    ]

    SUBSCRIPTION_STATUS = [
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('expired', 'Expired'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, blank=True, null=True)
    profile_picture = models.URLField(max_length=500, null=True, blank=True)
    saved_signature = models.TextField(blank=True, null=True, help_text="Base64 encoded signature image")
    subscription_tier = models.CharField(max_length=20, choices=SUBSCRIPTION_TIERS, default='free')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS, default='active')
    subscription_started_at = models.DateTimeField(null=True, blank=True)
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    last_login_notification_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    isactive = models.BooleanField(default=True)
    address_id = models.ForeignKey("Address.Address", on_delete=models.CASCADE, null=True)

    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return f"{self.email} ({self.role})"

    class Meta:
        indexes = [
            models.Index(fields=['role', 'isactive']),
            models.Index(fields=['isactive']),
        ]


class TokenManager:
    def __init__(self):
        self.algorithm = "HS256"
        self.token_ttl_hours = 5

    def _get_secret_key(self):
        return settings.SECRET_KEY

    def create_token(self, user_id, device_info=None):
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(hours=self.token_ttl_hours)
        token_id = str(uuid.uuid4())

        payload = {
            "jti": token_id,
            "user_id": str(user_id),
            "type": "access",
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }

        token = jwt.encode(payload, self._get_secret_key(), algorithm=self.algorithm)

        return {
            "token": token,
            "user_id": str(user_id),
            "created_at": int(issued_at.timestamp()),
            "expires_at": int(expires_at.timestamp()),
            "jti": token_id,
            "is_active": True,
        }

    def validate_token(self, token):
        try:
            payload = jwt.decode(token, self._get_secret_key(), algorithms=[self.algorithm])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

        token_id = payload.get("jti")
        user_id = str(payload.get("user_id", ""))
        issued_at = int(payload.get("iat", 0))
        expires_at = int(payload.get("exp", 0))

        if payload.get("type") != "access" or not user_id:
            return None

        if BlacklistedToken.objects.filter(jti=token_id).exists():
            return None

        try:
            revocation = UserTokenRevocation.objects.get(user_id=user_id)
            if issued_at <= int(revocation.revoke_all_issued_before.timestamp()):
                return None
        except UserTokenRevocation.DoesNotExist:
            pass

        return {
            "token": token,
            "jti": token_id,
            "user_id": user_id,
            "created_at": issued_at,
            "expires_at": expires_at,
            "is_active": True,
        }

    def invalidate_token(self, token):
        # Decode locally — no DB reads needed just to write a blacklist entry.
        try:
            payload = jwt.decode(token, self._get_secret_key(), algorithms=[self.algorithm])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return False

        token_id = payload.get("jti")
        user_id = str(payload.get("user_id", ""))
        expires_at_ts = payload.get("exp")

        if not token_id or not user_id or not expires_at_ts:
            return False

        expires_at_dt = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)
        BlacklistedToken.objects.get_or_create(
            jti=token_id,
            defaults={"user_id": user_id, "expires_at": expires_at_dt},
        )
        return True

    def invalidate_all_user_tokens(self, user_id):
        user_id_str = str(user_id)
        now = django_timezone.now()
        UserTokenRevocation.objects.update_or_create(
            user_id=user_id_str,
            defaults={"revoke_all_issued_before": now},
        )
        return 1

class BlacklistedToken(models.Model):
    jti = models.CharField(max_length=36, unique=True, db_index=True)
    user_id = models.CharField(max_length=20)
    blacklisted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['expires_at'])]

class UserTokenRevocation(models.Model):
    user_id = models.CharField(max_length=20, unique=True, db_index=True)
    revoke_all_issued_before = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

class RateLimitEntry(models.Model):
    ip = models.CharField(max_length=45)
    endpoint = models.CharField(max_length=100)
    request_count = models.PositiveIntegerField(default=1)
    window_start = models.DateTimeField()

    class Meta:
        unique_together = ['ip', 'endpoint']
        indexes = [models.Index(fields=['ip', 'endpoint'])]

token_manager = TokenManager()

class SupportMessage(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    ]
    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_support_messages')

    def __str__(self):
        return f"{self.subject} from {self.email} ({self.status})"


class SupportMessageReply(models.Model):
    support_message = models.ForeignKey(SupportMessage, on_delete=models.CASCADE, related_name='replies')
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='support_replies')
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reply to #{self.support_message_id} by {self.admin}"
