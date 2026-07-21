# properties/serializers.py
from rest_framework import serializers
from .models import properties, saved_properties
from Users.models import User
from Address.models import Address

# === ADDRESS SERIALIZERS ===
class AddressCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating addresses"""
    class Meta:
        model = Address
        fields = ['street', 'city', 'state_province', 'country', 'postal_code', 'landmark']
        extra_kwargs = {
            'street': {'required': False},
            'city': {'required': False},
            'state_province': {'required': False},
            'country': {'required': False},
            'postal_code': {'required': False},
            'landmark': {'required': False}
        }
    
    def create(self, validated_data):
        return Address.objects.create(**validated_data)

# === PROPERTY STATUS SERIALIZER ===
class PropertyStatusSerializer(serializers.Serializer):
    """Serializer for updating property status fields"""
    is_published = serializers.BooleanField(required=False)
    is_featured = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(
        choices=[
            ('available', 'Available'),
            ('occupied', 'Occupied'),
            ('under_maintenance', 'Under Maintenance'),
            ('unavailable', 'Unavailable')
        ],
        required=False
    )
    
    def validate(self, data):
        """Validate at least one field is provided"""
        if not data:
            raise serializers.ValidationError("At least one status field must be provided")
        return data

# === PROPERTY SERIALIZERS ===
class PropertyBaseSerializer(serializers.ModelSerializer):
    """Base serializer with common fields and methods"""
    landlord_name = serializers.CharField(source='landlord.get_full_name', read_only=True)
    landlord_email = serializers.CharField(source='landlord.email', read_only=True)
    address_details = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = properties
        fields = [
            'id', 'title', 'description', 'property_type', 'status', 'listing_type',
            'yearly_rent', 'monthly_rent', 'nightly_rate', 'min_nights', 'max_nights',
            'bedrooms', 'bathrooms', 'is_published', 'is_featured', 'main_image', 'image_urls',
            'created_at', 'updated_at', 'landlord', 'landlord_name', 
            'landlord_email', 'address_id', 'address_details'
        ]
        extra_kwargs = {
            'landlord': {'write_only': True},
            'address_id': {'write_only': True},
        }
    
    def get_address_details(self, obj):
        """Get formatted address details if address exists"""
        if obj.address_id:
            address = obj.address_id
            return {
                'id': address.id,
                'street': address.street,
                'city': address.city,
                'state_province': address.state_province,
                'country': address.country,
                'postal_code': address.postal_code,
                'landmark': address.landmark
            }
        return None
    
    def to_representation(self, instance):
        """Customize the response format"""
        representation = super().to_representation(instance)
        
        # Convert Decimal fields to strings to avoid serialization issues
        for field in ['yearly_rent', 'monthly_rent', 'nightly_rate']:
            val = getattr(instance, field)
            representation[field] = str(val) if val is not None else "0.000"
        
        # Format timestamps
        representation['created_at'] = instance.created_at.isoformat() if instance.created_at else None
        representation['updated_at'] = instance.updated_at.isoformat() if instance.updated_at else None
        
        return representation

class PropertyCreateSerializer(PropertyBaseSerializer):
    """Serializer for creating properties with nested address"""
    address = AddressCreateSerializer(required=False, write_only=True)
    
    class Meta(PropertyBaseSerializer.Meta):
        fields = [f for f in PropertyBaseSerializer.Meta.fields if f != 'landlord'] + ['address']
        extra_kwargs = {
            'main_image': {'required': False},
            'image_urls': {'required': False}
        }
    
    def validate(self, data):
        """Custom validation logic"""
        # Validate property type
        valid_property_types = ['apartment', 'house', 'condo', 'studio', 'commercial', 'bungalow', 'duplex', 'other']
        if 'property_type' in data and data['property_type'] not in valid_property_types:
            raise serializers.ValidationError({'property_type': f"Must be one of: {', '.join(valid_property_types)}"})
        
        # Validate status
        valid_statuses = ['available', 'occupied', 'under_maintenance', 'unavailable']
        if 'status' in data and data['status'] not in valid_statuses:
            raise serializers.ValidationError({'status': f"Must be one of: {', '.join(valid_statuses)}"})
        
        return data
    
    def create(self, validated_data):
        """Create property with nested address handling"""
        address_data = validated_data.pop('address', None)
        address_instance = None
        if address_data:
            address_instance = Address.objects.create(**address_data)
        
        property_instance = properties.objects.create(
            address_id=address_instance,
            **validated_data
        )
        return property_instance

class PropertyUpdateSerializer(PropertyBaseSerializer):
    """Serializer for updating properties (partial updates supported)"""
    address = AddressCreateSerializer(required=False, write_only=True)
    
    class Meta(PropertyBaseSerializer.Meta):
        fields = PropertyBaseSerializer.Meta.fields + ['address']
        extra_kwargs = {
            **PropertyBaseSerializer.Meta.extra_kwargs,
            'landlord': {'read_only': True},
            'title': {'required': False},
            'description': {'required': False},
            'property_type': {'required': False},
            'status': {'required': False},
            'yearly_rent': {'required': False},
            'monthly_rent': {'required': False},
            'nightly_rate': {'required': False},
            'listing_type': {'required': False},
            'min_nights': {'required': False},
            'max_nights': {'required': False},
            'bedrooms': {'required': False},
            'bathrooms': {'required': False},
            'is_published': {'required': False},
            'is_featured': {'required': False},
        }
    
    def update(self, instance, validated_data):
        """Update property with nested address handling"""
        address_data = validated_data.pop('address', None)
        
        # Explicitly handle nested address update - this ensures persistence to DB
        if address_data:
            if instance.address_id:
                for attr, value in address_data.items():
                    setattr(instance.address_id, attr, value)
                instance.address_id.save()
            else:
                instance.address_id = Address.objects.create(**address_data)
        
        # Update property fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance

class PropertyListSerializer(PropertyBaseSerializer):
    """Serializer for listing properties"""
    class Meta(PropertyBaseSerializer.Meta):
        fields = [
            'id', 'title', 'property_type', 'status',
            'listing_type', 'yearly_rent', 'monthly_rent',
            'nightly_rate', 'min_nights', 'max_nights',
            'bedrooms', 'bathrooms', 'main_image',
            'is_published', 'is_featured', 'created_at', 'landlord_name', 'address_details'
        ]

# === SAVED PROPERTIES SERIALIZERS ===
class SavedPropertySerializer(serializers.ModelSerializer):
    property_details = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = saved_properties
        fields = ['id', 'user_id', 'property_id', 'property_details', 'created_at']
    def get_property_details(self, obj):
        return PropertyListSerializer(obj.property_id).data

class SavePropertySerializer(serializers.Serializer):
    property_id = serializers.IntegerField()
    def validate_property_id(self, value):
        if not properties.objects.filter(id=value).exists():
            raise serializers.ValidationError("Property does not exist")
        return value

class LandlordAnalyticsSerializer(serializers.Serializer):
    total_properties = serializers.IntegerField()
    published_properties = serializers.IntegerField()
    draft_properties = serializers.IntegerField()
    featured_properties = serializers.IntegerField()
    total_rental_income = serializers.DecimalField(max_digits=16, decimal_places=3)
    average_monthly_rent = serializers.DecimalField(max_digits=12, decimal_places=3)
    properties_by_type = serializers.DictField()
    recent_activity = serializers.ListField()
