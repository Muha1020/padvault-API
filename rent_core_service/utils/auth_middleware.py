# utils/auth_middleware.py
import logging
import re
from django.http import JsonResponse

logger = logging.getLogger(__name__)

def error_response(message, status_code):
    return JsonResponse({
        "success": False,
        "message": message,
        "data": None,
        "error_code": status_code
    }, status=status_code)

class TokenAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        
        # Exact public endpoints
        self.public_endpoints = [
            # Authentication
            '/api/users/login/',
            '/api/users/register/',
            
            # Test endpoints
            '/api/users/success/',
            '/api/users/error/',
            '/api/users/exception/',
            '/api/users/html-response/',
            '/api/users/not-found/',
            '/api/users/unauthorized/',
            
            # Health check
            '/health/',
            
            # Webhook endpoints
            '/api/transactions/monnify-webhook/',
            
            # Property endpoints (EXACT PATHS)
            '/api/properties/',
            '/api/properties/search/',
            '/api/properties/filter/',
            '/api/properties/categories/',
            '/api/properties/featured/',
        ]
    
        # Regex patterns for dynamic property endpoints
        self.public_patterns = [
            # Property detail views
            r'^/api/properties/[0-9a-fA-F-]+/view/$',  # UUID format
            r'^/api/properties/\d+/view/$',            # Numeric ID format
            
            # Rent public endpoints
            r'^/api/rent/lease/[0-9a-fA-F-]+/$',
            r'^/api/rent/lease/[0-9a-fA-F-]+/sign/$',
            r'^/api/rent/initiations/public/$',
            
            # Document proxy
            r'^/api/rent/documents/[0-9a-fA-F-]+/view/$',
        ]
    
    def _is_public_endpoint(self, path):
        """Check if path is public"""
        # Check exact matches first
        if path in self.public_endpoints:
            return True
        
        # Check regex patterns
        for pattern in self.public_patterns:
            if re.match(pattern, path):
                return True
        
        return False
    
    def __call__(self, request):
        # Check if this is a public endpoint
        if self._is_public_endpoint(request.path):
            logger.info(f"Allowing public endpoint: {request.path}")
            return self.get_response(request)
        
        logger.info(f"Protecting endpoint: {request.path}")
        # Resolve token — cookie takes priority, Authorization header is fallback
        # Check for impersonation token first
        impersonation_token = request.COOKIES.get('padvault_impersonation_token')
        token = request.COOKIES.get('padvault_token')
        
        if not token:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.startswith('JWT '):
                token = auth_header[4:]

        if not token:
            logger.warning("No JWT token found in cookie or Authorization header")
            return error_response("Authentication token required.", 401)

        logger.info(f"Token extracted: {token[:10]}...")  # Log first 10 chars for security
        
        # Validation helper function
        def validate_user_token(t):
            from Users.models import token_manager 
            td = token_manager.validate_token(t)
            if not td or 'user_id' not in td:
                return None
            return td
            
        admin_data = None
        if impersonation_token:
            admin_data = validate_user_token(token)
            if not admin_data:
                return error_response("Admin session expired.", 401)
            token_to_validate = impersonation_token
        else:
            token_to_validate = token
            
        try:
            token_data = validate_user_token(token_to_validate)
            if token_data:
                logger.info(f"Token validation result: {token_data}")
        except ImportError as e:
            logger.error(f"Import error in token manager: {str(e)}")
            return error_response("Authentication system error.", 500)
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}", exc_info=True)
            return error_response("Authentication error.", 500)
        
        if not token_data:
            logger.warning("Token validation failed - invalid or expired token")
            return error_response("Invalid or expired token.", 401)
        
        if 'user_id' not in token_data:
            logger.error("Token data missing 'user_id' field")
            return error_response("Authentication token invalid.", 401)
        
        # Add user info to request using our custom user model
        try:
            from Users.models import User  
            user = User.objects.get(id=token_data['user_id'])

            if not user.isactive:
                logger.warning(f"Blocked deactivated account: {user.email}")
                return error_response("This account has been deactivated.", 401)

            logger.info(f"User found: {user.email}, Role: {user.role}")
            
            # CRITICAL: Set the user properly for Django compatibility
            request.user = user
            request._user = user  # Django internally checks this
            
            if admin_data:
                admin_user = User.objects.get(id=admin_data['user_id'])
                request.impersonator = admin_user
                logger.info(f"Admin {admin_user.email} is impersonating {user.email}")
            
            # Verify the user has the required Django authentication attributes
            logger.info(f"User is_authenticated: {getattr(user, 'is_authenticated', 'MISSING')}")
            logger.info(f"User is_anonymous: {getattr(user, 'is_anonymous', 'MISSING')}")
            
            # Set token data for potential use in views
            request.token_data = token_data
            
        except User.DoesNotExist:
            logger.error(f"User not found with ID: {token_data.get('user_id')}")
            return error_response("User account not found.", 401)
        except Exception as e:
            logger.error(f"User lookup failed: {str(e)}", exc_info=True)
            return error_response("User authentication failed.", 401)
        
        logger.info(f"Authentication successful for user: {user.email}")
        logger.info("Middleware authentication complete")
        
        # Continue to the view
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Additional method to ensure user is available during view processing
        """
        if hasattr(request, 'user'):
            logger.debug(f"Process view - User: {getattr(request.user, 'email', 'No email')}")