import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.db.models import Q, Count, F, Min, Max
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.cache import cache_page

_CATEGORY_META = [
    ('apartment',  'Apartment'),
    ('house',      'House'),
    ('condo',      'Condo'),
    ('studio',     'Studio'),
    ('commercial', 'Commercial'),
    ('bungalow',   'Bungalow'),
    ('duplex',     'Duplex'),
    ('other',      'Other'),
]

from ..models import properties  
from .base import BasePropertyView
from utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

class PublicPropertySerializerMixin:
    """Mixin to handle safe serialization of property data for public marketplace"""

    def serialize_public_property(self, prop, detail=False):
        """Standardized serialization for both list and detail views"""
        main_image, is_placeholder = self.get_property_image(prop)
        
        data = {
            "id": prop.id,
            "title": prop.title,
            "property_type": prop.property_type,
            "listing_type": prop.listing_type,
            "status": prop.status,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "main_image": main_image,
            "is_placeholder": is_placeholder,
            "location": self.get_location_data(prop),
            "created_at": prop.created_at.isoformat(),
        }

        # Pricing Logic
        if prop.listing_type == 'lease':
            data["price"] = float(prop.monthly_rent) if prop.monthly_rent else 0
            data["price_period"] = "month"
            data["yearly_rent"] = float(prop.yearly_rent) if prop.yearly_rent else 0
        elif prop.listing_type == 'short_term':
            data["price"] = float(prop.nightly_rate) if prop.nightly_rate else 0
            data["price_period"] = "night"
            data["min_nights"] = prop.min_nights
        else: # Hybrid
            data["monthly_rent"] = float(prop.monthly_rent) if prop.monthly_rent else 0
            data["nightly_rate"] = float(prop.nightly_rate) if prop.nightly_rate else 0
            data["price"] = data["monthly_rent"] # Default to rent for list view
            data["price_period"] = "month"

        if detail:
            data["description"] = prop.description
            data["image_gallery"] = prop.image_urls if prop.image_urls else [main_image]
            data["views_count"] = prop.views_count
            
            # Trust Metadata
            landlord = prop.landlord
            first = landlord.firstname or ""
            last_initial = (landlord.lastname[0] + ".") if landlord.lastname else ""
            data["landlord"] = {
                "name": f"{first} {last_initial}".strip() or "Landlord",
                "is_verified": landlord.email_verified or landlord.registration_step == 'complete',
                "member_since": landlord.created_at.year if landlord.created_at else 2024
            }
            
        return data

# properties list & search view
class PropertyListView(BasePropertyView, PublicPropertySerializerMixin):
    """
    GET /api/properties/ 
    Handles:
    - Pagination (?page=1&limit=12)
    - Search (?q=Lagos)
    - Category Filters (?type=apartment&bedrooms=3)
    - Price Filters (?min_price=100000&max_price=500000)
    """
    
    @method_decorator(rate_limit(60, 60, 'public_properties'))
    def get(self, request):
        try:
            page = int(request.GET.get('page', 1))
            limit = int(request.GET.get('limit', 12))
            offset = (page - 1) * limit
            
            # Start with published & available
            qs = properties.objects.filter(
                is_published=True, 
                status='available'
            ).select_related('address_id', 'landlord')
            
            # 1. Search Query (Title, Description, City, State)
            q = request.GET.get('q', '').strip()
            if q:
                qs = qs.filter(
                    Q(title__icontains=q) | 
                    Q(description__icontains=q) |
                    Q(address_id__city__icontains=q) |
                    Q(address_id__state_province__icontains=q)
                )

            # 2. Filters
            p_type = request.GET.get('type')
            l_type = request.GET.get('listing_type')
            min_p = request.GET.get('min_price')
            max_p = request.GET.get('max_price')
            beds = request.GET.get('bedrooms')
            baths = request.GET.get('bathrooms')
            
            if p_type: qs = qs.filter(property_type=p_type)
            if l_type: qs = qs.filter(listing_type=l_type)
            if beds:   qs = qs.filter(bedrooms=beds)
            if baths:  qs = qs.filter(bathrooms=baths)
            
            try:
                if min_p: qs = qs.filter(Q(monthly_rent__gte=min_p) | Q(nightly_rate__gte=min_p))
                if max_p: qs = qs.filter(Q(monthly_rent__lte=max_p) | Q(nightly_rate__lte=max_p))
            except (ValueError, TypeError):
                pass
            
            total_count = qs.count()
            qs = qs.order_by('-is_featured', '-created_at')[offset:offset + limit]
            
            # Prepare response
            results = [self.serialize_public_property(p) for p in qs]
            
            return JsonResponse({
                "success": True,
                "data": {
                    "results": results,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total_count,
                        "pages": (total_count + limit - 1) // limit
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Marketplace List Error: {e}", exc_info=True)
            return JsonResponse({"success": False, "message": "Error fetching properties"}, status=500)

# Property Search View (Consolidated wrapper)
class PropertySearchView(PropertyListView):
    """Wrapper for PropertyListView to maintain backward compatibility"""
    @method_decorator(rate_limit(60, 60, 'public_properties_search'))
    def get(self, request):
        return super().get(request)

# Property Filter View (Consolidated wrapper)
class PropertyFilterView(PropertyListView):
    """Wrapper for PropertyListView to maintain backward compatibility"""
    @method_decorator(rate_limit(60, 60, 'public_properties_filter'))
    def get(self, request):
        return super().get(request)

# property detail view
class PropertyDetailView(BasePropertyView, PublicPropertySerializerMixin):
    """GET /api/properties/<property_id>/view/ - Property details"""
    
    @method_decorator(rate_limit(100, 60, 'public_property_detail'))
    def get(self, request, property_id):
        try:
            # Handle both UUID and Numeric ID
            if isinstance(property_id, str) and not property_id.isdigit():
                 lookup = Q(id=property_id)
            else:
                 lookup = Q(id=int(property_id))
            
            prop = properties.objects.select_related('address_id', 'landlord').get(
                lookup, 
                is_published=True
            )
            
            # Increment view count
            properties.objects.filter(id=prop.id).update(views_count=F('views_count') + 1)
            prop.refresh_from_db()

            return JsonResponse({
                "success": True,
                "data": self.serialize_public_property(prop, detail=True)
            })
            
        except properties.DoesNotExist:
            return JsonResponse({"success": False, "message": "Property not found"}, status=404)
        except Exception as e:
            logger.error(f"Marketplace Detail Error: {e}", exc_info=True)
            return JsonResponse({"success": False, "message": "Error fetching property"}, status=500)

# Property Filters Meta Data View
class PropertyFiltersMetaDataView(View, PublicPropertySerializerMixin):
    """
    GET /api/properties/meta/
    Returns intelligence for marketplace filters
    """
    @method_decorator(rate_limit(30, 60, 'public_properties_meta'))
    def get(self, request):
        try:
            base_qs = properties.objects.filter(is_published=True, status='available')

            # 1. Price boundaries
            prices = base_qs.aggregate(
                min_monthly=Min('monthly_rent'),
                max_monthly=Max('monthly_rent'),
                min_nightly=Min('nightly_rate'),
                max_nightly=Max('nightly_rate'),
                min_yearly=Min('yearly_rent'),
                max_yearly=Max('yearly_rent')
            )

            # 2. Unique Locations
            locations = base_qs.filter(address_id__isnull=False).values(
                'address_id__city', 'address_id__state_province'
            ).distinct()
            
            formatted_locations = []
            seen_cities = set()
            for loc in locations:
                city = loc['address_id__city']
                state = loc['address_id__state_province']
                if city and city not in seen_cities:
                    formatted_locations.append({"city": city, "state": state})
                    seen_cities.add(city)

            # 3. Active Property Types
            types = base_qs.values_list('property_type', flat=True).distinct()
            active_types = [t for t in types if t]

            return JsonResponse({
                "success": True,
                "data": {
                    "price_range": {
                        "monthly": {"min": float(prices['min_monthly'] or 0), "max": float(prices['max_monthly'] or 0)},
                        "nightly": {"min": float(prices['min_nightly'] or 0), "max": float(prices['max_nightly'] or 0)},
                        "yearly": {"min": float(prices['min_yearly'] or 0), "max": float(prices['max_yearly'] or 0)}
                    },
                    "locations": formatted_locations,
                    "property_types": active_types,
                    "listing_types": ['lease', 'short_term', 'hybrid']
                }
            })
        except Exception as e:
            logger.error(f"Marketplace Meta Error: {e}", exc_info=True)
            return JsonResponse({"success": False, "message": "Error fetching marketplace metadata"}, status=500)

# Property Status Counts View
class PropertyStatusCountsView(View):
    """GET /api/properties/status-counts/ - Get counts by property status"""
    def get(self, request):
        try:
            status_counts = properties.objects.filter(is_published=True).values('status').annotate(
                count=Count('id')
            )
            status_data = {item['status']: item['count'] for item in status_counts}
            for status in ['available', 'occupied', 'under_maintenance', 'unavailable']:
                status_data.setdefault(status, 0)
            
            return JsonResponse({"success": True, "data": status_data})
        except Exception as e:
            return JsonResponse({"success": False, "message": "Error fetching status counts"}, status=500)

# property categories view
class PropertyCategoriesView(View):
    """GET /api/properties/categories/ - Property types"""
    def get(self, request):
        counts = dict(
            properties.objects.filter(is_published=True, status='available')
            .values('property_type')
            .annotate(n=Count('id'))
            .values_list('property_type', 'n')
        )
        categories = [
            {"id": slug, "name": label, "count": counts.get(slug, 0)}
            for slug, label in _CATEGORY_META
        ]
        return JsonResponse({"success": True, "data": categories})

# featured properties view
class FeaturedPropertiesView(BasePropertyView, PublicPropertySerializerMixin):
    """GET /api/properties/featured/ - Featured properties"""
    def get(self, request):
        try:
            featured_props = properties.objects.filter(
                is_published=True, 
                is_featured=True,
                status='available'
            ).select_related('address_id', 'landlord')[:6]
            
            results = [self.serialize_public_property(p) for p in featured_props]
            return JsonResponse({"success": True, "data": results})
        except Exception as e:
            return JsonResponse({"success": False, "message": "Error fetching featured properties"}, status=500)

# Property Availability View
class PropertyAvailabilityView(View, PublicPropertySerializerMixin):
    """GET /api/properties/<property_id>/availability/ - Check property availability"""
    @method_decorator(rate_limit(30, 60, 'public_property_avail'))
    def get(self, request, property_id):
        try:
            prop = properties.objects.select_related('address_id').get(id=property_id)
            
            availability_data = {
                "property_id": prop.id,
                "title": prop.title,
                "is_published": prop.is_published,
                "status": prop.status,
                "is_available": prop.is_published and prop.status == 'available',
                "listing_type": prop.listing_type,
                "location": self.get_location_data(prop)
            }
            return JsonResponse({"success": True, "data": availability_data})
        except properties.DoesNotExist:
            return JsonResponse({"success": False, "message": "Property not found"}, status=404)
        except Exception as e:
            return JsonResponse({"success": False, "message": "Error checking availability"}, status=500)
