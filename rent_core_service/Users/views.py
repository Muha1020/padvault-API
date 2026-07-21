# Users/views.py
import os
import time
import requests
import json
import traceback
import logging
import bcrypt
import secrets
import hmac
from decimal import Decimal
import cloudinary.uploader
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import UserSerializer
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.middleware.csrf import get_token
from utils.rate_limit import rate_limit
from Address.models import Address
from .models import User, token_manager
from utils.monnify import MonnifyProvider
from utils.email import EmailManager

# Configure logging
logger = logging.getLogger(__name__)

# User registration view
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(rate_limit(limit=10, window_seconds=3600, endpoint_key='register'), name='post')
class RegisterUserView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            logger.info(f"Received registration request from email: {request.data.get('email', 'unknown')}")
            
            serializer = UserSerializer(data=request.data)
            
            if serializer.is_valid():
                logger.info("Data validation passed")
                
                try:
                    user = serializer.save()
                    
                    # Generate OTP
                    from django.utils import timezone
                    from datetime import timedelta
                    
                    otp = str(secrets.randbelow(900000) + 100000)
                    user.email_otp = otp
                    user.otp_expires_at = timezone.now() + timedelta(minutes=15)
                    user.save(update_fields=['email_otp', 'otp_expires_at'])
                    
                    logger.info(f"User created successfully with ID: {user.id}. Sending OTP.")
                    
                    # Send OTP email - Wrap in try-except to ensure registration doesn't crash on SMTP failure
                    try:
                        EmailManager.send_otp_email(user.email, user.firstname or "User", otp)
                    except Exception as email_err:
                        logger.error(f"CRITICAL: Failed to send OTP to {user.email}: {str(email_err)}")
                        # We still return success because the user account is created
                    
                    return Response({
                        "success": True,
                        "message": "User created successfully",
                        "user_id": user.id
                    }, status=status.HTTP_201_CREATED)
                    
                except Exception as save_error:
                    logger.error(f"Error during user save: {str(save_error)}")
                    return Response({
                        "success": False,
                        "message": "Error saving user to database",
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Unexpected error in user registration: {str(e)}")
            return Response({
                "success": False,
                "message": "Internal server error",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Login view
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(rate_limit(limit=5, window_seconds=60, endpoint_key='login'), name='post')
class LoginAPIView(APIView):
    authentication_classes = [] # Public
    permission_classes = []

    def post(self, request):
        try:
            email = request.data.get("email", "").strip()
            password = request.data.get("password", "").strip()
        except Exception:
            return Response({
                "success": False,
                "message": "Invalid request format",
                "error_code": 400
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not email or not password:
            return Response({
                "success": False,
                "message": "Email and password are required",
                "error_code": 400
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            logger.warning(f"Failed login: unknown email '{email}' from IP {request.META.get('REMOTE_ADDR')}")
            return Response({
                "success": False,
                "message": "Invalid email or password",
                "error_code": 401
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        if not user.isactive:
            return Response({
                "success": False,
                "message": "Account is inactive",
                "error_code": 403
            }, status=status.HTTP_403_FORBIDDEN)
            
        if not user.email_verified:
            return Response({
                "success": False,
                "message": "Email not verified. Please verify your email.",
                "error_code": 403,
                "unverified_email": user.email
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            password_bytes = password.encode('utf-8')
            hashed_bytes = user.password.encode('utf-8')
            
            if not bcrypt.checkpw(password_bytes, hashed_bytes):
                logger.warning(f"Failed login: wrong password for '{email}' from IP {request.META.get('REMOTE_ADDR')}")
                return Response({
                    "success": False,
                    "message": "Invalid email or password",
                    "error_code": 401
                }, status=status.HTTP_401_UNAUTHORIZED)
                
        except Exception:
            return Response({
                "success": False,
                "message": "Authentication error",
                "error_code": 500
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        token_data = token_manager.create_token(str(user.id))
        token = token_data["token"]
        
        # Force CSRF cookie to be set in the response so the frontend has it for subsequent requests
        get_token(request)

        # Send login security notification at most once per 24 hours
        from utils.push_notifications import send_push_notification
        from datetime import timedelta
        from django.utils import timezone as _tz
        _now = _tz.now()
        _last = user.last_login_notification_at
        if not _last or (_now - _last) > timedelta(hours=24):
            send_push_notification(
                user,
                "New Login Detected",
                "Your account was just accessed. If this wasn't you, change your password immediately.",
                "/dashboard/settings",
                notification_type='security'
            )
            user.last_login_notification_at = _now
            user.save(update_fields=['last_login_notification_at'])

        user_response = {
            "id": user.id,
            "email": user.email,
            "firstname": user.firstname,
            "lastname": user.lastname,
            "phone": user.phone,
            "role": user.role,
            "isactive": user.isactive,
            "subscription_tier": user.subscription_tier,
            "registration_step": user.registration_step,
            "monnify_subaccount_code": user.monnify_subaccount_code,
            "profile_picture": user.profile_picture,
            "saved_signature": user.saved_signature,
        }

        response = Response({
            "success": True,
            "message": "Login successful",
            "data": {
                "user": user_response,
            }
        }, status=status.HTTP_200_OK)

        _production = os.getenv("DJANGO_PRODUCTION", "false").lower() == "true"
        response.set_cookie(
            key='padvault_token',
            value=token,
            httponly=True,
            samesite='Lax',
            max_age=5 * 60 * 60,
            secure=_production,
            path='/',
        )

        return response


class LogoutView(APIView):
    def post(self, request):
        try:
            token = request.COOKIES.get('padvault_token')
            if not token:
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('JWT '):
                    token = auth_header[4:]

            if token:
                token_manager.invalidate_token(token)

            response = Response({
                "success": True,
                "message": "Logout successful",
            }, status=status.HTTP_200_OK)

            response.delete_cookie('padvault_token', path='/')
            return response

        except Exception as e:
            logger.error(f"Unexpected error during logout: {str(e)}")
            return Response({
                "success": False,
                "message": "Internal server error during logout",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoutAllView(APIView):
    def post(self, request):
        try:
            user_id = str(request.user.id)
            tokens_invalidated = token_manager.invalidate_all_user_tokens(user_id)

            response = Response({
                "success": True,
                "message": "Logged out from all devices",
            }, status=status.HTTP_200_OK)
            response.delete_cookie('padvault_token', path='/')
            return response
            
        except Exception as e:
            logger.error(f"Error during logout all: {str(e)}")
            return Response({
                "success": False,
                "message": "Internal server error",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EditProfileView(APIView):
    def put(self, request):
        try:
            user = request.user
            data = request.data

            allowed_fields = ['firstname', 'lastname', 'phone', 'saved_signature']
            updated_fields = []

            for field in allowed_fields:
                if field in data:
                    setattr(user, field, data[field] or None)
                    updated_fields.append(field)

            if 'profile_picture' in data:
                pic = data['profile_picture']
                if pic and not (isinstance(pic, str) and pic.startswith(('http://', 'https://'))):
                    return Response({"success": False, "message": "Invalid profile picture URL"}, status=status.HTTP_400_BAD_REQUEST)
                user.profile_picture = pic or None
                updated_fields.append('profile_picture')

            if 'email' in data:
                new_email = data['email']
                if new_email != user.email:
                    import re
                    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
                        return Response({"success": False, "message": "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST)
                    if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                        return Response({"success": False, "message": "Email already exists"}, status=status.HTTP_400_BAD_REQUEST)
                    user.email = new_email
                    updated_fields.append('email')
            
            if updated_fields:
                user.save()
                return Response({
                    "success": True,
                    "message": "Profile updated successfully",
                    "data": {
                        "user": {
                            "id": user.id,
                            "email": user.email,
                            "firstname": user.firstname,
                            "lastname": user.lastname,
                            "phone": user.phone,
                            "role": user.role,
                            "profile_picture": user.profile_picture,
                        }
                    }
                })
            return Response({"success": False, "message": "No changes provided"}, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Error during profile update: {str(e)}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


@method_decorator(rate_limit(limit=5, window_seconds=60, endpoint_key='change_password'), name='post')
class ChangePasswordView(APIView):
    def post(self, request):
        try:
            user = request.user
            current_password = request.data.get('current_password')
            new_password = request.data.get('new_password')
            
            if not current_password or not new_password:
                return Response({"success": False, "message": "Missing passwords"}, status=400)
            
            if not bcrypt.checkpw(current_password.encode('utf-8'), user.password.encode('utf-8')):
                return Response({"success": False, "message": "Current password incorrect"}, status=400)
            
            # Use Django's built-in password validators
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return Response({"success": False, "message": "Password too weak", "errors": e.messages}, status=400)
            
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            user.password = hashed_password.decode('utf-8')
            user.save()
            
            token_manager.invalidate_all_user_tokens(str(user.id))
            
            # Send notification
            EmailManager.send_password_change_email(user)
            
            return Response({"success": True, "message": "Password changed successfully"})
            
        except Exception as e:
            logger.error(f"Error during password change: {str(e)}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class UserProfileView(APIView):
    def get(self, request):
        try:
            user = request.user
            user_data = {
                "id": user.id,
                "email": user.email,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "phone": user.phone,
                "role": user.role,
                "subscription_tier": user.subscription_tier,
                "subscription_status": user.subscription_status,
                "subscription_expires_at": user.subscription_expires_at,
                "registration_step": user.registration_step,
                "profile_picture": user.profile_picture,
                "monnify_subaccount_code": user.monnify_subaccount_code,
                "bank_name": user.bank_name,
                "bank_code": user.bank_code,
                "account_number": user.account_number,
                "account_name": user.account_name,
            }
            if hasattr(request, 'impersonator'):
                user_data['is_impersonating'] = True
                user_data['admin_user'] = {
                    "id": request.impersonator.id,
                    "email": request.impersonator.email,
                    "role": request.impersonator.role
                }

            return Response({"success": True, "data": user_data})
        except Exception as e:
            return Response({"success": False, "message": "Error fetching profile"}, status=500)


class DeleteAccountView(APIView):
    def delete(self, request):
        try:
            user = request.user
            password = request.data.get('password', '').strip()

            if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
                return Response({"success": False, "message": "Incorrect password"}, status=400)

            token_manager.invalidate_all_user_tokens(str(user.id))
            
            user_email = user.email
            user_name = user.firstname or "User"
            
            # NDPA Compliance: Anonymize PII
            import uuid
            user.isactive = False
            user.email = f"deleted_{uuid.uuid4().hex}@padvault.com"
            user.firstname = "Deleted"
            user.lastname = "User"
            user.phone = ""
            user.bank_name = ""
            user.bank_code = ""
            user.account_number = ""
            user.account_name = ""
            user.profile_picture = None
            user.saved_signature = ""
            user.monnify_subaccount_code = None
            user.password = "!deleted"
            user.save()
            
            # Notify user
            EmailManager.send_account_deletion_email(user_email, user_name)

            response = Response({"success": True, "message": "Account deleted successfully"})
            response.delete_cookie('padvault_token', path='/')
            return response

        except Exception as e:
            return Response({"success": False, "message": "Failed to delete account"}, status=500)


class UploadProfilePictureView(APIView):
    ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/jpg'}
    MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

    def post(self, request):
        try:
            user = request.user
            file = request.FILES.get('image')
            if not file:
                return Response({"success": False, "message": "No image provided"}, status=400)

            if file.content_type not in self.ALLOWED_IMAGE_TYPES:
                return Response({"success": False, "message": "Invalid file type. Only JPEG, PNG, and WebP are allowed."}, status=400)

            if file.size > self.MAX_SIZE_BYTES:
                return Response({"success": False, "message": "File too large. Maximum size is 5MB."}, status=400)

            result = cloudinary.uploader.upload(
                file,
                folder=f"rent_mgt/avatars/{user.id}",
                transformation=[
                    {"width": 400, "height": 400, "crop": "fill", "gravity": "face"},
                ],
            )
            url = result['secure_url']
            user.profile_picture = url
            user.save()

            return Response({"success": True, "data": {"profile_picture": url}})
        except Exception as e:
            return Response({"success": False, "message": "Upload failed"}, status=500)


class KYCVerificationView(APIView):
    @method_decorator(rate_limit(limit=5, window_seconds=300, endpoint_key='kyc_verify'))
    def post(self, request):
        try:
            user = request.user
            if user.monnify_subaccount_code:
                return Response({"success": False, "message": "KYC already completed and account linked"}, status=400)

            data = request.data
            bank_code = data.get('bank_code')
            bank_name = data.get('bank_name') # Capture bank name
            account_number = data.get('account_number')
            bvn = data.get('bvn')
            
            monnify = MonnifyProvider()
            
            # Step 1: BVN-Account Match (Mandatory as per Monnify documentation)
            # BVN is passed to Monnify and then discarded. NEVER saved to DB.
            match_res = monnify.verify_bvn_match(bvn, bank_code, account_number)
            if not match_res['status']:
                return Response({"success": False, "message": match_res.get('message', "BVN matching failed")}, status=400)
            
            if not match_res.get('match'):
                return Response({"success": False, "message": "BVN does not match the provided bank account"}, status=400)

            # Step 2: Resolve Account Name
            verify_res = monnify.verify_bank_account(account_number, bank_code)
            if not verify_res['status']:
                return Response({"success": False, "message": verify_res.get('message')}, status=400)
            
            account_name = verify_res['account_name']

            # Step 3: Create Monnify Sub-account for payouts
            sub_res = monnify.create_subaccount(bank_code, account_number, account_name, user.email)
            if not sub_res['status']:
                error_msg = sub_res.get('message', '')
                # Sanitize technical errors (like split ratio/contract errors) for the end-user
                if any(x in error_msg.lower() for x in ["split percentage", "contract", "auth"]):
                    error_msg = "Fintech service configuration error. Please contact Padvault support."
                return Response({"success": False, "message": error_msg}, status=400)
            
            # Update user profile
            user.bank_code = bank_code
            user.bank_name = bank_name # Save the human-readable bank name
            user.account_number = account_number
            user.account_name = account_name
            user.monnify_subaccount_code = sub_res['subAccountCode']
            user.registration_step = 'complete'
            user.save()

            return Response({"success": True, "data": {
                "account_name": account_name,
                "sub_account_code": sub_res['subAccountCode']
            }})
        except Exception as e:
            # Mask the exception in logs to prevent accidental BVN leakage if it's in the error message
            logger.error("KYC Verification Error occurred. Details masked for data protection.")
            return Response({"success": False, "message": "Internal server error occurred during verification"}, status=500)


class InitializeSubscriptionView(APIView):
    @method_decorator(rate_limit(limit=3, window_seconds=600, endpoint_key='init_sub'))
    def post(self, request):
        try:
            user = request.user
            from Admin.models import SystemConfig
            try:
                amount = float(SystemConfig.objects.get(key='subscription_price').value)
            except SystemConfig.DoesNotExist:
                amount = 15000.00
            reference = f"SUB-{user.id}-{int(time.time())}"
            metadata = {
                "type": "subscription",
                "user_id": str(user.id),
                "plan": "premium"
            }

            monnify = MonnifyProvider()
            
            redirect_url = "https://padvault.io/dashboard/settings"

            res = monnify.initialize_transaction(
                amount=amount,
                name=f"{user.firstname} {user.lastname}".strip() or user.email,
                email=user.email,
                reference=reference,
                description="Padvault Premium Subscription (1 Month)",
                redirect_url=redirect_url,
                sub_account_code=None, # No split for subscription
                metadata=metadata
            )
            
            if res['status']:
                return Response({
                    "success": True, 
                    "data": {
                        "checkout_url": res['checkoutUrl'],
                        "payment_reference": reference
                    }
                })
            
            logger.error(f"Monnify Init Error: {res.get('message')}")
            return Response({"success": False, "message": res.get("message")}, status=400)
            
        except Exception as e:
            logger.error(f"Subscription Init Exception: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal error occurred while initializing payment"}, status=500)

class VerifySubscriptionView(APIView):
    def post(self, request):
        from utils.monnify import MonnifyProvider

        user = request.user
        payment_reference = request.data.get('payment_reference', '').strip()

        if not payment_reference.startswith(f'SUB-{user.id}-'):
            return Response({"success": False, "message": "Invalid payment reference."}, status=status.HTTP_400_BAD_REQUEST)

        # Already active — short-circuit
        if user.subscription_tier == 'premium' and user.subscription_status == 'active':
            return Response({"success": True, "already_active": True, "subscription_tier": "premium"})

        monnify = MonnifyProvider()
        res = monnify.verify_transaction(payment_reference)

        if not res['status']:
            return Response({"success": False, "message": "Could not verify payment with gateway."}, status=status.HTTP_502_BAD_GATEWAY)

        payment_status = res['data'].get('paymentStatus', '')
        amount_paid = float(res['data'].get('amountPaid', 0))
        gateway_reference = res['data'].get('transactionReference', payment_reference)

        if payment_status not in ('PAID', 'OVERPAID'):
            return Response({"success": True, "paid": False, "payment_status": payment_status})

        # Reuse the same upgrade logic the webhook uses (idempotency + email + push included)
        from Transactions.services import process_monnify_webhook
        metadata = {"type": "subscription", "user_id": str(user.id)}
        process_monnify_webhook(payment_reference, amount_paid, metadata, gateway_reference)

        user.refresh_from_db()
        return Response({
            "success": True,
            "paid": True,
            "subscription_tier": user.subscription_tier,
            "subscription_expires_at": user.subscription_expires_at,
        })


class DashboardSummaryView(APIView):
    """
    GET /api/users/dashboard-summary/
    Returns all data the landlord dashboard needs in a single request,
    replacing the previous 4 parallel API calls.
    """
    def get(self, request):
        try:
            from Properties.models import properties as Property
            from Rent.models import Rent
            from Rent.serializers import RentSerializer
            from Properties.serializers import PropertyListSerializer
            from Maintenance.models import MaintenanceRequest
            from Maintenance.serializers import MaintenanceSerializer
            from Bookings.models import Booking
            from Bookings.serializers import BookingSerializer

            user = request.user

            from django.db.models import Prefetch
            from Rent.models import PaymentSchedule

            # Count before slicing — calling .count() on a sliced queryset raises a Django error.
            props_qs = Property.objects.filter(landlord=user).select_related('address_id').order_by('-created_at')
            props_count = props_qs.count()
            props_page = props_qs[:20]

            # RentSerializer accesses .schedule, so prefetch to avoid N+1 per rent row.
            rents_list = list(
                Rent.objects.filter(rental_property__landlord=user)
                .select_related('rental_property', 'tenant')
                .prefetch_related('schedule')
                .order_by('-created_at')[:50]
            )
            maintenance_list = list(
                MaintenanceRequest.objects.filter(property__landlord=user)
                .select_related('property')
                .order_by('-created_at')[:50]
            )
            # Booking FK is named 'property', not 'rental_property'
            bookings_list = list(
                Booking.objects.filter(property__landlord=user)
                .select_related('property')
                .order_by('-created_at')[:50]
            )

            return Response({
                "success": True,
                "data": {
                    "properties": {
                        "count": props_count,
                        "data": PropertyListSerializer(props_page, many=True, context={'request': request}).data,
                    },
                    "rents": {
                        "count": len(rents_list),
                        "data": RentSerializer(rents_list, many=True).data,
                    },
                    "maintenance": {
                        "count": len(maintenance_list),
                        "data": MaintenanceSerializer(maintenance_list, many=True).data,
                    },
                    "bookings": {
                        "count": len(bookings_list),
                        "data": BookingSerializer(bookings_list, many=True).data,
                    },
                }
            })
        except Exception as e:
            logger.error(f"Dashboard summary error: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to load dashboard"}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ContactUsView(APIView):
    authentication_classes = []
    permission_classes = []
    
    @method_decorator(rate_limit(limit=3, window_seconds=300, endpoint_key='contact_us'))
    def post(self, request):
        try:
            name = request.data.get('name', '').strip()
            email = request.data.get('email', '').strip()
            subject = request.data.get('subject', '').strip()
            message = request.data.get('message', '').strip()
            
            if not all([name, email, subject, message]):
                return Response({"success": False, "message": "All fields are required"}, status=400)
                
            # Save to database
            from .models import SupportMessage
            SupportMessage.objects.create(
                name=name,
                email=email,
                subject=subject,
                message=message
            )

            EmailManager.send_contact_email(name, email, subject, message)
            
            return Response({"success": True, "message": "Message sent successfully"})
        except Exception as e:
            logger.error(f"Contact Us Error: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Failed to send message"}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class VerifyEmailOTPView(APIView):
    authentication_classes = []
    permission_classes = []
    
    @method_decorator(rate_limit(limit=5, window_seconds=300, endpoint_key='verify_otp'))
    def post(self, request):
        try:
            email = request.data.get('email', '').strip()
            otp = request.data.get('otp', '').strip()
            
            if not email or not otp:
                return Response({"success": False, "message": "Email and OTP required"}, status=400)
                
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"success": False, "message": "User not found"}, status=404)
                
            if user.email_verified:
                return Response({"success": True, "message": "Email is already verified"})
                
            from django.utils import timezone
            
            if not user.email_otp or not hmac.compare_digest(user.email_otp, otp):
                return Response({"success": False, "message": "Invalid verification code"}, status=400)
                
            if user.otp_expires_at and timezone.now() > user.otp_expires_at:
                return Response({"success": False, "message": "Verification code has expired"}, status=400)
                
            # Success
            user.email_verified = True
            user.email_otp = None
            user.otp_expires_at = None
            user.save(update_fields=['email_verified', 'email_otp', 'otp_expires_at'])
            
            # Send welcome email now that they are verified
            EmailManager.send_welcome_email(user)

            # Send welcome notification
            from utils.push_notifications import send_push_notification
            send_push_notification(
                user,
                "Welcome to Padvault!",
                "We're excited to have you on board. Start by adding your first property or setting up your profile.",
                "/dashboard",
                notification_type='system'
            )
            
            return Response({"success": True, "message": "Email verified successfully"})
            
        except Exception as e:
            logger.error(f"Error in OTP Verification: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal server error"}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class ResendOTPView(APIView):
    authentication_classes = []
    permission_classes = []
    
    @method_decorator(rate_limit(limit=3, window_seconds=600, endpoint_key='resend_otp'))
    def post(self, request):
        try:
            email = request.data.get('email', '').strip()
            if not email:
                return Response({"success": False, "message": "Email required"}, status=400)
                
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"success": False, "message": "User not found"}, status=404)
                
            if user.email_verified:
                return Response({"success": False, "message": "Email is already verified"}, status=400)
                
            # Generate new OTP
            from django.utils import timezone
            from datetime import timedelta
            
            otp = str(secrets.randbelow(900000) + 100000)
            user.email_otp = otp
            user.otp_expires_at = timezone.now() + timedelta(minutes=15)
            user.save(update_fields=['email_otp', 'otp_expires_at'])
            
            EmailManager.send_otp_email(user.email, user.firstname or "User", otp)
            
            return Response({"success": True, "message": "Verification code sent"})
            
        except Exception as e:
            logger.error(f"Error resending OTP: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal server error"}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class ForgotPasswordView(APIView):
    authentication_classes = []
    permission_classes = []
    
    @method_decorator(rate_limit(limit=3, window_seconds=300, endpoint_key='forgot_password'))
    def post(self, request):
        try:
            email = request.data.get('email', '').strip()
            if not email:
                return Response({"success": False, "message": "Email is required"}, status=400)
            
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                # We return success even if user not found for security (to prevent account enumeration)
                return Response({"success": True, "message": "If an account exists with this email, a reset code has been sent."})
            
            # Generate OTP
            from django.utils import timezone
            from datetime import timedelta
            
            otp = str(secrets.randbelow(900000) + 100000)
            user.email_otp = otp
            user.otp_expires_at = timezone.now() + timedelta(minutes=15)
            user.save(update_fields=['email_otp', 'otp_expires_at'])
            
            # Send Email
            EmailManager.send_password_reset_email(user.email, user.firstname or "User", otp)
            
            return Response({"success": True, "message": "Reset code sent successfully"})
            
        except Exception as e:
            logger.error(f"Forgot Password Error: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal server error"}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class ResetPasswordView(APIView):
    authentication_classes = []
    permission_classes = []
    
    @method_decorator(rate_limit(limit=5, window_seconds=300, endpoint_key='reset_password'))
    def post(self, request):
        try:
            email = request.data.get('email', '').strip()
            otp = request.data.get('otp', '').strip()
            new_password = request.data.get('new_password', '').strip()
            
            if not all([email, otp, new_password]):
                return Response({"success": False, "message": "All fields are required"}, status=400)
                
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"success": False, "message": "Invalid request"}, status=400)
            
            from django.utils import timezone
            if not user.email_otp or not hmac.compare_digest(user.email_otp, otp):
                return Response({"success": False, "message": "Invalid or expired reset code"}, status=400)
                
            if user.otp_expires_at and timezone.now() > user.otp_expires_at:
                return Response({"success": False, "message": "Reset code has expired"}, status=400)
            
            # Validate password strength
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError
            try:
                validate_password(new_password)
            except ValidationError as e:
                return Response({"success": False, "message": "Password too weak", "errors": e.messages}, status=400)
            
            # Update password
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
            user.password = hashed_password.decode('utf-8')
            
            # Clear OTP
            user.email_otp = None
            user.otp_expires_at = None
            user.save(update_fields=['password', 'email_otp', 'otp_expires_at'])
            
            # Invalidate all existing tokens for this user
            token_manager.invalidate_all_user_tokens(str(user.id))
            
            return Response({"success": True, "message": "Password reset successfully. You can now login."})
            
        except Exception as e:
            logger.error(f"Reset Password Error: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal server error"}, status=500)

class GoogleAuthView(APIView):
    authentication_classes = [] # Public
    permission_classes = []

    def post(self, request):
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            from django.conf import settings
        except ImportError:
            return Response({"success": False, "message": "google-auth not installed on server"}, status=500)

        token = request.data.get('credential')
        if not token:
            return Response({"success": False, "message": "No credential provided."}, status=400)

        try:
            client_id = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id, clock_skew_in_seconds=10)

            email = idinfo['email']
            first_name = idinfo.get('given_name', '')
            last_name = idinfo.get('family_name', '')
            picture = idinfo.get('picture', '')

            user = User.objects.filter(email=email).first()

            if not user:
                import secrets
                import bcrypt
                random_pass = secrets.token_urlsafe(32)
                hashed = bcrypt.hashpw(random_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                user = User(
                    email=email,
                    firstname=first_name,
                    lastname=last_name,
                    profile_picture=picture,
                    email_verified=True,
                    role='landlord',
                    password=hashed
                )
                user.save()
            elif not user.isactive:
                return Response({
                    "success": False,
                    "message": "Account is inactive",
                    "error_code": 403
                }, status=status.HTTP_403_FORBIDDEN)

            token_data = token_manager.create_token(str(user.id))
            token_str = token_data["token"]
            
            get_token(request)
            
            user_response = {
                "id": user.id,
                "email": user.email,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "phone": user.phone,
                "role": user.role,
                "isactive": user.isactive,
                "subscription_tier": user.subscription_tier,
                "registration_step": user.registration_step,
                "monnify_subaccount_code": user.monnify_subaccount_code,
                "profile_picture": user.profile_picture,
                "saved_signature": user.saved_signature,
            }

            response = Response({
                "success": True,
                "message": "Login successful",
                "data": {
                    "user": user_response
                }
            }, status=status.HTTP_200_OK)
            
            _production = os.getenv("DJANGO_PRODUCTION", "false").lower() == "true"
            response.set_cookie(
                key='padvault_token',
                value=token_str,
                httponly=True,
                samesite='Lax',
                max_age=5 * 60 * 60,
                secure=_production,
                path='/',
            )
            return response

        except ValueError as e:
            logger.error(f"Google Token Verification Error: {str(e)}")
            return Response({"success": False, "message": "Invalid Google token."}, status=401)
        except Exception as e:
            logger.error(f"Google Auth Error: {str(e)}", exc_info=True)
            return Response({"success": False, "message": "Internal server error"}, status=500)

class BankListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            from utils.monnify import MonnifyProvider
            monnify = MonnifyProvider()
            banks = monnify.get_banks()
            return Response({'success': True, 'data': banks}, status=200)
        except Exception as e:
            logger.error(f'Error fetching banks: {str(e)}', exc_info=True)
            return Response({'success': False, 'message': 'Internal server error'}, status=500)

