from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from .models import Invoice

MAX_LINE_ITEMS = 50
MAX_DESCRIPTION_LENGTH = 300


class InvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            'issued_to_name', 'issued_to_email', 'issued_to_phone',
            'rent', 'booking', 'line_items', 'tax', 'currency', 'due_date', 'notes',
        ]

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one line item is required.")

        if not isinstance(value, list):
            raise serializers.ValidationError("line_items must be a list.")

        if len(value) > MAX_LINE_ITEMS:
            raise serializers.ValidationError(
                f"A single invoice cannot have more than {MAX_LINE_ITEMS} line items."
            )

        cleaned = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    f"Item {i + 1}: each line item must be an object."
                )

            # Only allow known keys — reject any extra fields
            allowed_keys = {'description', 'amount'}
            extra_keys = set(item.keys()) - allowed_keys
            if extra_keys:
                raise serializers.ValidationError(
                    f"Item {i + 1}: unexpected fields {extra_keys}. "
                    f"Only 'description' and 'amount' are allowed."
                )

            if 'description' not in item or 'amount' not in item:
                raise serializers.ValidationError(
                    f"Item {i + 1}: both 'description' and 'amount' are required."
                )

            description = item['description']
            if not isinstance(description, str) or not description.strip():
                raise serializers.ValidationError(
                    f"Item {i + 1}: 'description' must be a non-empty string."
                )
            if len(description) > MAX_DESCRIPTION_LENGTH:
                raise serializers.ValidationError(
                    f"Item {i + 1}: 'description' must not exceed {MAX_DESCRIPTION_LENGTH} characters."
                )

            # Coerce amount to Decimal — catches strings, booleans, nested objects
            try:
                amount = Decimal(str(item['amount']))
            except (InvalidOperation, TypeError):
                raise serializers.ValidationError(
                    f"Item {i + 1}: 'amount' must be a valid number."
                )

            if amount <= 0:
                raise serializers.ValidationError(
                    f"Item {i + 1}: 'amount' must be greater than zero."
                )

            cleaned.append({'description': description.strip(), 'amount': amount})

        return cleaned

    def validate_tax(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Tax cannot be negative.")
        return value


class InvoiceSerializer(serializers.ModelSerializer):
    issued_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_issued_by_name(self, obj):
        if obj.issued_by:
            return f"{obj.issued_by.firstname} {obj.issued_by.lastname}"
        return ""
