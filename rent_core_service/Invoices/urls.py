from django.urls import path
from . import views

urlpatterns = [
    path('', views.InvoiceListCreateView.as_view(), name='invoice-list-create'),
    # Public Endpoints
    path('public/<uuid:public_id>/', views.PublicInvoiceDetailView.as_view(), name='public-invoice-detail'),
    path('public/<uuid:public_id>/init-payment/', views.PublicInvoiceInitPaymentView.as_view(), name='invoice-public-init-payment'),
    path('public/<uuid:public_id>/verify-payment/', views.PublicInvoiceVerifyPaymentView.as_view(), name='invoice-public-verify-payment'),
    path('<int:invoice_id>/', views.InvoiceDetailView.as_view(), name='invoice-detail'),
    path('<int:invoice_id>/mark-paid/', views.InvoiceMarkPaidView.as_view(), name='invoice-mark-paid'),
]
