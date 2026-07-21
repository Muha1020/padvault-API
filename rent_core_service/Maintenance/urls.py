from django.urls import path
from . import views

urlpatterns = [
    path('', views.MaintenanceListCreateView.as_view(), name='maintenance-list-create'),
    path('stats/', views.MaintenanceStatsView.as_view(), name='maintenance-stats'),
    path('<int:req_id>/', views.MaintenanceDetailView.as_view(), name='maintenance-detail'),
    path('<int:req_id>/status/', views.MaintenanceStatusUpdateView.as_view(), name='maintenance-status'),
]
