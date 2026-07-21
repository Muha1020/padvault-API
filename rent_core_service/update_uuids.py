import os
import django
import uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rent_core_service.settings')
django.setup()

from Rent.models import Rent

rents = Rent.objects.all()
for rent in rents:
    rent.lease_public_id = uuid.uuid4()
    rent.save(update_fields=['lease_public_id'])

print(f"Updated {rents.count()} rent records with unique UUIDs.")
