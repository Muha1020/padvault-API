# properties/urls.py
from django.urls import path
from .views import public_views, landlord_views, tenant_views, asset_views, image_views


urlpatterns = [
# Public endpoints
    path('', public_views.PropertyListView.as_view(), name='property-list'),#GET /api/properties/
    path('meta/', public_views.PropertyFiltersMetaDataView.as_view(), name='property-filters-meta'),#GET /api/properties/meta/
    path('search/', public_views.PropertySearchView.as_view(), name='property-search'),#GET /api/properties/search/?q=<query>
    path('filter/', public_views.PropertyFilterView.as_view(), name='property-filter'),#GET /api/properties/filter/?<filter_params>
    path('categories/', public_views.PropertyCategoriesView.as_view(), name='property-categories'),#GET /api/properties/categories/
    path('featured/', public_views.FeaturedPropertiesView.as_view(), name='featured-properties'),#GET /api/properties/featured/
    path('<uuid:property_id>/view/', public_views.PropertyDetailView.as_view(), name='property-detail'),#GET /api/properties/<property_uuid>/view/
    path('<int:property_id>/view/', public_views.PropertyDetailView.as_view(), name='property-detail'),#GET /api/properties/<property_id>/view/
    path('properties/status-counts/', public_views.PropertyStatusCountsView.as_view(), name='property-status-counts'), #GET /api/properties/properties/status-counts/
    path('properties/<int:property_id>/availability/', public_views.PropertyAvailabilityView.as_view(), name='property-availability'), #GET /api/properties/properties/<property_id>/availability/

# Landlord endpoints
    path('landlord/create/', landlord_views.LandlordPropertyCreateView.as_view(), name='landlord-property-create'), #POST /api/properties/landlord/create/
    path('landlord/properties/', landlord_views.LandlordPropertyListView.as_view(), name='landlord-properties-list'), #GET /api/properties/landlord/properties/
    #path('debug/user/', DebugUserView.as_view(), name='debug-user'),
    path('landlord/<uuid:property_id>/', landlord_views.LandlordPropertyDetailView.as_view(), name='landlord-property-detail'), #GET /api/properties/landlord/<property_uuid>/
    path('landlord/<int:property_id>/', landlord_views.LandlordPropertyDetailView.as_view(), name='landlord-property-detail'),#GET /api/properties/landlord/<property_id>/
    path('landlord/<uuid:property_id>/status/', landlord_views.PropertyStatusUpdateView.as_view(), name='property-status-update'), #PATCH /api/properties/landlord/<property_uuid>/status/
    path('landlord/<int:property_id>/status/', landlord_views.PropertyStatusUpdateView.as_view(), name='property-status-update'),#PATCH /api/properties/landlord/<property_id>/status/

# Asset endpoints
    path('<int:property_id>/assets/', asset_views.PropertyAssetListCreateView.as_view(), name='property-assets'),
    path('<int:property_id>/assets/<int:asset_id>/', asset_views.PropertyAssetDetailView.as_view(), name='property-asset-detail'),

# Image endpoints
    path('<int:property_id>/images/upload/', image_views.PropertyImageUploadView.as_view(), name='property-image-upload'),
    path('<int:property_id>/images/remove/', image_views.PropertyImageRemoveView.as_view(), name='property-image-remove'),

# Tenant endpoints
  # Tenant endpoints
    path('save/<int:property_id>/', tenant_views.SavePropertyView.as_view(), name='save-property'),
    path('unsave/<int:property_id>/', tenant_views.UnsavePropertyView.as_view(), name='unsave-property'),
    path('saved/', tenant_views.SavedPropertiesListView.as_view(), name='saved-properties'),
    path('<int:property_id>/saved-status/', tenant_views.CheckSavedStatusView.as_view(), name='check-saved-status'),
]