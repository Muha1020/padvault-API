from django.db import models

# Create your models here.

#properties model
class properties(models.Model):  # lowercase
    PROPERTY_TYPES = [
        ('apartment', 'Apartment'),  ('house', 'House'), ('condo', 'Condo'), ('studio', 'Studio'),
        ('commercial', 'Commercial'), ('bungalow', 'Bungalow'), ('duplex', 'Duplex'), ('other', 'Other'),
    ]
    PROPERTY_STATUS = [
        ('available', 'Available'), ('occupied', 'Occupied'),
        ('under_maintenance', 'Under Maintenance'), ('unavailable', 'Unavailable'),
    ]
    LISTING_TYPES = [
        ('lease', 'Long-Term Lease'),
        ('short_term', 'Short-Term / Airbnb'),
        ('hybrid', 'Hybrid'),
    ]

    # Basic info
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=5000)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES, default='apartment')
    status = models.CharField(max_length=20, choices=PROPERTY_STATUS, default='available')
    listing_type = models.CharField(max_length=20, choices=LISTING_TYPES, default='lease')

    # Pricing
    yearly_rent = models.DecimalField(max_digits=16, decimal_places=3, null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    nightly_rate = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    min_nights = models.PositiveIntegerField(default=1, null=True, blank=True)
    max_nights = models.PositiveIntegerField(null=True, blank=True)
    
    # Property details
    bedrooms = models.IntegerField(default=1)
    bathrooms = models.IntegerField(default=1)
    
    # Status & visibility
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=True)
    
    # Relationships
    landlord = models.ForeignKey("Users.User", on_delete=models.CASCADE)
    address_id = models.ForeignKey("Address.Address", on_delete=models.CASCADE, null=True, blank=True)
    
    # Images
    main_image = models.URLField(max_length=600, null=True, blank=True)
    image_urls = models.JSONField(default=list, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    #analytics
    views_count = models.PositiveIntegerField(default=0)  # For analytics

    # Moderation
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.TextField(null=True, blank=True)
    

    class Meta:
        verbose_name_plural = "properties"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_published', 'status']),
            models.Index(fields=['landlord', 'status']),
            models.Index(fields=['listing_type']),
            models.Index(fields=['property_type']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['-created_at']),
        ]

# Asset profiles: meter numbers, smart locks, WiFi codes, etc.
class PropertyAsset(models.Model):
    ASSET_CATEGORIES = [
        ('appliance', 'Appliance'),
        ('furniture', 'Furniture'),
        ('fixture', 'Fixture'),
        ('utility', 'Utility/Access'),
        ('other', 'Other'),
    ]

    CONDITION_CHOICES = [
        ('new', 'New'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('damaged', 'Damaged'),
    ]

    property = models.ForeignKey(properties, on_delete=models.CASCADE, related_name='assets')
    name = models.CharField(max_length=100, default='Unknown')
    category = models.CharField(max_length=20, choices=ASSET_CATEGORIES, default='appliance')
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='good')
    serial_number = models.CharField(max_length=200, blank=True)
    estimated_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()}) — {self.property.title}"


#saved properties model
class saved_properties(models.Model):
     user_id= models.ForeignKey("Users.User", on_delete=models.CASCADE, null=True)
     property_id= models.ForeignKey("properties", on_delete=models.CASCADE, null=True)
     created_at = models.DateTimeField(auto_now_add=True)  # Add this field
    
     class Meta:
        unique_together = ['user_id', 'property_id']  # Prevent duplicate saves
     def __str__(self):
         return f"{self.user_id.email} saved {self.property_id.title}"