from django.urls import path
from .views import (
    AdminLoginAPIView,
    AdminStatsView,
    AdminSystemLogsView,
    AdminSupportMessagesView,
    AdminSupportMessageReplyView,
    AdminCreateAdminView,
    AdminDeleteAdminView,
    AdminUserListView,
    AdminUserStatusView,
    AdminUserImpersonateView,
    AdminStopImpersonationView,
    AdminUserProfileView,
    AdminUserNotifyView,
    AdminUserBulkActionView,
    AdminKYCListView,
    AdminKYCOverrideView,
    AdminPropertiesListView,
    AdminPropertyModerationView,
    AdminPropertyBulkActionView,
    AdminLeasesListView,
    AdminMaintenanceListView,
    AdminTransactionsListView,
    AdminUserSubscriptionView,
    AdminInvoiceListView,
    AdminInvoiceOverrideView,
    AdminExportView,
    AdminBroadcastView,
    AdminConfigView,
)

urlpatterns = [
    # Auth
    path('login/', AdminLoginAPIView.as_view(), name='admin-login'),

    # Global & Reporting
    path('stats/', AdminStatsView.as_view(), name='admin_stats'),
    path('system-logs/', AdminSystemLogsView.as_view(), name='admin_system_logs'),
    path('support-messages/', AdminSupportMessagesView.as_view(), name='admin_support_messages'),
    path('support-messages/<int:message_id>/', AdminSupportMessagesView.as_view(), name='admin_support_message_detail'),
    path('support-messages/<int:message_id>/reply/', AdminSupportMessageReplyView.as_view(), name='admin_support_message_reply'),

    # Admin & User Management
    path('create-admin/', AdminCreateAdminView.as_view(), name='admin_create_admin'),
    path('delete-admin/<int:user_id>/', AdminDeleteAdminView.as_view(), name='admin_delete_admin'),
    path('users/', AdminUserListView.as_view(), name='admin_users_list'),
    path('users/<int:user_id>/status/', AdminUserStatusView.as_view(), name='admin_user_status'),
    path('users/<int:user_id>/subscription/', AdminUserSubscriptionView.as_view(), name='admin_user_subscription'),
    path('users/<int:user_id>/impersonate/', AdminUserImpersonateView.as_view(), name='admin_user_impersonate'),
    path('users/<int:user_id>/profile/', AdminUserProfileView.as_view(), name='admin_user_profile'),
    path('users/<int:user_id>/notify/', AdminUserNotifyView.as_view(), name='admin_user_notify'),
    path('users/bulk-action/', AdminUserBulkActionView.as_view(), name='admin_users_bulk_action'),
    path('stop-impersonating/', AdminStopImpersonationView.as_view(), name='admin_stop_impersonating'),

    # KYC & Verification
    path('kyc/', AdminKYCListView.as_view(), name='admin_kyc_list'),
    path('kyc/<int:user_id>/override/', AdminKYCOverrideView.as_view(), name='admin_kyc_override'),

    # Content & Operations
    path('properties/', AdminPropertiesListView.as_view(), name='admin_properties_list'),
    path('properties/<int:property_id>/moderation/', AdminPropertyModerationView.as_view(), name='admin_property_moderation'),
    path('properties/bulk-action/', AdminPropertyBulkActionView.as_view(), name='admin_properties_bulk_action'),
    path('leases/', AdminLeasesListView.as_view(), name='admin_leases_list'),
    path('maintenance/', AdminMaintenanceListView.as_view(), name='admin_maintenance_list'),

    # Financial
    path('transactions/', AdminTransactionsListView.as_view(), name='admin_transactions_list'),
    path('invoices/', AdminInvoiceListView.as_view(), name='admin_invoices_list'),
    path('invoices/<int:invoice_id>/override/', AdminInvoiceOverrideView.as_view(), name='admin_invoice_override'),
    path('export/', AdminExportView.as_view(), name='admin_export'),

    # Super Admin — Broadcast & Config
    path('broadcast/', AdminBroadcastView.as_view(), name='admin_broadcast'),
    path('config/', AdminConfigView.as_view(), name='admin_config'),
]