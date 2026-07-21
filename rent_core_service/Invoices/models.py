import uuid
from django.db import models
from django.utils import timezone


class Invoice(models.Model):
    INVOICE_STATUS = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('partial', 'Partial'),
    ]

    # Public ID for anonymous access links
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # Auto-generated reference (INV-YYYYMM-XXXX)
    invoice_number = models.CharField(max_length=20, unique=True, editable=False)

    # Who issued it and who it's for
    issued_by = models.ForeignKey(
        'Users.User', on_delete=models.SET_NULL, null=True, related_name='issued_invoices'
    )
    issued_to_name = models.CharField(max_length=150)
    issued_to_email = models.EmailField(blank=True)
    issued_to_phone = models.CharField(max_length=20, blank=True)

    # Optional links — invoice can relate to a lease or a booking
    rent = models.ForeignKey(
        'Rent.Rent', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    booking = models.ForeignKey(
        'Bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )

    # Line items stored as JSON: [{ "description": "...", "amount": 50000 }, ...]
    line_items = models.JSONField(default=list)

    # Financials
    subtotal = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    tax = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    total = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default='NGN')

    # Status
    status = models.CharField(max_length=10, choices=INVOICE_STATUS, default='draft')
    due_date = models.DateField()
    notes = models.TextField(blank=True)

    # Monnify tracking
    monnify_reference = models.CharField(max_length=100, blank=True, null=True)
    monnify_contract_code = models.CharField(max_length=100, blank=True, null=True)
    virtual_account_number = models.CharField(max_length=20, blank=True, null=True)
    virtual_bank_name = models.CharField(max_length=100, blank=True, null=True)

    # Timestamps
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [
            models.Index(fields=['issued_by', 'status']),
            models.Index(fields=['due_date', 'status']),
            models.Index(fields=['invoice_number']),
            models.Index(fields=['public_id']),
        ]

    def __str__(self):
        return f"{self.invoice_number} — {self.issued_to_name}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            now = timezone.now()
            prefix = f"INV-{now.strftime('%Y%m')}"
            last = Invoice.objects.filter(invoice_number__startswith=prefix).count()
            self.invoice_number = f"{prefix}-{str(last + 1).zfill(4)}"

        if self.line_items:
            from decimal import Decimal
            self.subtotal = sum(
                Decimal(str(item.get('amount', 0))) for item in self.line_items
            )
        self.total = self.subtotal + (self.tax or 0)
        super().save(*args, **kwargs)
