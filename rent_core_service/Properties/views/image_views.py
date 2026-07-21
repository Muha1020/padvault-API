import logging
import cloudinary.uploader
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from ..models import properties
from ..serializers import PropertyBaseSerializer
from .base import IsLandlordOrAdmin

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/jpg'}
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class PropertyImageUploadView(APIView):
    """
    POST /api/properties/<id>/images/upload/
    Upload a single image (main cover or gallery) for a property.

    Multipart fields:
        image   — the image file
        is_main — 'true' to set as main_image, anything else appends to image_urls
    """
    permission_classes = [IsLandlordOrAdmin]

    def post(self, request, property_id):
        # Ownership check — outside try so Http404 propagates cleanly
        qs = properties.objects.all()
        if request.user.role == 'admin':
            prop = get_object_or_404(qs, id=property_id)
        else:
            prop = get_object_or_404(qs, id=property_id, landlord=request.user)

        try:
            file = request.FILES.get('image')
            if not file:
                return Response({
                    "success": False,
                    "message": "No image file provided.",
                }, status=status.HTTP_400_BAD_REQUEST)

            if file.content_type not in ALLOWED_TYPES:
                return Response({
                    "success": False,
                    "message": "Unsupported file type. Use JPEG, PNG, or WebP.",
                }, status=status.HTTP_400_BAD_REQUEST)

            if file.size > MAX_SIZE_BYTES:
                return Response({
                    "success": False,
                    "message": "Image must be under 5 MB.",
                }, status=status.HTTP_400_BAD_REQUEST)

            is_main = request.data.get('is_main', 'false').lower() == 'true'

            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                file,
                folder=f"rent_mgt/properties/{property_id}",
                resource_type="image",
                transformation=[
                    {"quality": "auto", "fetch_format": "auto"},
                    {"width": 1200, "height": 900, "crop": "limit"},
                ],
            )
            url = result['secure_url']

            # Save URL to the property
            if is_main:
                prop.main_image = url
            else:
                urls = prop.image_urls or []
                urls.append(url)
                prop.image_urls = urls

            prop.save(update_fields=['main_image'] if is_main else ['image_urls'])

            return Response({
                "success": True,
                "message": "Image uploaded successfully.",
                "url": url,
                "data": PropertyBaseSerializer(prop, context={'request': request}).data,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error uploading image for property {property_id}: {e}", exc_info=True)
            return Response({
                "success": False,
                "message": "Failed to upload image.",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PropertyImageRemoveView(APIView):
    """
    DELETE /api/properties/<id>/images/remove/
    Remove an image URL from main_image or image_urls.

    JSON body:
        url     — the Cloudinary URL to remove
        is_main — true to clear main_image, false to remove from gallery
    """
    permission_classes = [IsLandlordOrAdmin]

    def delete(self, request, property_id):
        qs = properties.objects.all()
        if request.user.role == 'admin':
            prop = get_object_or_404(qs, id=property_id)
        else:
            prop = get_object_or_404(qs, id=property_id, landlord=request.user)

        try:
            url = request.data.get('url', '').strip()
            is_main = request.data.get('is_main', False)

            if not url:
                return Response({
                    "success": False,
                    "message": "No URL provided.",
                }, status=status.HTTP_400_BAD_REQUEST)

            if is_main:
                prop.main_image = None
                prop.save(update_fields=['main_image'])
            else:
                urls = prop.image_urls or []
                if url in urls:
                    urls.remove(url)
                    prop.image_urls = urls
                    prop.save(update_fields=['image_urls'])

            return Response({
                "success": True,
                "message": "Image removed successfully.",
                "data": PropertyBaseSerializer(prop, context={'request': request}).data,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error removing image for property {property_id}: {e}", exc_info=True)
            return Response({
                "success": False,
                "message": "Failed to remove image.",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
