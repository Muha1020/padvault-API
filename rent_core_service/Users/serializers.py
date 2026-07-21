# Users/serializers.py
from rest_framework import serializers
from .models import User
from .validators import validate_email_format, validate_password_complexity, validate_role
import bcrypt

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'password','firstname', 'lastname', 'role', 'phone']
        extra_kwargs = {
            'password': {'write_only': True},
            'firstname': {'required': False},
            'lastname': {'required': False},
            'role': {'required': False},
            'phone': {'required': False},
        }

    def validate_email(self, value):
        """Validate email format and uniqueness"""
        value = validate_email_format(value)
        
        # Check if email already exists
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already exists.")
            
        return value

    def validate_password(self, value):
        """Validate password complexity"""
        return validate_password_complexity(value)

    def validate_role(self, value):
        """Validate and normalize role"""
        value = value.lower()
        if value not in ['landlord', 'tenant']:
            raise serializers.ValidationError("Role must be landlord or tenant.")
        return value

    def create(self, validated_data):
        """Hash password and create user"""
        # Extract and hash password
        raw_password = validated_data.pop('password')
        hashed_password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt())
        
        # Create user with hashed password
        validated_data['password'] = hashed_password.decode('utf-8')
        return User.objects.create(**validated_data)