from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from Bookings.models import Booking

class Command(BaseCommand):
    help = 'Expires stale pending bookings and auto-transitions check-ins/check-outs'

    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()
        yesterday = now - timedelta(hours=24)

        # 1. Expire stale pending bookings (Ghost-Lock protection)
        expired_count = Booking.objects.filter(
            status='pending',
            created_at__lte=yesterday
        ).update(
            status='cancelled',
            landlord_notes='Auto-cancelled: 24hr expiration period reached without approval/payment.'
        )

        # 2. Auto Check-in
        # If the booking is confirmed and the check-in date has arrived or passed
        checkin_count = Booking.objects.filter(
            status='confirmed',
            check_in_date__lte=today
        ).update(status='checked_in')

        # 3. Auto Check-out
        # If the booking is checked in and the check-out date is in the past
        checkout_count = Booking.objects.filter(
            status='checked_in',
            check_out_date__lt=today
        ).update(status='checked_out')

        self.stdout.write(self.style.SUCCESS(
            f"Booking Status Engine Run Complete: "
            f"Expired {expired_count} | Checked In {checkin_count} | Checked Out {checkout_count}"
        ))
