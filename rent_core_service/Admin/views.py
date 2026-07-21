import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import StreamingHttpResponse
from django.utils import timezone
import csv
import io
from django.db.models import Count, Sum
from django.utils.decorators import method_decorator
from Users.models import User, SupportMessage, SupportMessageReply, token_manager
from utils.email import EmailManager
from Properties.models import properties
from Rent.models import Rent, RentInitiation
from Maintenance.models import MaintenanceRequest
from Transactions.models import Transaction
from Notifications.models import Notification
from utils.permissions import IsSuperAdmin, IsModeratorOrHigher, IsSupportOrHigher
from utils.rate_limit import rate_limit
from .models import AdminAuditLog, SystemConfig
import traceback
import bcrypt
import os

logger = logging.getLogger(__name__)

class AdminLoginAPIView(APIView):
    authentication_classes = [] # Public
    permission_classes = []

    @method_decorator(rate_limit(limit=5, window_seconds=300, endpoint_key='admin_login'))
    def post(self, request):
        try:
            email = request.data.get("email", "").strip()
            password = request.data.get("password", "").strip()
        except Exception:
            return Response({"success": False, "message": "Invalid request format"}, status=status.HTTP_400_BAD_REQUEST)
        
        if not email or not password:
            return Response({"success": False, "message": "Email and password are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            logger.warning(f"Failed admin login: unknown email '{email}' from IP {request.META.get('REMOTE_ADDR')}")
            return Response({"success": False, "message": "Invalid email or password"}, status=status.HTTP_401_UNAUTHORIZED)
        
        if user.role != 'admin':
            return Response({"success": False, "message": "Unauthorized. Admin access only."}, status=status.HTTP_403_FORBIDDEN)
            
        if not user.isactive:
            return Response({"success": False, "message": "Account is inactive"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            password_bytes = password.encode('utf-8')
            hashed_bytes = user.password.encode('utf-8')
            
            if not bcrypt.checkpw(password_bytes, hashed_bytes):
                logger.warning(f"Failed admin login: wrong password for '{email}' from IP {request.META.get('REMOTE_ADDR')}")
                return Response({"success": False, "message": "Invalid email or password"}, status=status.HTTP_401_UNAUTHORIZED)
                
        except Exception:
            return Response({"success": False, "message": "Authentication error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        token_data = token_manager.create_token(str(user.id))
        token = token_data["token"]

        log_admin_action(user, "admin_login", ip_address=request.META.get('REMOTE_ADDR'))

        user_response = {
            "id": user.id,
            "email": user.email,
            "firstname": user.firstname,
            "lastname": user.lastname,
            "role": user.role,
            "admin_level": user.admin_level,
            "isactive": user.isactive,
        }

        response = Response({
            "success": True,
            "message": "Admin login successful",
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

def log_admin_action(admin_user, action, target_id=None, target_type=None, details=None, ip_address=None):
    try:
        AdminAuditLog.objects.create(
            admin=admin_user,
            action=action,
            target_object_id=str(target_id) if target_id else None,
            target_object_type=target_type,
            details=details,
            ip_address=ip_address
        )
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")

class AdminStatsView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            total_users = User.objects.count()
            total_landlords = User.objects.filter(role='landlord').count()
            total_tenants = User.objects.filter(role='tenant').count()
            
            premium_users = User.objects.filter(subscription_tier='premium').count()
            active_properties = properties.objects.filter(is_published=True).count()
            total_leases = Rent.objects.exclude(payment_status='cancelled').count()

            try:
                price = int(SystemConfig.objects.get(key='subscription_price').value)
            except (SystemConfig.DoesNotExist, ValueError):
                price = 15000
            mrr = premium_users * price
            
            pending_kyc = User.objects.filter(registration_step='kyc').count()
            new_support_messages = SupportMessage.objects.filter(status='new').count()

            return Response({
                "success": True,
                "data": {
                    "total_users": total_users,
                    "total_landlords": total_landlords,
                    "total_tenants": total_tenants,
                    "premium_users": premium_users,
                    "active_properties": active_properties,
                    "total_leases": total_leases,
                    "mrr": mrr,
                    "pending_kyc": pending_kyc,
                    "new_support_messages": new_support_messages
                }
            })
        except Exception as e:
            logger.error(f"AdminStats Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminSystemLogsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            logs = AdminAuditLog.objects.select_related('admin').order_by('-created_at')[:100]
            data = []
            for log in logs:
                data.append({
                    "id": log.id,
                    "admin_email": log.admin.email,
                    "admin_name": f"{log.admin.firstname} {log.admin.lastname}",
                    "action": log.action,
                    "target_id": log.target_object_id,
                    "target_type": log.target_object_type,
                    "details": log.details,
                    "ip_address": log.ip_address,
                    "created_at": log.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            logger.error(f"SystemLogs Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminSupportMessagesView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            messages = SupportMessage.objects.prefetch_related('replies__admin').all().order_by('-created_at')
            data = []
            for msg in messages:
                replies = []
                for r in msg.replies.all().order_by('sent_at'):
                    replies.append({
                        "id": r.id,
                        "admin_name": f"{r.admin.firstname} {r.admin.lastname}" if r.admin else "Admin",
                        "body": r.body,
                        "sent_at": r.sent_at,
                    })
                data.append({
                    "id": msg.id,
                    "name": msg.name,
                    "email": msg.email,
                    "subject": msg.subject,
                    "message": msg.message,
                    "status": msg.status,
                    "created_at": msg.created_at,
                    "resolved_by": msg.resolved_by.email if msg.resolved_by else None,
                    "replies": replies,
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            logger.error(f"SupportMessages Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)
            
    def patch(self, request, message_id):
        try:
            msg = SupportMessage.objects.get(id=message_id)
            new_status = request.data.get('status')
            if new_status in dict(SupportMessage.STATUS_CHOICES):
                msg.status = new_status
                if new_status == 'resolved':
                    msg.resolved_by = request.user
                msg.save()
                log_admin_action(request.user, "update_support_message", msg.id, "SupportMessage", f"Status changed to {new_status}")
                return Response({"success": True, "message": "Status updated"})
            return Response({"success": False, "message": "Invalid status"}, status=400)
        except SupportMessage.DoesNotExist:
            return Response({"success": False, "message": "Message not found"}, status=404)
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminSupportMessageReplyView(APIView):
    permission_classes = [IsSupportOrHigher]

    def post(self, request, message_id):
        try:
            msg = SupportMessage.objects.get(id=message_id)
            body = request.data.get('body', '').strip()
            if not body:
                return Response({"success": False, "message": "Reply body is required"}, status=400)

            reply = SupportMessageReply.objects.create(
                support_message=msg,
                admin=request.user,
                body=body,
            )

            if msg.status == 'new':
                msg.status = 'in_progress'
                msg.save()

            EmailManager.send_support_reply_email(
                recipient_email=msg.email,
                recipient_name=msg.name,
                subject=msg.subject,
                reply_body=body,
                original_message=msg.message,
            )

            log_admin_action(request.user, "reply_support_message", msg.id, "SupportMessage", f"Reply sent to {msg.email}")

            return Response({
                "success": True,
                "message": "Reply sent",
                "data": {
                    "id": reply.id,
                    "admin_name": f"{request.user.firstname} {request.user.lastname}",
                    "body": reply.body,
                    "sent_at": reply.sent_at,
                },
                "new_status": msg.status,
            })
        except SupportMessage.DoesNotExist:
            return Response({"success": False, "message": "Message not found"}, status=404)
        except Exception as e:
            logger.error(f"SupportMessageReply Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminUserListView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            users = User.objects.all().order_by('-created_at')
            
            # Simple filtering
            role = request.query_params.get('role')
            status = request.query_params.get('status') # 'active' or 'inactive'
            
            if role:
                users = users.filter(role=role)
            if status:
                is_active = status.lower() == 'active'
                users = users.filter(isactive=is_active)
                
            data = []
            for u in users:
                data.append({
                    "id": u.id,
                    "email": u.email,
                    "firstname": u.firstname,
                    "lastname": u.lastname,
                    "role": u.role,
                    "admin_level": u.admin_level,
                    "isactive": u.isactive,
                    "registration_step": u.registration_step,
                    "subscription_tier": u.subscription_tier,
                    "created_at": u.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            logger.error(f"UserList Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminUserStatusView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            if user.role == 'admin' and request.user.admin_level != 'super_admin':
                return Response({"success": False, "message": "Cannot modify another admin"}, status=403)
                
            isactive = request.data.get('isactive')
            if isactive is not None:
                user.isactive = bool(isactive)
                user.save()
                
                action = "activate_user" if isactive else "suspend_user"
                log_admin_action(request.user, action, user.id, "User")
                
                # If suspended, invalidate tokens
                if not isactive:
                    token_manager.invalidate_all_user_tokens(str(user.id))
                    
                return Response({"success": True, "message": f"User {'activated' if isactive else 'suspended'}"})
            return Response({"success": False, "message": "isactive flag required"}, status=400)
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminPropertiesListView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            props = properties.objects.select_related('landlord').all().order_by('-created_at')
            data = []
            for p in props:
                data.append({
                    "id": p.id,
                    "title": p.title,
                    "property_type": p.property_type,
                    "landlord": f"{p.landlord.firstname} {p.landlord.lastname}",
                    "landlord_email": p.landlord.email,
                    "is_published": p.is_published,
                    "is_flagged": p.is_flagged,
                    "flag_reason": p.flag_reason,
                    "status": p.status,
                    "created_at": p.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            logger.error(f"PropertiesList Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminPropertyModerationView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def patch(self, request, property_id):
        try:
            prop = properties.objects.get(id=property_id)
            action = request.data.get('action') # 'unpublish', 'publish', 'flag'
            
            if action == 'unpublish':
                prop.is_published = False
                prop.save()
                log_admin_action(request.user, "unpublish_property", prop.id, "Property")
                return Response({"success": True, "message": "Property unpublished"})
            elif action == 'publish':
                prop.is_published = True
                prop.save()
                log_admin_action(request.user, "publish_property", prop.id, "Property")
                return Response({"success": True, "message": "Property published"})
            elif action == 'flag':
                reason = request.data.get('reason', '').strip()
                prop.is_flagged = True
                prop.flag_reason = reason or None
                prop.save()
                log_admin_action(request.user, "flag_property", prop.id, "Property", reason)
                return Response({"success": True, "message": "Property flagged"})
            elif action == 'unflag':
                prop.is_flagged = False
                prop.flag_reason = None
                prop.save()
                log_admin_action(request.user, "unflag_property", prop.id, "Property")
                return Response({"success": True, "message": "Property flag removed"})

            return Response({"success": False, "message": "Invalid action"}, status=400)
        except properties.DoesNotExist:
            return Response({"success": False, "message": "Property not found"}, status=404)
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminCreateAdminView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        try:
            email = request.data.get('email')
            password = request.data.get('password')
            firstname = request.data.get('firstname', '')
            lastname = request.data.get('lastname', '')
            admin_level = request.data.get('admin_level')

            if not email or not password or not admin_level:
                return Response({"success": False, "message": "Email, password, and admin_level are required"}, status=400)

            if admin_level not in dict(User.ADMIN_LEVEL_CHOICES):
                return Response({"success": False, "message": "Invalid admin_level"}, status=400)

            if User.objects.filter(email=email).exists():
                return Response({"success": False, "message": "Email already exists"}, status=400)

            import bcrypt
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            new_admin = User.objects.create(
                email=email,
                password=hashed_password,
                firstname=firstname,
                lastname=lastname,
                role='admin',
                admin_level=admin_level,
                email_verified=True,
                isactive=True
            )

            log_admin_action(request.user, "create_admin", new_admin.id, "User", f"Level: {admin_level}")
            return Response({"success": True, "message": "Admin user created successfully"})
        except Exception as e:
            logger.error(f"CreateAdmin Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminDeleteAdminView(APIView):
    permission_classes = [IsSuperAdmin]

    def delete(self, request, user_id):
        try:
            target_admin = User.objects.get(id=user_id, role='admin')
            if target_admin.id == request.user.id:
                return Response({"success": False, "message": "You cannot delete your own account"}, status=400)
            
            target_admin.delete()
            log_admin_action(request.user, "delete_admin", user_id, "User", f"Deleted admin user {user_id}")
            return Response({"success": True, "message": "Admin account deleted successfully"})
        except User.DoesNotExist:
            return Response({"success": False, "message": "Admin not found"}, status=404)
        except Exception as e:
            logger.error(f"DeleteAdmin Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminUserSubscriptionView(APIView):
    permission_classes = [IsSuperAdmin]

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            new_tier = request.data.get('subscription_tier')
            new_status = request.data.get('subscription_status')

            if new_tier:
                user.subscription_tier = new_tier
            if new_status:
                user.subscription_status = new_status
                
            user.save()
            log_admin_action(request.user, "update_subscription", user.id, "User", f"Tier: {new_tier}, Status: {new_status}")
            return Response({"success": True, "message": "Subscription updated"})
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminUserImpersonateView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def post(self, request, user_id):
        try:
            target_user = User.objects.get(id=user_id)
            if target_user.role == 'admin':
                return Response({"success": False, "message": "Cannot impersonate an admin"}, status=403)
                
            # Create a short-lived token for the target user (e.g., 1 hour)
            token_data = token_manager.create_token(str(target_user.id))
            
            log_admin_action(request.user, "impersonate_user", target_user.id, "User", "Generated impersonation token")
            
            response = Response({
                "success": True, 
                "message": "Impersonation active",
            })
            
            _production = os.getenv("DJANGO_PRODUCTION", "false").lower() == "true"
            response.set_cookie(
                key='padvault_impersonation_token',
                value=token_data['token'],
                httponly=True,
                samesite='Lax',
                max_age=1 * 60 * 60, # 1 hour
                secure=_production,
                path='/',
            )
            return response
            
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            logger.error(f"Impersonate Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminStopImpersonationView(APIView):
    # This might be called while impersonating, so no strict admin permission check here.
    # It just clears the cookie.
    authentication_classes = []
    permission_classes = []
    
    def post(self, request):
        response = Response({
            "success": True, 
            "message": "Stopped impersonating"
        })
        response.delete_cookie('padvault_impersonation_token', path='/')
        return response

class AdminKYCListView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            users = User.objects.filter(registration_step='kyc').order_by('-created_at')
            data = []
            for u in users:
                data.append({
                    "id": u.id,
                    "email": u.email,
                    "firstname": u.firstname,
                    "lastname": u.lastname,
                    "bank_name": u.bank_name,
                    "account_number": u.account_number,
                    "created_at": u.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminKYCOverrideView(APIView):
    permission_classes = [IsSupportOrHigher]

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            if user.registration_step != 'kyc':
                return Response({"success": False, "message": "User is not pending KYC"}, status=400)
                
            user.registration_step = 'complete'
            user.save()
            log_admin_action(request.user, "override_kyc", user.id, "User", "Manual KYC approval")
            return Response({"success": True, "message": "KYC manually approved"})
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminLeasesListView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            leases = RentInitiation.objects.select_related('rental_property', 'tenant', 'landlord').all().order_by('-created_at')
            data = []
            for lease in leases:
                data.append({
                    "id": lease.id,
                    "property_title": lease.rental_property.title,
                    "tenant_email": lease.tenant.email if lease.tenant else lease.tenant_email,
                    "landlord_email": lease.landlord.email,
                    "status": lease.status,
                    "start_date": lease.proposed_start_date,
                    "end_date": lease.proposed_end_date,
                    "rent_amount": lease.proposed_amount,
                    "created_at": lease.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminMaintenanceListView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request):
        try:
            requests = MaintenanceRequest.objects.select_related('property').all().order_by('-created_at')
            data = []
            for req in requests:
                data.append({
                    "id": req.id,
                    "title": req.title,
                    "property_title": req.property.title,
                    "tenant_email": req.reported_by_name,
                    "status": req.status,
                    "priority": req.priority,
                    "created_at": req.created_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

class AdminUserProfileView(APIView):
    permission_classes = [IsSupportOrHigher]

    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)

            # Properties (landlord only)
            user_properties = []
            if user.role == 'landlord':
                for p in properties.objects.filter(landlord=user).order_by('-created_at')[:10]:
                    user_properties.append({
                        "id": p.id,
                        "title": p.title,
                        "property_type": p.property_type,
                        "is_published": p.is_published,
                        "status": p.status,
                        "created_at": p.created_at,
                    })

            # Active leases
            leases = RentInitiation.objects.select_related('rental_property').filter(
                landlord=user
            ).order_by('-created_at')[:5] if user.role == 'landlord' else \
            RentInitiation.objects.select_related('rental_property').filter(
                tenant=user
            ).order_by('-created_at')[:5]

            lease_data = []
            for l in leases:
                lease_data.append({
                    "id": l.id,
                    "property_title": l.rental_property.title,
                    "status": l.status,
                    "rent_amount": str(l.proposed_amount),
                    "start_date": l.proposed_start_date,
                    "end_date": l.proposed_end_date,
                })

            # Recent transactions
            txns = Transaction.objects.filter(payer=user).order_by('-initiated_at')[:10]
            txn_data = [{
                "id": t.id,
                "reference": t.reference,
                "amount": str(t.amount),
                "type": t.transaction_type,
                "status": t.status,
                "created_at": t.initiated_at,
            } for t in txns]

            # Support messages from this email
            support_msgs = SupportMessage.objects.filter(email=user.email).order_by('-created_at')[:5]
            support_data = [{
                "id": m.id,
                "subject": m.subject,
                "status": m.status,
                "created_at": m.created_at,
            } for m in support_msgs]

            log_admin_action(request.user, "view_user_profile", user.id, "User")

            return Response({"success": True, "data": {
                "id": user.id,
                "email": user.email,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "role": user.role,
                "admin_level": user.admin_level,
                "isactive": user.isactive,
                "registration_step": user.registration_step,
                "subscription_tier": user.subscription_tier,
                "subscription_status": getattr(user, 'subscription_status', None),
                "created_at": user.created_at,
                "bank_name": getattr(user, 'bank_name', None),
                "account_number": getattr(user, 'account_number', None),
                "properties": user_properties,
                "leases": lease_data,
                "transactions": txn_data,
                "support_messages": support_data,
            }})
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            logger.error(f"UserProfile Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminUserNotifyView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            title = request.data.get('title', '').strip()
            message = request.data.get('message', '').strip()
            send_email = request.data.get('send_email', False)

            if not title or not message:
                return Response({"success": False, "message": "Title and message are required"}, status=400)

            Notification.objects.create(
                user=user,
                title=title,
                body=message,
                notification_type='system',
            )

            if send_email:
                EmailManager.send_admin_notification_email(user.email, user.firstname, title, message)

            log_admin_action(request.user, "notify_user", user.id, "User", f"Title: {title}")
            return Response({"success": True, "message": "Notification sent"})
        except User.DoesNotExist:
            return Response({"success": False, "message": "User not found"}, status=404)
        except Exception as e:
            logger.error(f"NotifyUser Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminUserBulkActionView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def post(self, request):
        try:
            user_ids = request.data.get('user_ids', [])
            action = request.data.get('action')

            if not user_ids or action not in ('suspend', 'activate'):
                return Response({"success": False, "message": "user_ids and valid action required"}, status=400)

            users = User.objects.filter(id__in=user_ids, role__in=['landlord', 'tenant'])
            updated = 0
            for u in users:
                u.isactive = (action == 'activate')
                u.save()
                if action == 'suspend':
                    token_manager.invalidate_all_user_tokens(str(u.id))
                log_admin_action(request.user, f"{action}_user", u.id, "User", "Bulk action")
                updated += 1

            return Response({"success": True, "message": f"{updated} user(s) {action}d", "updated": updated})
        except Exception as e:
            logger.error(f"BulkUserAction Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminPropertyBulkActionView(APIView):
    permission_classes = [IsModeratorOrHigher]

    def post(self, request):
        try:
            property_ids = request.data.get('property_ids', [])
            action = request.data.get('action')

            if not property_ids or action not in ('publish', 'unpublish'):
                return Response({"success": False, "message": "property_ids and valid action required"}, status=400)

            props = properties.objects.filter(id__in=property_ids)
            updated = 0
            for p in props:
                p.is_published = (action == 'publish')
                p.save()
                log_admin_action(request.user, f"{action}_property", p.id, "Property", "Bulk action")
                updated += 1

            return Response({"success": True, "message": f"{updated} propert{'y' if updated == 1 else 'ies'} {action}ed", "updated": updated})
        except Exception as e:
            logger.error(f"BulkPropertyAction Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminInvoiceListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            from Invoices.models import Invoice
            invoices = Invoice.objects.select_related('issued_by').all().order_by('-issued_at')
            data = []
            for inv in invoices:
                data.append({
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "issued_by_email": inv.issued_by.email if inv.issued_by else None,
                    "issued_to_name": inv.issued_to_name,
                    "issued_to_email": inv.issued_to_email,
                    "total": str(inv.total),
                    "status": inv.status,
                    "due_date": inv.due_date,
                    "paid_at": inv.paid_at,
                    "notes": inv.notes,
                    "issued_at": inv.issued_at,
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            logger.error(f"InvoiceList Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminInvoiceOverrideView(APIView):
    permission_classes = [IsSuperAdmin]

    def patch(self, request, invoice_id):
        try:
            from Invoices.models import Invoice
            inv = Invoice.objects.get(id=invoice_id)
            new_status = request.data.get('status')
            notes = request.data.get('notes', '').strip()

            valid_statuses = [s[0] for s in Invoice.INVOICE_STATUS]
            if new_status not in valid_statuses:
                return Response({"success": False, "message": "Invalid status"}, status=400)

            inv.status = new_status
            if new_status == 'paid' and not inv.paid_at:
                inv.paid_at = timezone.now()
            if notes:
                inv.notes = notes
            inv.save()

            log_admin_action(request.user, "override_invoice", inv.id, "Invoice",
                             f"Status → {new_status}{' | ' + notes if notes else ''}")
            return Response({"success": True, "message": f"Invoice marked as {new_status}"})
        except Exception as e:
            logger.error(f"InvoiceOverride Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminExportView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        export_type = request.query_params.get('type', '')

        def stream_csv(headers, rows, filename):
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(headers)
            yield buf.getvalue()
            buf.seek(0); buf.truncate()
            for row in rows:
                writer.writerow(row)
                yield buf.getvalue()
                buf.seek(0); buf.truncate()

        try:
            if export_type == 'users':
                qs = User.objects.all().order_by('-created_at')
                headers = ['Email', 'First Name', 'Last Name', 'Role', 'Tier', 'Active', 'Joined']
                rows = ((u.email, u.firstname, u.lastname, u.role,
                         u.subscription_tier, u.isactive,
                         u.created_at.strftime('%Y-%m-%d')) for u in qs)
                filename = 'padvault_users.csv'

            elif export_type == 'transactions':
                qs = Transaction.objects.select_related('payer').all().order_by('-initiated_at')
                headers = ['Reference', 'User Email', 'Amount', 'Type', 'Status', 'Date']
                rows = ((t.reference, t.payer.email if t.payer else '',
                         str(t.amount), t.transaction_type,
                         t.status, t.initiated_at.strftime('%Y-%m-%d %H:%M')) for t in qs)
                filename = 'padvault_transactions.csv'

            elif export_type == 'leases':
                qs = RentInitiation.objects.select_related('rental_property', 'tenant', 'landlord').all().order_by('-created_at')
                headers = ['Property', 'Tenant Email', 'Landlord Email', 'Rent Amount', 'Start Date', 'End Date', 'Status']
                rows = ((l.rental_property.title,
                         l.tenant.email if l.tenant else l.tenant_email,
                         l.landlord.email,
                         str(l.proposed_amount),
                         str(l.proposed_start_date), str(l.proposed_end_date),
                         l.status) for l in qs)
                filename = 'padvault_leases.csv'

            else:
                return Response({"success": False, "message": "Invalid export type. Use: users, transactions, leases"}, status=400)

            log_admin_action(request.user, f"export_{export_type}", details=f"CSV export: {export_type}")
            response = StreamingHttpResponse(stream_csv(headers, rows, filename), content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        except Exception as e:
            logger.error(f"Export Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminBroadcastView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        try:
            title      = request.data.get('title', '').strip()
            message    = request.data.get('message', '').strip()
            segment    = request.data.get('segment', 'all')
            send_email = request.data.get('send_email', False)

            if not title or not message:
                return Response({"success": False, "message": "Title and message are required"}, status=400)

            qs = User.objects.filter(isactive=True, role__in=['landlord', 'tenant'])
            if segment == 'landlords':
                qs = qs.filter(role='landlord')
            elif segment == 'tenants':
                qs = qs.filter(role='tenant')
            elif segment == 'premium':
                qs = qs.filter(subscription_tier='premium')

            notifications = [
                Notification(user=u, title=title, body=message, notification_type='system')
                for u in qs
            ]
            Notification.objects.bulk_create(notifications)

            emails_sent = 0
            if send_email:
                for u in qs:
                    try:
                        EmailManager.send_admin_notification_email(u.email, u.firstname, title, message)
                        emails_sent += 1
                    except Exception:
                        pass

            log_admin_action(request.user, "broadcast_notification", details=f"Segment: {segment} | {len(notifications)} users")
            return Response({"success": True, "message": "Broadcast sent",
                             "data": {"users_notified": len(notifications), "emails_sent": emails_sent}})
        except Exception as e:
            logger.error(f"Broadcast Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminConfigView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            configs = SystemConfig.objects.all()
            data = {c.key: c.value for c in configs}
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)

    def patch(self, request):
        try:
            key   = request.data.get('key', '').strip()
            value = request.data.get('value', '').strip()
            if not key or not value:
                return Response({"success": False, "message": "key and value are required"}, status=400)

            ALLOWED_KEYS = {'subscription_price', 'platform_fee_percentage'}
            if key not in ALLOWED_KEYS:
                return Response({"success": False, "message": f"Unknown config key: {key}"}, status=400)

            try:
                numeric = float(value)
            except ValueError:
                return Response({"success": False, "message": "Value must be a number"}, status=400)

            if key == 'subscription_price' and numeric <= 0:
                return Response({"success": False, "message": "Subscription price must be greater than 0"}, status=400)

            if key == 'platform_fee_percentage' and not (0 <= numeric <= 50):
                return Response({"success": False, "message": "Platform fee must be between 0% and 50%"}, status=400)

            SystemConfig.objects.update_or_create(
                key=key,
                defaults={'value': value, 'updated_by': request.user}
            )
            log_admin_action(request.user, "update_config", details=f"{key} → {value}")
            return Response({"success": True, "message": f"Config '{key}' updated"})
        except Exception as e:
            logger.error(f"Config Error: {e}")
            return Response({"success": False, "message": "Internal server error"}, status=500)


class AdminTransactionsListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            transactions = Transaction.objects.select_related('payer').all().order_by('-initiated_at')
            data = []
            for t in transactions:
                data.append({
                    "id": t.id,
                    "reference": t.reference,
                    "user_email": t.payer.email if t.payer else None,
                    "amount": t.amount,
                    "status": t.status,
                    "transaction_type": t.transaction_type,
                    "created_at": t.initiated_at
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "message": "Internal server error"}, status=500)
