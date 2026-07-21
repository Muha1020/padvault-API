from django.db import models

# Create your models here.
# transactions/models.py
from django.db import models
from Users.models import User

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('rent_payment', 'Rent Payment'),
        ('deposit', 'Security Deposit'),
        ('maintenance', 'Maintenance Fee'),
        ('utility', 'Utility Bill'),
        ('subscription', 'Premium Subscription'),
        ('booking_fee', 'Booking Fee'),
    ]
    
    TRANSACTION_STATUS = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ]
    
    # Basic information
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    reference = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    
    # Financial details
    amount = models.DecimalField(max_digits=15, decimal_places=3)
    currency = models.CharField(max_length=3, default='NGN')
    fee = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    net_amount = models.DecimalField(max_digits=15, decimal_places=3)
    
    # Parties involved - Payer is optional for guest checkouts
    payer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_transactions')
    payee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_transactions')
    
    # Metadata for non-user payers (guest bookings etc)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Status and timing
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS, default='pending')
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Payment method
    payment_method = models.CharField(max_length=50, blank=True)
    payment_gateway = models.CharField(max_length=50, blank=True)
    gateway_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-initiated_at']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['payer', 'status']),
            models.Index(fields=['status', 'initiated_at']),
        ]

    def __str__(self):
        return f"Transaction #{self.reference} - {self.amount} {self.currency}"

    def save(self, *args, **kwargs):
        self.net_amount = self.amount - self.fee
        super().save(*args, **kwargs)