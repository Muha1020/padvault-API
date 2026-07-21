from django.db import models
from Users.models import User

class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.URLField(max_length=500, unique=True)
    auth = models.CharField(max_length=100)
    p256dh = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Push Subscription for {self.user.email}"

    class Meta:
        verbose_name = "Push Subscription"
        verbose_name_plural = "Push Subscriptions"

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('payment', 'Payment Received/Sent'),
        ('invoice', 'New Invoice'),
        ('lease', 'Lease Update'),
        ('maintenance', 'Maintenance Update'),
        ('booking', 'Booking Update'),
        ('subscription', 'Subscription Update'),
        ('security', 'Security Alert'),
        ('system', 'System Alert'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='system')
    link = models.CharField(max_length=255, blank=True, null=True) # Deep link in the app
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.email}"
