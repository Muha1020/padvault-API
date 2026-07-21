import logging
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers

from ..models import properties, PropertyAsset
from .base import IsLandlordOrAdmin

logger = logging.getLogger(__name__)


class PropertyAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyAsset
        fields = '__all__'
        read_only_fields = ['property', 'created_at', 'updated_at']


class PropertyAssetCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyAsset
        fields = ['name', 'category', 'condition', 'serial_number', 'estimated_value', 'is_active']


class PropertyAssetListCreateView(APIView):
    """
    GET  /api/properties/<id>/assets/  — List all assets for a property
    POST /api/properties/<id>/assets/  — Add a new asset to a property
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_property(self, request, property_id):
        if request.user.role == 'admin':
            return get_object_or_404(properties, id=property_id)
        return get_object_or_404(properties, id=property_id, landlord=request.user)

    def get(self, request, property_id):
        prop = self._get_property(request, property_id)
        assets = PropertyAsset.objects.filter(property=prop, is_active=True)
        return Response({
            "success": True,
            "message": "Assets retrieved successfully",
            "data": PropertyAssetSerializer(assets, many=True).data,
        })

    def post(self, request, property_id):
        prop = self._get_property(request, property_id)
        try:
            serializer = PropertyAssetCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"success": False, "message": "Validation failed",
                                 "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            asset = serializer.save(property=prop)
            return Response({
                "success": True,
                "message": "Asset added successfully",
                "data": PropertyAssetSerializer(asset).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error adding asset to property {property_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to add asset"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PropertyAssetDetailView(APIView):
    """
    PUT    /api/properties/<id>/assets/<asset_id>/  — Update an asset
    DELETE /api/properties/<id>/assets/<asset_id>/  — Deactivate an asset
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_asset(self, request, property_id, asset_id):
        if request.user.role == 'admin':
            prop = get_object_or_404(properties, id=property_id)
        else:
            prop = get_object_or_404(properties, id=property_id, landlord=request.user)
        return get_object_or_404(PropertyAsset, id=asset_id, property=prop)

    def put(self, request, property_id, asset_id):
        asset = self._get_asset(request, property_id, asset_id)
        try:
            serializer = PropertyAssetCreateSerializer(asset, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response({"success": False, "errors": serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)
            asset = serializer.save()
            return Response({
                "success": True,
                "message": "Asset updated successfully",
                "data": PropertyAssetSerializer(asset).data,
            })
        except Exception as e:
            logger.error(f"Error updating asset {asset_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update asset"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, property_id, asset_id):
        asset = self._get_asset(request, property_id, asset_id)
        try:
            asset.is_active = False
            asset.save(update_fields=['is_active'])
            return Response({
                "success": True,
                "message": "Asset deactivated successfully",
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error deactivating asset {asset_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to deactivate asset"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
