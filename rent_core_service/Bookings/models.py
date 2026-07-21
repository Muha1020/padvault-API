from django.db import models
import uuid


class Booking(models.Model):
    BOOKING_STATUS = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('cancelled', 'Cancelled'),
    ]

    BOOKING_SOURCES = [
        ('direct', 'Direct'),
        ('airbnb', 'Airbnb'),
        ('booking_com', 'Booking.com'),
        ('other', 'Other'),
    ]

    # Reference
    booking_reference = models.CharField(max_length=20, unique=True, editable=False)

    # Relationships — landlord logs this on behalf of the guest
    property = models.ForeignKey(
        'Properties.properties',
        on_delete=models.CASCADE,
        related_name='bookings'
    )
    # Guest details stored directly (guest is not a system user in Phase 1)
    guest_name = models.CharField(max_length=150)
    guest_phone = models.CharField(max_length=20, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_count = models.PositiveIntegerField(default=1)

    # Dates
    check_in_date = models.DateField()
    check_out_date = models.DateField()

    # Pricing (captured at booking time so rate changes don't affect records)
    nightly_rate = models.DecimalField(max_digits=12, decimal_places=3)
    total_nights = models.PositiveIntegerField(default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    caution_fee = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default='NGN')

    # Payment tracking (manual in Phase 1)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    balance = models.DecimalField(max_digits=15, decimal_places=3, default=0)

    # Status
    status = models.CharField(max_length=20, choices=BOOKING_STATUS, default='pending')
    source = models.CharField(max_length=20, choices=BOOKING_SOURCES, default='direct')
    special_requests = models.TextField(blank=True)
    landlord_notes = models.TextField(blank=True)

    # Logged by (the landlord who created this record)
    created_by = models.ForeignKey(
        'Users.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_bookings'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['property', 'status']),
            models.Index(fields=['check_in_date', 'check_out_date']),
            models.Index(fields=['booking_reference']),
        ]

    def __str__(self):
        return f"Booking {self.booking_reference} — {self.property.title} ({self.check_in_date} to {self.check_out_date})"

    def save(self, *args, **kwargs):
        from datetime import datetime
        from decimal import Decimal
        if not self.booking_reference:
            self.booking_reference = f"BK{uuid.uuid4().hex[:8].upper()}"
            
        if isinstance(self.check_in_date, str):
            self.check_in_date = datetime.strptime(self.check_in_date[:10], "%Y-%m-%d").date()
        if isinstance(self.check_out_date, str):
            self.check_out_date = datetime.strptime(self.check_out_date[:10], "%Y-%m-%d").date()
            
        self.nightly_rate = Decimal(str(self.nightly_rate))
        self.caution_fee = Decimal(str(self.caution_fee))
        self.amount_paid = Decimal(str(self.amount_paid))
            
        self.total_nights = (self.check_out_date - self.check_in_date).days
        self.total_amount = self.nightly_rate * self.total_nights
        self.balance = self.total_amount + self.caution_fee - self.amount_paid
        super().save(*args, **kwargs)
