from rest_framework import serializers
from .models import Booking


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            'property', 'guest_name', 'guest_phone', 'guest_email', 'guest_count',
            'check_in_date', 'check_out_date', 'caution_fee',
            'currency', 'source', 'special_requests', 'landlord_notes',
        ]
        # nightly_rate is intentionally excluded — it is pulled from the
        # property record in the view to prevent tampering.

    def validate_caution_fee(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Caution fee cannot be negative.")
        return value

    def validate(self, data):
        check_in = data.get('check_in_date')
        check_out = data.get('check_out_date')

        if check_in and check_out:
            if check_out <= check_in:
                raise serializers.ValidationError("Check-out date must be after check-in date.")
            if (check_out - check_in).days < 1:
                raise serializers.ValidationError("Minimum booking is 1 night.")

        return data


class BookingStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Booking.BOOKING_STATUS)
    landlord_notes = serializers.CharField(required=False, allow_blank=True)


class BookingSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source='property.title', read_only=True)
    property_main_image = serializers.SerializerMethodField()
    property_address = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    invoice_public_id = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = '__all__'

    def get_property_main_image(self, obj):
        return obj.property.main_image or None

    def get_property_address(self, obj):
        addr = obj.property.address_id
        if addr:
            return f"{addr.street}, {addr.city}"
        return ""

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.firstname} {obj.created_by.lastname}"
        return ""

    def get_invoice_public_id(self, obj):
        invoice = obj.invoices.first()
        if invoice:
            return str(invoice.public_id)
        return None
