from django.urls import path
from .views import (
    SubscribePushView, UnsubscribePushView, 
    NotificationListView, MarkNotificationReadView, 
    MarkAllNotificationsReadView
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('<int:pk>/read/', MarkNotificationReadView.as_view(), name='notification-read'),
    path('read-all/', MarkAllNotificationsReadView.as_view(), name='notification-read-all'),
    path('subscribe/', SubscribePushView.as_view(), name='push-subscribe'),
    path('unsubscribe/', UnsubscribePushView.as_view(), name='push-unsubscribe'),
]
