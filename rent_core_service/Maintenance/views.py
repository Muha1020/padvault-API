import logging
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .models import MaintenanceRequest
from .serializers import MaintenanceCreateSerializer, MaintenanceSerializer, MaintenanceStatusSerializer
from Properties.models import properties
from Rent.models import Rent
from Properties.views.base import IsLandlordOrAdmin
from utils.rate_limit import rate_limit
from utils.push_notifications import send_push_notification

logger = logging.getLogger(__name__)


class MaintenancePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@method_decorator(rate_limit(limit=50, window_seconds=3600, endpoint_key='maintenance_create'), name='post')
class MaintenanceListCreateView(APIView):
    """
    GET  /api/maintenance/  — List all maintenance requests for landlord's properties
    POST /api/maintenance/  — Log a new maintenance request
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            qs = MaintenanceRequest.objects.filter(
                property__landlord=request.user
            ).select_related('property')

            status_filter = request.GET.get('status')
            priority_filter = request.GET.get('priority')
            category_filter = request.GET.get('category')
            property_id = request.GET.get('property')
            search = request.GET.get('search')

            if status_filter:
                qs = qs.filter(status=status_filter)
            if priority_filter:
                qs = qs.filter(priority=priority_filter)
            if category_filter:
                qs = qs.filter(category=category_filter)
            if property_id:
                qs = qs.filter(property_id=property_id)
            if search:
                qs = qs.filter(
                    Q(title__icontains=search) |
                    Q(reported_by_name__icontains=search) |
                    Q(description__icontains=search)
                )

            paginator = MaintenancePagination()
            page = paginator.paginate_queryset(qs, request)
            serializer = MaintenanceSerializer(page, many=True)
            return Response({
                "success": True,
                "message": "Maintenance requests retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": serializer.data,
            })

        except Exception as e:
            logger.error(f"Error listing maintenance requests: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve maintenance requests"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            serializer = MaintenanceCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                }, status=status.HTTP_400_BAD_REQUEST)

            prop = serializer.validated_data['property']
            if prop.landlord != request.user and request.user.role != 'admin':
                return Response({
                    "success": False,
                    "message": "You do not own this property.",
                }, status=status.HTTP_403_FORBIDDEN)

            request_obj = serializer.save(created_by=request.user)
            return Response({
                "success": True,
                "message": "Maintenance request logged successfully",
                "data": MaintenanceSerializer(request_obj).data,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating maintenance request: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to log maintenance request"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MaintenanceDetailView(APIView):
    """
    GET   /api/maintenance/<id>/  — Request detail
    PATCH /api/maintenance/<id>/  — Update details
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_request(self, request, req_id):
        if request.user.role == 'admin':
            return get_object_or_404(MaintenanceRequest.objects.select_related('property'), id=req_id)
        return get_object_or_404(
            MaintenanceRequest.objects.select_related('property'),
            id=req_id,
            property__landlord=request.user
        )

    def get(self, request, req_id):
        obj = self._get_request(request, req_id)
        return Response({
            "success": True,
            "message": "Maintenance request retrieved successfully",
            "data": MaintenanceSerializer(obj).data,
        })

    def patch(self, request, req_id):
        try:
            obj = self._get_request(request, req_id)
            allowed = {'reported_by_name', 'reported_by_phone', 'title',
                       'description', 'category', 'priority', 'images', 'landlord_notes'}
            data = {k: v for k, v in request.data.items() if k in allowed}
            serializer = MaintenanceCreateSerializer(obj, data=data, partial=True)
            if not serializer.is_valid():
                return Response({"success": False, "errors": serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)
            obj = serializer.save()
            return Response({
                "success": True,
                "message": "Maintenance request updated successfully",
                "data": MaintenanceSerializer(obj).data,
            })
        except Exception as e:
            logger.error(f"Error updating maintenance request {req_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update maintenance request"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, req_id):
        try:
            obj = self._get_request(request, req_id)
            obj.delete()
            return Response({
                "success": True,
                "message": "Maintenance request deleted successfully"
            })
        except Exception as e:
            logger.error(f"Error deleting maintenance request {req_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to delete maintenance request"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MaintenanceStatusUpdateView(APIView):
    """
    PATCH /api/maintenance/<id>/status/  — Move request through the workflow
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, req_id):
        try:
            if request.user.role == 'admin':
                obj = get_object_or_404(MaintenanceRequest, id=req_id)
            else:
                obj = get_object_or_404(MaintenanceRequest, id=req_id, property__landlord=request.user)

            serializer = MaintenanceStatusSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"success": False, "errors": serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)

            obj.status = serializer.validated_data['status']
            if 'landlord_notes' in serializer.validated_data:
                obj.landlord_notes = serializer.validated_data['landlord_notes']
            if 'resolution_summary' in serializer.validated_data:
                obj.resolution_summary = serializer.validated_data['resolution_summary']
            if obj.status == 'resolved' and not obj.resolved_at:
                obj.resolved_at = timezone.now()
            obj.save()

            # Push Notification to Tenant (if found via active lease)
            try:
                # Find the most recent active lease for this property
                rent = Rent.objects.filter(rental_property=obj.property).order_by('-created_at').first()
                if rent and rent.tenant:
                    send_push_notification(
                        rent.tenant,
                        "Maintenance Update",
                        f"Status for '{obj.title}' updated to {obj.status}.",
                        "/dashboard/maintenance",
                        notification_type='maintenance'
                    )
            except Exception as e:
                logger.warning(f"Failed to send maintenance push notification: {e}")

            return Response({
                "success": True,
                "message": f"Status updated to '{obj.status}'",
                "data": MaintenanceSerializer(obj).data,
            })

        except Exception as e:
            logger.error(f"Error updating maintenance status {req_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update status"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MaintenanceStatsView(APIView):
    """
    GET /api/maintenance/stats/  — Get basic stats for landlord's maintenance requests
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            qs = MaintenanceRequest.objects.filter(property__landlord=request.user)
            
            total = qs.count()
            pending = qs.filter(status='pending').count()
            in_progress = qs.filter(status='in_progress').count()
            resolved = qs.filter(status='resolved').count()
            high_priority = qs.filter(priority='high').count()
            
            return Response({
                "success": True,
                "data": {
                    "total": total,
                    "pending": pending,
                    "in_progress": in_progress,
                    "resolved": resolved,
                    "high_priority": high_priority
                }
            })
        except Exception as e:
            logger.error(f"Error getting maintenance stats: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to get stats"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
