import json
from django.http import JsonResponse
from django.views import View
from django.db.models import Q, Count
from ..models import properties  
from rest_framework.permissions import BasePermission
import logging

# Create your views here.
# Base view class for properties
class BasePropertyView(View):
    """Base class with common property methods"""

    def get_location_data(self, prop):
        """Extract address fields from the related Address object."""
        if hasattr(prop, 'address_id') and prop.address_id:
            addr = prop.address_id
            return {
                "street": addr.street or "",
                "city": addr.city or "",
                "state_province": addr.state_province or "",
                "country": addr.country or "Nigeria",
                "landmark": getattr(addr, 'landmark', '') or "",
            }
        return {"street": "", "city": "", "state_province": "", "country": "Nigeria", "landmark": ""}

    def get_property_image(self, property):
        """Get image URL with placeholder fallback"""
        if property.main_image and hasattr(property.main_image, 'url'):
            return property.main_image.url, False
        
        if property.image_urls and len(property.image_urls) > 0:
            return property.image_urls[0], False
        
        # Placeholder fallback
        placeholders = {
            'apartment': 'https://placehold.co/400x300/4F46E5/FFFFFF?text=Apartment',
            'house': 'https://placehold.co/400x300/10B981/FFFFFF?text=House',
            'condo': 'https://placehold.co/400x300/F59E0B/FFFFFF?text=Condo', 
            'studio': 'https://placehold.co/400x300/EF4444/FFFFFF?text=Studio',
            'commercial': 'https://placehold.co/400x300/8B5CF6/FFFFFF?text=Commercial'
        }
        placeholder = placeholders.get(property.property_type, 
                                     'https://placehold.co/400x300/6B7280/FFFFFF?text=Property')
        return placeholder, True
    
class IsLandlordOrAdmin(BasePermission):
    """
    Permission to only allow landlords and admins to access views.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not hasattr(request.user, 'is_authenticated') or not request.user.is_authenticated:
            return False
        
        # Check if user has the required role
        if hasattr(request.user, 'role') and request.user.role in ['landlord', 'admin']:
            return True
        
        return False

class IsTenantOrAdmin(BasePermission):
    """
    Permission to only allow tenants and admins to access views.
    Useful for endpoints like saving properties, viewing rentals, etc.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not hasattr(request.user, 'is_authenticated') or not request.user.is_authenticated:
            return False
        
        # Check if user has the required role
        if hasattr(request.user, 'role') and request.user.role in ['tenant', 'admin']:
            return True
        
        return False

class IsAdminOnly(BasePermission):
    """
    Permission to only allow admin users to access views.
    For superuser-only functionality.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated and is admin
        return (hasattr(request.user, 'is_authenticated') and 
                request.user.is_authenticated and 
                hasattr(request.user, 'role') and 
                request.user.role == 'admin')