from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import PushSubscriptionSerializer, NotificationSerializer
from .models import PushSubscription, Notification
from utils.permissions import IsAuthenticated

class SubscribePushView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Successfully subscribed to push notifications"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UnsubscribePushView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get('endpoint')
        if not endpoint:
            return Response({"error": "Endpoint is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            subscription = request.user.push_subscriptions.get(endpoint=endpoint)
            subscription.delete()
            return Response({"message": "Successfully unsubscribed"}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "Subscription not found"}, status=status.HTTP_404_NOT_FOUND)

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
        unread_count = notifications.filter(is_read=False).count()
        
        # Pagination
        from rest_framework.pagination import PageNumberPagination
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(notifications, request)
        
        serializer = NotificationSerializer(page, many=True)
        return Response({
            "success": True,
            "unread_count": unread_count,
            "data": serializer.data
        })

class MarkNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.is_read = True
            notification.save()
            return Response({"success": True})
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found"}, status=status.HTTP_404_NOT_FOUND)

class MarkAllNotificationsReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"success": True})
