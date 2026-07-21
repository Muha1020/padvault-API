from django.urls import path
from . import views

urlpatterns = [
    path('', views.TransactionListView.as_view(), name='transaction-list'),
    path('monnify-webhook/', views.MonnifyWebhookView.as_view(), name='monnify-webhook'),
]
