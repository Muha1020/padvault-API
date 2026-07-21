from rest_framework import serializers
from django.utils import timezone
from .models import Rent, RentInitiation, RentPayment, PaymentSchedule


class PaymentScheduleSerializer(serializers.ModelSerializer):
    invoice_public_id = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PaymentSchedule
        fields = '__all__'
        read_only_fields = ['rent', 'installment_number', 'due_date', 'amount_due']

    def get_invoice_public_id(self, obj):
        if obj.invoice:
            return str(obj.invoice.public_id)
        return None


class RentInitiationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentInitiation
        fields = [
            'rental_property', 'tenant_name', 'tenant_email', 'tenant_phone',
            'proposed_start_date', 'proposed_end_date',
            'proposed_rent_type', 'proposed_amount', 'proposed_security_deposit', 'message',
        ]
        extra_kwargs = {
            'tenant_email': {'required': False},
            'tenant_phone': {'required': False},
            'proposed_security_deposit': {'required': False},
            'message': {'required': False},
        }

    def validate(self, data):
        start = data.get('proposed_start_date')
        end = data.get('proposed_end_date')
        if start and end:
            if end <= start:
                raise serializers.ValidationError("End date must be after start date.")
            
            duration_months = (end.year - start.year) * 12 + (end.month - start.month)
            if duration_months > 60:
                raise serializers.ValidationError("Lease duration cannot exceed 5 years (60 months).")
                
        if data.get('proposed_amount', 0) <= 0:
            raise serializers.ValidationError("Proposed amount must be greater than zero.")
        if not data.get('tenant_name', '').strip():
            raise serializers.ValidationError("Tenant name is required.")
        return data

    def create(self, validated_data):
        validated_data['expires_at'] = timezone.now() + timezone.timedelta(days=7)
        return super().create(validated_data)


class PublicRentInitiationSerializer(RentInitiationCreateSerializer):
    """Serializer for public marketplace applications"""
    class Meta(RentInitiationCreateSerializer.Meta):
        extra_kwargs = {
            'tenant_email': {'required': True},
            'tenant_name': {'required': True},
            'tenant_phone': {'required': True},
            'proposed_start_date': {'required': True},
            'proposed_amount': {'required': True},
        }

    def validate_tenant_email(self, value):
        if not value:
            raise serializers.ValidationError("Email is required.")
        return value.lower().strip()


class RentInitiationSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source='rental_property.title', read_only=True)
    property_main_image = serializers.SerializerMethodField(read_only=True)
    display_tenant_name = serializers.SerializerMethodField(read_only=True)
    landlord_name = serializers.SerializerMethodField(read_only=True)
    total_proposed_amount = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)

    class Meta:
        model = RentInitiation
        fields = '__all__'

    def get_display_tenant_name(self, obj):
        if obj.tenant_name:
            return obj.tenant_name
        if obj.tenant:
            return f"{obj.tenant.firstname} {obj.tenant.lastname}"
        return "Unknown"

    def get_landlord_name(self, obj):
        return f"{obj.landlord.firstname} {obj.landlord.lastname}"

    def get_property_main_image(self, obj):
        return obj.rental_property.main_image or None


class RentSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source='rental_property.title', read_only=True)
    property_main_image = serializers.SerializerMethodField(read_only=True)
    display_tenant_name = serializers.SerializerMethodField(read_only=True)
    progress_percentage = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    schedule = PaymentScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Rent
        exclude = ('tenant_signature', 'landlord_signature')

    def get_display_tenant_name(self, obj):
        if obj.tenant_name:
            return obj.tenant_name
        if obj.tenant:
            return f"{obj.tenant.firstname} {obj.tenant.lastname}"
        return "Unknown"

    def get_property_main_image(self, obj):
        return obj.rental_property.main_image or None


class RentPaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentPayment
        fields = [
            'rent', 'amount', 'payment_method', 'payment_reference',
            'due_date', 'period_start', 'period_end',
        ]
        extra_kwargs = {
            'due_date': {'required': False},
            'period_start': {'required': False},
            'period_end': {'required': False},
        }

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")
        return value


class RentPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentPayment
        fields = '__all__'


class RentInitiationRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


class RentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rent
        fields = ['tenant_name', 'tenant_email', 'tenant_phone', 'amount', 'end_date', 'rent_type']
        
    def validate_tenant_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Tenant name is required.")
        return value
