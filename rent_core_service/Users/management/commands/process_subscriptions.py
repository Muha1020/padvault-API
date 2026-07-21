from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from Users.models import User
from Invoices.models import Invoice
from Admin.models import SystemConfig
from utils.email import EmailManager
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Processes premium subscriptions, generates invoices, and sends expiry warnings.'

    def handle(self, *args, **kwargs):
        logger.info("Starting subscription processing...")
        now = timezone.now()
        try:
            sub_price = int(Decimal(SystemConfig.objects.get(key='subscription_price').value))
        except SystemConfig.DoesNotExist:
            sub_price = 15000

        # Find all premium users whose subscription is set
        premium_users = User.objects.filter(
            subscription_tier='premium',
            subscription_expires_at__isnull=False
        )

        for user in premium_users:
            try:
                time_remaining = user.subscription_expires_at - now
                days_remaining = time_remaining.days
                hours_remaining = time_remaining.total_seconds() / 3600

                # Check if we already have a pending subscription invoice
                invoice = Invoice.objects.filter(
                    issued_to_email=user.email,
                    status='draft',
                    notes__icontains='Premium Subscription Renewal'
                ).first()

                # Generate invoice if T-3 days and no invoice exists
                if 0 < days_remaining <= 3 and not invoice:
                    invoice = Invoice.objects.create(
                        issued_to_name=f"{user.firstname} {user.lastname}".strip() or "Landlord",
                        issued_to_email=user.email,
                        issued_to_phone=user.phone,
                        due_date=user.subscription_expires_at.date(),
                        tax=0,
                        notes='Premium Subscription Renewal',
                        status='draft'
                    )
                    invoice.line_items = [{"description": "Padvault Premium (1 Month)", "amount": sub_price}]
                    invoice.save()

                    # Send 3-day warning
                    EmailManager.send_subscription_expiring_soon(user, invoice)
                    logger.info(f"Generated invoice and sent 3-day warning to {user.email}")

                # Send 24-hour urgent warning
                # We check if hours_remaining is between 0 and 24.
                # To prevent multiple emails if this runs multiple times a day, 
                # we can check if it was already sent by looking at the invoice status.
                if 0 < hours_remaining <= 24 and invoice and invoice.status == 'draft':
                    # Send urgent email
                    EmailManager.send_subscription_expiring_urgent(user, invoice)
                    # Mark invoice as sent to prevent re-sending the 24-hour warning
                    invoice.status = 'sent'
                    invoice.save()
                    logger.info(f"Sent 24-hour urgent warning to {user.email}")

                # Expiry logic
                if hours_remaining <= 0:
                    if user.subscription_status == 'active':
                        user.subscription_status = 'past_due'
                        user.save()
                        # Send expired/grace period email
                        if invoice:
                            EmailManager.send_subscription_expired(user, invoice)
                        logger.info(f"Subscription expired for {user.email}. Grace period started.")
                    
                    # Auto-downgrade after 3 days of grace period
                    if days_remaining <= -3:
                        user.subscription_tier = 'free'
                        user.subscription_status = 'expired'
                        user.save()
                        if invoice and invoice.status in ['draft', 'sent']:
                            invoice.status = 'cancelled'
                            invoice.save()
                        logger.info(f"Downgraded {user.email} to free tier due to non-payment.")

            except Exception as e:
                logger.error(f"Error processing subscription for user {user.email}: {e}", exc_info=True)

        self.stdout.write(self.style.SUCCESS('Successfully processed subscriptions'))
