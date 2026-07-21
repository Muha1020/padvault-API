from django.urls import path
from . import views

urlpatterns = [
    path('', views.BookingListCreateView.as_view(), name='booking-list-create'),
    path('<int:booking_id>/', views.BookingDetailView.as_view(), name='booking-detail'),
    path('<int:booking_id>/status/', views.BookingStatusUpdateView.as_view(), name='booking-status'),
    path('<int:booking_id>/send-payment-email/', views.SendBookingPaymentEmailView.as_view(), name='booking-send-email'),
    path('property/<int:property_id>/', views.PropertyBookingsView.as_view(), name='property-bookings'),
    
    # New Public & Approval Flow
    path('public/request/', views.PublicBookingRequestView.as_view(), name='public-booking-request'),
    path('<int:booking_id>/approve/', views.BookingApproveView.as_view(), name='booking-approve'),
    path('<int:booking_id>/reject/', views.BookingRejectView.as_view(), name='booking-reject'),
]
