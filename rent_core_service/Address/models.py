from django.db import models

# Create your models here.

class Address(models.Model):
    street = models.CharField(max_length=255)
    apartment_number = models.CharField(max_length=20, blank=True, null=True)
    city = models.CharField(max_length=100)
    state_province = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    landmark = models.CharField(max_length=255, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)

    class Meta:
        verbose_name = "Address"
        verbose_name_plural = "Addresses"
        ordering = ['city', 'street']
    def __str__(self):
        return f"{self.street_address}, {self.city}, {self.state_province}, {self.postal_code}, {self.country}"

