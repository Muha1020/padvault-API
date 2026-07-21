from django.db import models
from Users.models import User
from Properties.models import properties

import uuid

class Rent(models.Model):
    RENT_TYPES = [
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'), 
        ('quarterly', 'Quarterly'),
        ('bi_annually', 'Bi-Annually'),
        ('custom', 'Custom'),
    ]
    
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    DEPOSIT_STATUS = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('deducted', 'Deducted')
    ]
    
    #property details
    rental_property = models.ForeignKey(properties, on_delete=models.CASCADE, related_name='rentals')
    tenant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rentals')

    # Tenant info (phase 1 — no tenant portal yet)
    tenant_name = models.CharField(max_length=200, blank=True)
    tenant_email = models.EmailField(blank=True)
    tenant_phone = models.CharField(max_length=20, blank=True)
    
    # Rent details
    rent_type = models.CharField(max_length=20, choices=RENT_TYPES, default='monthly')
    amount = models.DecimalField(max_digits=15, decimal_places=3)
    currency = models.CharField(max_length=3, default='NGN')
    
    # Duration
    start_date = models.DateField()
    end_date = models.DateField()
    duration_months = models.IntegerField()
    
    # Payment status
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    total_amount = models.DecimalField(max_digits=15, decimal_places=3)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    balance = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    
    # Rent Period Tracking
    current_period = models.IntegerField(default=1)
    total_periods = models.IntegerField()
    next_payment_date = models.DateField()
    
    # Security Deposit System
    security_deposit = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    deposit_status = models.CharField(max_length=20, choices=DEPOSIT_STATUS, default='pending')
    
    # Financial Tracking
    total_paid = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    last_payment_date = models.DateTimeField(null=True, blank=True)
    days_overdue = models.IntegerField(default=0)
    
    # E-Signature Fields
    lease_public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    tenant_signature = models.TextField(blank=True, null=True)
    landlord_signature = models.TextField(blank=True, null=True)
    lease_document_url = models.URLField(max_length=1000, blank=True, null=True)
    is_signed = models.BooleanField(default=False)
    signed_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'payment_status']),
            models.Index(fields=['rental_property', 'payment_status']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['next_payment_date']),
        ]

    def __str__(self):
        return f"Rent #{self.id} - {self.rental_property.title}"

    def save(self, *args, **kwargs):
        # Auto-calculate balance
        self.balance = self.total_amount - self.amount_paid
        self.total_paid = self.amount_paid
        super().save(*args, **kwargs)

    def calculate_balance(self):
        self.balance = self.total_amount - self.amount_paid
        self.save(update_fields=['balance'])

    def mark_as_paid(self, amount):
        from decimal import Decimal
        self.amount_paid += Decimal(str(amount))
        self.total_paid = self.amount_paid
        self.balance = self.total_amount - self.amount_paid
        if self.balance <= 0:
            self.payment_status = 'paid'
        self.save(update_fields=['amount_paid', 'total_paid', 'balance', 'payment_status'])

    @property
    def is_active(self):
        from django.utils import timezone
        today = timezone.now().date()
        return self.payment_status != 'cancelled' and self.start_date <= today <= self.end_date

    @property
    def progress_percentage(self):
        if self.total_amount > 0:
            return (self.amount_paid / self.total_amount) * 100
        return 0

    def generate_schedule(self):
        """
        Auto-generate PaymentSchedule installments for this lease.
        Called immediately after a RentInitiation is approved.
        """
        from dateutil.relativedelta import relativedelta

        period_delta = {
            'monthly': relativedelta(months=1),
            'quarterly': relativedelta(months=3),
            'bi_annually': relativedelta(months=6),
            'yearly': relativedelta(years=1),
            'custom': relativedelta(months=1),
        }.get(self.rent_type, relativedelta(months=1))

        due_date = self.start_date
        for i in range(1, self.total_periods + 1):
            PaymentSchedule.objects.get_or_create(
                rent=self,
                installment_number=i,
                defaults={
                    'due_date': due_date,
                    'amount_due': self.amount,
                }
            )
            due_date = due_date + period_delta
    
    #Rent Initiation model
class RentInitiation(models.Model):
    INITIATION_STATUS = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    
    
    rental_property = models.ForeignKey(properties, on_delete=models.CASCADE, related_name='rent_initiations')
    tenant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rent_initiations')
    landlord = models.ForeignKey(User, on_delete=models.CASCADE, related_name='landlord_initiations')

    # Tenant info (phase 1 — no tenant portal yet)
    tenant_name = models.CharField(max_length=200)
    tenant_email = models.EmailField(blank=True)
    tenant_phone = models.CharField(max_length=20, blank=True)

    # Initiation details
    proposed_start_date = models.DateField()
    proposed_end_date = models.DateField()
    proposed_rent_type = models.CharField(max_length=20, choices=Rent.RENT_TYPES, default='monthly')
    proposed_amount = models.DecimalField(max_digits=15, decimal_places=3)
    proposed_security_deposit = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    message = models.TextField(blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=INITIATION_STATUS, default='pending')
    rejection_reason = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['rental_property', 'status']),
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"Rent Initiation #{self.id} - {self.rental_property.title}"

    @property
    def total_proposed_amount(self):
        return self.proposed_amount + self.proposed_security_deposit

    def convert_to_rent(self):
        """
        Convert this initiation to an actual rent agreement.
        Returns the created Rent object.
        """
        duration_months = (self.proposed_end_date.year - self.proposed_start_date.year) * 12
        duration_months += self.proposed_end_date.month - self.proposed_start_date.month

        if self.proposed_rent_type == 'monthly':
            total_periods = duration_months
        elif self.proposed_rent_type == 'yearly':
            total_periods = max(1, duration_months // 12)
        elif self.proposed_rent_type == 'quarterly':
            total_periods = max(1, duration_months // 3)
        elif self.proposed_rent_type == 'bi_annually':
            total_periods = max(1, duration_months // 6)
        else:
            total_periods = 1

        rent = Rent.objects.create(
            rental_property=self.rental_property,
            tenant=self.tenant,
            tenant_name=self.tenant_name,
            tenant_email=self.tenant_email,
            tenant_phone=self.tenant_phone,
            rent_type=self.proposed_rent_type,
            amount=self.proposed_amount,
            currency='NGN',
            start_date=self.proposed_start_date,
            end_date=self.proposed_end_date,
            duration_months=duration_months,
            total_amount=self.proposed_amount * total_periods,
            current_period=1,
            total_periods=total_periods,
            next_payment_date=self.proposed_start_date,
            security_deposit=self.proposed_security_deposit,
            deposit_status='pending' if self.proposed_security_deposit > 0 else 'paid',
        )

        self.status = 'approved'
        self.save()
        return rent

    def reject_initiation(self, reason=""):
        """Reject this rent initiation."""
        self.status = 'rejected'
        self.rejection_reason = reason
        self.save()

# Split payment schedule — one row per installment period
class PaymentSchedule(models.Model):
    INSTALLMENT_STATUS = [
        ('pending', 'Pending'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
    ]

    rent = models.ForeignKey(Rent, on_delete=models.CASCADE, related_name='schedule')
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=15, decimal_places=3)
    amount_paid = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    status = models.CharField(max_length=10, choices=INSTALLMENT_STATUS, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)

    # Link to auto-generated invoice for this installment
    invoice = models.ForeignKey(
        'Invoices.Invoice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='schedule_entries'
    )

    class Meta:
        ordering = ['installment_number']
        unique_together = ['rent', 'installment_number']
        indexes = [
            models.Index(fields=['rent', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]

    def __str__(self):
        return f"Schedule #{self.installment_number} — Rent #{self.rent_id} — {self.amount_due}"


#rent payment model
class RentPayment(models.Model):
    PAYMENT_METHODS = [
        ('bank_transfer', 'Bank Transfer'),
        ('card', 'Credit/Debit Card'),
        ('mobile_money', 'Mobile Money'),
        ('cash', 'Cash'),
    ]
    
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    
    # Relationships
    rent = models.ForeignKey(Rent, on_delete=models.CASCADE, related_name='payments')
    tenant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rent_payments')
    
    # Payment details
    amount = models.DecimalField(max_digits=15, decimal_places=3)
    currency = models.CharField(max_length=3, default='NGN')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_reference = models.CharField(max_length=100, unique=True)
    
    # Status and dates
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    payment_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField()
    
    # Period covered
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Link to transactions app
    transaction = models.ForeignKey(
        'Transactions.Transaction', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='rent_payments'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['rent', 'payment_status']),
            models.Index(fields=['due_date', 'payment_status']),
            models.Index(fields=['payment_reference']),
        ]

    def __str__(self):
        return f"Payment #{self.id} - {self.rent.rental_property.title} - {self.amount}"