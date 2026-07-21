# Users/validators.py
import re
from django.core.exceptions import ValidationError

def validate_email_format(email):
    """Validate email format using regex"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        raise ValidationError("Invalid email format.")
    return email

def validate_password_complexity(password):
    """Validate password meets complexity requirements"""
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if not re.search(r'[A-Z]', password):
        raise ValidationError("Password must contain at least one uppercase letter.")
    if not re.search(r'[a-z]', password):
        raise ValidationError("Password must contain at least one lowercase letter.")
    if not re.search(r'\d', password):
        raise ValidationError("Password must contain at least one digit.")
    if not re.search(r'[@$!%*?&#.]', password):
        raise ValidationError("Password must contain at least one special character (@, $, !, %, *, ?, &, #).")
    return password

def validate_role(role):
    """Validate and normalize role"""
    role = role.lower()
    if role not in ['landlord', 'tenant']:
        raise ValidationError("Role must be landlord or tenant.")
    return role