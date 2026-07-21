# properties/tenant_views.py
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db import IntegrityError

from ..models import properties, saved_properties
from ..serializers import SavePropertySerializer, SavedPropertySerializer, PropertyListSerializer
from .base import IsTenantOrAdmin


"""Test Tenant User
{
 "email": "tenant@abuja.com",
    "firstname": "Tunde",
    "lastname": "Tenant",
    "password": "Tenant@123",
    "role": "TENANT",
    "phone": "08012345678"
}
"""
class SavePropertyView(APIView):
    """
    POST /api/properties/save/<property_id>/ - Save a property to user's favorites
    """
    permission_classes = [IsTenantOrAdmin]
    
    def post(self, request, property_id, format=None):
        """
        Save a property to the authenticated user's favorites
        """
        try:
            # Validate the property exists using your existing serializer
            serializer = SavePropertySerializer(data={'property_id': property_id})
            
            if serializer.is_valid():
                property_obj = properties.objects.get(id=property_id)
                
                # Additional check: ensure property is published
                if not property_obj.is_published:
                    return Response({
                        "success": False,
                        "message": "Cannot save an unpublished property",
                        "code": "UNPUBLISHED_PROPERTY"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Additional check: ensure property is available
                if property_obj.status != 'available':
                    return Response({
                        "success": False,
                        "message": f"Cannot save a property that is {property_obj.status}",
                        "code": "PROPERTY_UNAVAILABLE"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Check if already saved
                if saved_properties.objects.filter(user_id=request.user, property_id=property_obj).exists():
                    return Response({
                        "success": False,
                        "message": "Property is already in your saved list",
                        "code": "ALREADY_SAVED"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Create the saved property entry
                saved_property = saved_properties.objects.create(
                    user_id=request.user,
                    property_id=property_obj
                )
                
                # Use your existing SavedPropertySerializer for the response
                response_serializer = SavedPropertySerializer(saved_property, context={'request': request})
                
                return Response({
                    "success": True,
                    "message": "Property saved successfully",
                    "data": response_serializer.data
                }, status=status.HTTP_201_CREATED)
                
            else:
                return Response({
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                    "code": "VALIDATION_ERROR"
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except properties.DoesNotExist:
            return Response({
                "success": False,
                "message": "Property not found",
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error saving property {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while saving the property",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UnsavePropertyView(APIView):
    """
    DELETE /api/properties/unsave/<property_id>/ - Remove a property from user's favorites
    """
    permission_classes = [IsTenantOrAdmin]
    
    def delete(self, request, property_id, format=None):
        """
        Remove a property from the authenticated user's favorites
        """
        try:
            # Get the saved property entry
            saved_property = get_object_or_404(
                saved_properties,
                user_id=request.user,
                property_id=property_id
            )
            
            # Use serializer to get property details before deletion
            property_data = SavedPropertySerializer(saved_property, context={'request': request}).data
            
            saved_property.delete()
            
            return Response({
                "success": True,
                "message": "Property removed from saved list",
                "data": {
                    "property_id": property_id,
                    "property_title": property_data['property_details']['title'] if property_data.get('property_details') else "Unknown Property"
                }
            }, status=status.HTTP_200_OK)
            
        except saved_properties.DoesNotExist:
            return Response({
                "success": False,
                "message": "Property not found in your saved list",
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error unsaving property {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while removing the property",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SavedPropertiesListView(APIView):
    """
    GET /api/properties/saved/ - Get all saved properties for the authenticated user
    """
    permission_classes = [IsTenantOrAdmin]
    
    def get(self, request, format=None):
        """
        Retrieve all properties saved by the authenticated user
        """
        try:
            # Get all saved properties for the current user with related data
            saved_props = saved_properties.objects.filter(
                user_id=request.user
            ).select_related('property_id', 'user_id').order_by('-created_at')
            
            # Use your existing serializer
            serializer = SavedPropertySerializer(saved_props, many=True, context={'request': request})
            
            return Response({
                "success": True,
                "message": "Saved properties retrieved successfully",
                "data": serializer.data,
                "count": saved_props.count()
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error retrieving saved properties: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while retrieving saved properties",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CheckSavedStatusView(APIView):
    """
    GET /api/properties/<property_id>/saved-status/ - Check if a property is saved by the user
    """
    permission_classes = [IsTenantOrAdmin]
    
    def get(self, request, property_id, format=None):
        """
        Check if a specific property is saved by the authenticated user
        """
        try:
            # Check if property exists first
            property_obj = get_object_or_404(properties, id=property_id)
            
            is_saved = saved_properties.objects.filter(
                user_id=request.user,
                property_id=property_obj
            ).exists()
            
            # Get saved property details if it exists
            saved_details = None
            if is_saved:
                saved_prop = saved_properties.objects.get(
                    user_id=request.user,
                    property_id=property_obj
                )
                saved_details = SavedPropertySerializer(saved_prop, context={'request': request}).data
            
            return Response({
                "success": True,
                "message": "Saved status retrieved successfully",
                "data": {
                    "property_id": property_id,
                    "is_saved": is_saved,
                    "saved_details": saved_details
                }
            }, status=status.HTTP_200_OK)
            
        except properties.DoesNotExist:
            return Response({
                "success": False,
                "message": "Property not found",
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error checking saved status for property {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while checking saved status",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)