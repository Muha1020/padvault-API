# properties/landlord_views.py
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q

from ..models import properties
from ..serializers import PropertyCreateSerializer, PropertyBaseSerializer, PropertyStatusSerializer, PropertyListSerializer, PropertyUpdateSerializer
from .base import IsLandlordOrAdmin, BasePropertyView
from utils.rate_limit import rate_limit


#property create view
@method_decorator(rate_limit(limit=30, window_seconds=3600, endpoint_key='property_create'), name='post')
class LandlordPropertyCreateView(BasePropertyView, APIView):
    """
    POST /api/properties/landlord/create/
    Create a new property listing for the authenticated landlord.
    """
    parser_classes = [JSONParser, MultiPartParser]
    permission_classes = [IsLandlordOrAdmin]
    
    def post(self, request, format=None):
        try:
            # Get the authenticated landlord (user)
            landlord = request.user

            # Verify user is a landlord
            if not hasattr(landlord, 'role') or landlord.role != 'landlord':
                return Response({
                    "success": False,
                    "message": "Access denied. Only landlords can view this endpoint.",
                    "data": None
                }, status=status.HTTP_403_FORBIDDEN)

            # Freemium gate — free tier is capped at 5 units
            if getattr(landlord, 'subscription_tier', 'free') == 'free':
                unit_count = properties.objects.filter(landlord=landlord).count()
                if unit_count >= 5:
                    return Response({
                        "success": False,
                        "message": "Free plan is limited to 5 properties. Upgrade to premium to add more.",
                        "code": "UPGRADE_REQUIRED"
                    }, status=status.HTTP_403_FORBIDDEN)

            # Make a mutable copy of the request data
            data = request.data.copy()
            
            # Remove landlord from data if present - it will be set automatically
            data.pop('landlord', None)
            
            # Add landlord to validated data for creation
            data['landlord'] = landlord.id
            
            # Validate and create property
            serializer = PropertyCreateSerializer(
                data=data, 
                context={'request': request}
            )
            
            if serializer.is_valid():
                # Save the property with nested address
                property_instance = serializer.save(landlord=landlord)
                
                # Get the full property data with location
                property_data = PropertyBaseSerializer(property_instance, context={'request': request}).data
                
                # ADDED: Add location section to response
                property_data["location"] = self.get_location_data(property_instance)
                
                return Response({
                    "success": True,
                    "message": "Property created successfully",
                    "data": property_data
                }, status=status.HTTP_201_CREATED)
                
            else:
                return Response({
                    "success": False,
                    "message": "Validation failed. Please check the errors.",
                    "errors": serializer.errors,
                    "code": "VALIDATION_ERROR"
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating property: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while creating property",
                "data": None,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#landlord detail view
class LandlordPropertyDetailView(BasePropertyView, APIView):
    """
    GET /api/properties/landlord/<property_id>/
    Get detailed information about a specific property belonging to the authenticated landlord.
    
    PUT /api/properties/landlord/<property_id>/
    Update a specific property belonging to the authenticated landlord.
    """
    parser_classes = [JSONParser, MultiPartParser]
    permission_classes = [IsLandlordOrAdmin]
    
    def get(self, request, property_id, format=None):
        """
        Retrieve detailed information about a specific property.
        """
        try:
            # Get the property object with ownership restriction
            qs = properties.objects.select_related('address_id')
            if request.user.role == 'admin':
                # Admins can access any property
                property_obj = qs.get(id=property_id)
            else:
                # Landlords can only access their own properties
                property_obj = qs.get(id=property_id, landlord=request.user)
            
            # Serialize the property data
            serializer = PropertyBaseSerializer(property_obj, context={'request': request})
            property_data = serializer.data
            
            # ADDED: Add location section to response
            property_data["location"] = self.get_location_data(property_obj)
            
            return Response({
                "success": True,
                "message": "Property retrieved successfully",
                "data": property_data
            }, status=status.HTTP_200_OK)
            
        except properties.DoesNotExist:
            if request.user.role == 'landlord':
                message = "Property not found or you don't have permission to view it."
            else:
                message = "Property not found."
                
            return Response({
                "success": False,
                "message": message,
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error retrieving property {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while retrieving the property.",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request, property_id, format=None):
        """
        Update a property with full replacement
        """
        return self._update_property(request, property_id, partial=False)

    def patch(self, request, property_id, format=None):
        """
        Partially update a property
        """
        return self._update_property(request, property_id, partial=True)

    def delete(self, request, property_id, format=None):
        """
        DELETE /api/properties/landlord/<property_id>/
        Permanently delete a property belonging to the authenticated landlord.
        """
        try:
            qs = properties.objects.all()
            if request.user.role == 'admin':
                property_obj = qs.get(id=property_id)
            else:
                property_obj = qs.get(id=property_id, landlord=request.user)

            property_obj.delete()

            return Response({
                "success": True,
                "message": "Property deleted successfully.",
            }, status=status.HTTP_200_OK)

        except properties.DoesNotExist:
            return Response({
                "success": False,
                "message": "Property not found or you don't have permission to delete it.",
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting property {property_id}: {str(e)}", exc_info=True)
            return Response({
                "success": False,
                "message": "An error occurred while deleting the property.",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _update_property(self, request, property_id, partial=False):
        """
        Shared method for PUT and PATCH requests
        """
        try:
            # Get the property object with ownership restriction
            qs = properties.objects.select_related('address_id')
            if request.user.role == 'admin':
                property_obj = qs.get(id=property_id)
            else:
                property_obj = qs.get(id=property_id, landlord=request.user)

            # Make a mutable copy of the request data
            data = request.data.copy()
            
            # Remove landlord from data if present - cannot change ownership
            data.pop('landlord', None)
            
            # Use PropertyUpdateSerializer for updates
            serializer = PropertyUpdateSerializer(
                property_obj, 
                data=data, 
                partial=partial,
                context={'request': request}
            )
            
            if serializer.is_valid():
                # Save the updated property
                property_instance = serializer.save()
                
                # Get updated property data
                property_data = PropertyBaseSerializer(property_instance, context={'request': request}).data
                
                # ADDED: Add location section to response
                property_data["location"] = self.get_location_data(property_instance)
                
                return Response({
                    "success": True,
                    "message": "Property updated successfully",
                    "data": property_data
                }, status=status.HTTP_200_OK)
                
            else:
                return Response({
                    "success": False,
                    "message": "Validation failed. Please check the errors.",
                    "errors": serializer.errors,
                    "code": "VALIDATION_ERROR"
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except properties.DoesNotExist:
            message = "Property not found or you don't have permission to update it."
            return Response({
                "success": False,
                "message": message,
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error updating property {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while updating the property.",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#landlord property list view with filtering and pagination       
class LandlordPropertyPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class LandlordPropertyListView(BasePropertyView, APIView):
    """
    API endpoint for landlords to list their properties with filtering and pagination
    """
    permission_classes = [IsLandlordOrAdmin]
    pagination_class = LandlordPropertyPagination

    def get(self, request):
        try:
            # Get the authenticated landlord
            landlord = request.user
            
            # Get query parameters for filtering
            property_type = request.GET.get('type')
            status_filter = request.GET.get('status')
            is_published = request.GET.get('published')
            is_featured = request.GET.get('featured')
            search = request.GET.get('search')
            ordering = request.GET.get('ordering', '-created_at')
            
            # Start with all properties belonging to this landlord
            landlord_properties = properties.objects.filter(landlord=landlord).select_related('address_id')  # ADDED: Optimize query
            
            # Apply filters
            if property_type:
                landlord_properties = landlord_properties.filter(property_type=property_type)
            
            if status_filter:
                landlord_properties = landlord_properties.filter(status=status_filter)
            
            if is_published is not None:
                is_published_bool = is_published.lower() == 'true'
                landlord_properties = landlord_properties.filter(is_published=is_published_bool)
            
            if is_featured is not None:
                is_featured_bool = is_featured.lower() == 'true'
                landlord_properties = landlord_properties.filter(is_featured=is_featured_bool)
            
            if search:
                landlord_properties = landlord_properties.filter(
                    Q(title__icontains=search) | 
                    Q(description__icontains=search)
                )
            
            # Apply ordering
            allowed_ordering = ['created_at', '-created_at', 'title', '-title', 'yearly_rent', '-yearly_rent', 'status']
            if ordering.lstrip('-') in [field.lstrip('-') for field in allowed_ordering]:
                landlord_properties = landlord_properties.order_by(ordering)
            else:
                landlord_properties = landlord_properties.order_by('-created_at')
            
            # Paginate the results
            paginator = self.pagination_class()
            paginated_properties = paginator.paginate_queryset(landlord_properties, request)
            
            # Serialize the data
            serializer = PropertyListSerializer(paginated_properties, many=True, context={'request': request})
            properties_data = serializer.data

            # ADDED: Add location to each property in the list
            for i, prop_data in enumerate(properties_data):
                properties_data[i]["location"] = self.get_location_data(paginated_properties[i])

            # Return a flat Response with 'success' at the top level.
            # DRF's get_paginated_response() nests everything under "results", which
            # causes GlobalResponseMiddleware to re-wrap the body (no top-level 'success').
            # Returning a plain Response keeps the middleware pass-through path happy.
            return Response({
                "success": True,
                "message": "Properties retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": properties_data
            })
            
        except Exception as e:
            return Response({
                "success": False,
                "message": "An error occurred while fetching properties",
                "data": None,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#property status update view
class PropertyStatusUpdateView(BasePropertyView, APIView):
    """
    PATCH /api/properties/landlord/<property_id>/status/
    Update property status fields (is_published, is_featured, status) for a specific property.
    """
    permission_classes = [IsLandlordOrAdmin]
    
    def patch(self, request, property_id, format=None):
        """
        Update property status fields.
        """
        try:
            # Get the property with ownership restriction
            qs = properties.objects.select_related('address_id')
            if request.user.role == 'admin':
                property_obj = qs.get(id=property_id)
            else:
                property_obj = qs.get(id=property_id, landlord=request.user)

            # Validate and update status
            serializer = PropertyStatusSerializer(
                data=request.data,
                context={'instance': property_obj}
            )
            
            if serializer.is_valid():
                # Update the status fields
                update_data = {}
                if 'is_published' in serializer.validated_data:
                    property_obj.is_published = serializer.validated_data['is_published']
                    update_data['is_published'] = property_obj.is_published
                
                if 'is_featured' in serializer.validated_data:
                    property_obj.is_featured = serializer.validated_data['is_featured']
                    update_data['is_featured'] = property_obj.is_featured
                
                if 'status' in serializer.validated_data:
                    property_obj.status = serializer.validated_data['status']
                    update_data['status'] = property_obj.status
                
                # Save only if there are changes
                if update_data:
                    property_obj.save()
                
                # Return full property data
                property_serializer = PropertyBaseSerializer(property_obj, context={'request': request})
                property_data = property_serializer.data
                
                # ADDED: Add location section to response
                property_data["location"] = self.get_location_data(property_obj)
                
                return Response({
                    "success": True,
                    "message": "Property status updated successfully",
                    "data": property_data
                }, status=status.HTTP_200_OK)
                
            else:
                return Response({
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                    "code": "VALIDATION_ERROR"
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except properties.DoesNotExist:
            message = "Property not found or you don't have permission to update it."
            return Response({
                "success": False,
                "message": message,
                "code": "NOT_FOUND"
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error updating property status {property_id}: {str(e)}", exc_info=True)
            
            return Response({
                "success": False,
                "message": "An error occurred while updating property status.",
                "code": "INTERNAL_ERROR"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)