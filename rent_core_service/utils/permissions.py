from rest_framework.permissions import BasePermission

class IsAuthenticated(BasePermission):
    """
    Standard authentication check for DRF views.
    Ensures request.user is set and authenticated.
    """
    message = "Authentication credentials were not provided or are invalid."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

class IsSuperAdmin(BasePermission):
    """
    Allows access only to super admins.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.role == 'admin' and 
            request.user.admin_level == 'super_admin'
        )

class IsModeratorOrHigher(BasePermission):
    """
    Allows access to moderators and super admins.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.role == 'admin' and 
            request.user.admin_level in ['super_admin', 'moderator']
        )

class IsSupportOrHigher(BasePermission):
    """
    Allows access to support, moderators, and super admins.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.role == 'admin' and 
            request.user.admin_level in ['super_admin', 'moderator', 'support']
        )
