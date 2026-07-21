import logging
from rest_framework import authentication
from rest_framework import exceptions
from Users.models import User, token_manager

logger = logging.getLogger(__name__)

class PadvaultJWTAuthentication(authentication.BaseAuthentication):
    """
    Custom DRF Authentication class that checks for JWT in HttpOnly cookies
    or Authorization header.
    """
    def authenticate(self, request):
        # Resolve token — cookie first, Authorization header fallback
        token = request.COOKIES.get('padvault_token')
        if not token:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('JWT '):
                token = auth_header[4:]

        if not token:
            return None # Fallback to other auth classes or allow if public

        try:
            token_data = token_manager.validate_token(token)
            if not token_data or 'user_id' not in token_data:
                raise exceptions.AuthenticationFailed("Invalid or expired token.")

            user = User.objects.get(id=token_data['user_id'])
            
            if not user.isactive:
                raise exceptions.AuthenticationFailed("This account has been deactivated.")

            # Attach token metadata for use in views
            request.token_data = token_data
            
            return (user, token) # Success

        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed("User account not found.")
        except exceptions.AuthenticationFailed:
            raise
        except Exception as e:
            logger.error(f"Internal Auth Error: {e}", exc_info=True)
            return None
