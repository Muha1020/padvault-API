from rest_framework import serializers
from .models import MaintenanceRequest


class MaintenanceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceRequest
        fields = [
            'property', 'reported_by_name', 'reported_by_phone',
            'title', 'description', 'category', 'priority', 'images',
        ]

    def validate_images(self, value):
        if value is None:
            return value
        if not isinstance(value, list):
            raise serializers.ValidationError("images must be a list of URLs.")
        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 images allowed.")
        for url in value:
            if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
                raise serializers.ValidationError(
                    f"Invalid image URL: {url!r}. Each entry must be a string "
                    "starting with http:// or https://"
                )
        return value


class MaintenanceStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MaintenanceRequest.REQUEST_STATUS)
    landlord_notes = serializers.CharField(required=False, allow_blank=True)
    resolution_summary = serializers.CharField(required=False, allow_blank=True)


class MaintenanceSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source='property.title', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceRequest
        fields = '__all__'

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.firstname} {obj.created_by.lastname}"
        return ""
