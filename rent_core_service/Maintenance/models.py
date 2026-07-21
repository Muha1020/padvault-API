from django.db import models


class MaintenanceRequest(models.Model):
    CATEGORIES = [
        ('plumbing', 'Plumbing'),
        ('electrical', 'Electrical'),
        ('appliance', 'Appliance'),
        ('structural', 'Structural'),
        ('cleaning', 'Cleaning'),
        ('security', 'Security'),
        ('other', 'Other'),
    ]

    PRIORITIES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    REQUEST_STATUS = [
        ('open', 'Open'),
        ('acknowledged', 'Acknowledged'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    # Relationships
    property = models.ForeignKey(
        'Properties.properties',
        on_delete=models.CASCADE,
        related_name='maintenance_requests'
    )
    # In Phase 1 the landlord logs this; tenant name stored directly
    reported_by_name = models.CharField(max_length=150)   # tenant name / caller
    reported_by_phone = models.CharField(max_length=20, blank=True)

    # Request details
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORIES, default='other')
    priority = models.CharField(max_length=10, choices=PRIORITIES, default='medium')
    images = models.JSONField(default=list, blank=True)   # list of image URLs

    # Status tracking
    status = models.CharField(max_length=20, choices=REQUEST_STATUS, default='open')
    landlord_notes = models.TextField(blank=True)
    resolution_summary = models.TextField(blank=True)

    # Logged by (the landlord who created this record)
    created_by = models.ForeignKey(
        'Users.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='logged_maintenance_requests'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['property', 'status']),
            models.Index(fields=['priority', 'status']),
        ]

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title} — {self.property.title}"
