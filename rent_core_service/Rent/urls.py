from django.urls import path
from . import views

urlpatterns = [
    # Initiations
    path('initiations/', views.RentInitiationListCreateView.as_view(), name='rent-initiation-list-create'),
    path('initiations/public/', views.PublicRentInitiationCreateView.as_view(), name='rent-initiation-public-create'),
    path('initiations/<int:initiation_id>/approve/', views.RentInitiationApproveView.as_view(), name='rent-initiation-approve'),
    path('initiations/<int:initiation_id>/reject/', views.RentInitiationRejectView.as_view(), name='rent-initiation-reject'),

    # Active leases
    path('', views.RentListView.as_view(), name='rent-list'),
    path('<int:rent_id>/', views.RentDetailView.as_view(), name='rent-detail'),
    path('<int:rent_id>/cancel/', views.RentCancelView.as_view(), name='rent-cancel'),

    # Payments
    path('<int:rent_id>/payments/', views.RentPaymentCreateView.as_view(), name='rent-payments'),
    path('<int:rent_id>/schedule/', views.RentScheduleView.as_view(), name='rent-schedule'),
    path('schedule/<int:schedule_id>/send-payment-email/', views.SendRentPaymentEmailView.as_view(), name='rent-schedule-send-email'),

    # Public Lease Endpoints
    path('lease/<uuid:public_id>/', views.PublicLeaseDetailView.as_view(), name='public-lease-detail'),
    path('lease/<uuid:public_id>/sign/', views.PublicLeaseSignView.as_view(), name='public-lease-sign'),
    # Document delivery proxy
    path('documents/<uuid:public_id>/view/', views.DownloadLeaseView.as_view(), name='document-view'),
]
