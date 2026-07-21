import logging
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

# We use string-based imports or local imports inside the function
# to prevent circular dependencies.

logger = logging.getLogger(__name__)

def reconcile_payment(invoice, amount_paid, gateway_reference="MANUAL"):
    """
    Centralized logic to sync the system state when an invoice is paid.
    Handles Rent, Subscriptions, Bookings, and Next-Invoice Cascading.

    This function ensures that whether a payment is from Monnify or marked manually,
    the same business logic is applied across all modules.
    """
    from Transactions.models import Transaction
    from Users.models import User
    from Rent.models import Rent, PaymentSchedule
    from Bookings.models import Booking
    from utils.email import EmailManager
    from utils.push_notifications import send_push_notification
    from decimal import Decimal

    try:
        with transaction.atomic():
            # Re-fetch with row lock to prevent concurrent reconciliation races
            # (webhook thread and verify-payment endpoint can run simultaneously)
            invoice = invoice.__class__.objects.select_for_update().get(pk=invoice.pk)

            # Idempotency: bail out if already successfully reconciled
            if invoice.status == 'paid' or Transaction.objects.filter(
                reference=invoice.invoice_number, status='success'
            ).exists():
                return True

            amount_paid = Decimal(str(amount_paid))
            expected_amount = Decimal(str(invoice.total))

            # 1. Update Invoice Status
            if amount_paid < expected_amount:
                invoice.status = 'partial'
                logger.warning(f"Partial payment for Invoice {invoice.invoice_number}. Expected {expected_amount}, got {amount_paid}")
            else:
                invoice.status = 'paid'
                invoice.paid_at = timezone.now()

            invoice.save(update_fields=['status', 'paid_at', 'updated_at'])

            # 2. Record/Update the transaction record for the ledger
            payment_gateway = "Monnify" if gateway_reference != "MANUAL" else "Manual"
            transaction_obj, created = Transaction.objects.get_or_create(
                reference=invoice.invoice_number,
                defaults={
                    'transaction_type': 'rent_payment' if invoice.rent else 'booking_fee' if invoice.booking else 'subscription',
                    'amount': amount_paid,
                    'net_amount': amount_paid,
                    'payer': None,
                    'payee': invoice.issued_by,
                    'status': 'success',
                    'description': f"Payment for {invoice.invoice_number}",
                    'payment_gateway': payment_gateway,
                    'gateway_reference': gateway_reference,
                    'completed_at': timezone.now(),
                }
            )

            if not created:
                # Update existing transaction (e.g. if it was pending)
                transaction_obj.amount = amount_paid
                transaction_obj.status = 'success'
                transaction_obj.gateway_reference = gateway_reference
                transaction_obj.payment_gateway = payment_gateway
                transaction_obj.completed_at = timezone.now()
                transaction_obj.save()

            # 3. Handle Case: Rent Lease
            if invoice.rent:
                rent = invoice.rent
                
                # Find the Schedule Entry linked to this invoice
                # PaymentSchedule.invoice is a ForeignKey back to Invoice
                schedule_entry = rent.schedule.filter(invoice=invoice).first()
                if not schedule_entry:
                    # Fallback: find earliest unpaid installment if not explicitly linked
                    schedule_entry = rent.schedule.filter(status__in=['pending', 'overdue', 'partial']).order_by('installment_number').first()
                
                if schedule_entry:
                    schedule_entry.amount_paid += amount_paid
                    if schedule_entry.amount_paid >= schedule_entry.amount_due:
                        schedule_entry.status = 'paid'
                        schedule_entry.paid_at = timezone.now()
                    else:
                        schedule_entry.status = 'partial'
                    
                    schedule_entry.save()
                
                # Update overall Rent ledger
                rent.last_payment_date = timezone.now()
                rent.mark_as_paid(amount_paid)

                # SYNC: Update Property Status to Occupied
                if rent.rental_property.status != 'occupied':
                    prop = rent.rental_property
                    prop.status = 'occupied'
                    prop.save(update_fields=['status', 'updated_at'])
                    logger.info(f"Reconciliation: Property {prop.title} is now marked as OCCUPIED.")

                # CASCADE: Auto-generate invoice for the NEXT unpaid installment
                # This keeps the cash flow cycle moving automatically
                next_unpaid = rent.schedule.filter(
                    status__in=['pending', 'overdue'],
                    invoice__isnull=True,
                ).order_by('installment_number').first()
                
                if next_unpaid:
                    from Rent.views import generate_invoice_for_schedule
                    generate_invoice_for_schedule(next_unpaid)
                    logger.info(f"Reconciliation: Generated next invoice for Rent #{rent.id}")

            # 4. Handle Case: Booking
            elif invoice.booking:
                booking = invoice.booking
                booking.amount_paid += amount_paid
                booking.balance = (Decimal(str(booking.total_amount)) + Decimal(str(booking.caution_fee))) - booking.amount_paid
                
                if booking.balance <= 0:
                    booking.status = 'confirmed'
                booking.save()

            # 5. Handle Case: Premium Subscription Renewal
            if invoice.notes == 'Premium Subscription Renewal':
                user = User.objects.filter(email=invoice.issued_to_email).first()
                if user:
                    user.subscription_tier = 'premium'
                    user.subscription_status = 'active'
                    
                    if user.subscription_expires_at and user.subscription_expires_at > timezone.now():
                        user.subscription_expires_at += timedelta(days=30)
                    else:
                        user.subscription_expires_at = timezone.now() + timedelta(days=30)
                    
                    user.save(update_fields=['subscription_tier', 'subscription_status', 'subscription_expires_at'])
                    EmailManager.send_subscription_confirmation(user, plan_name="Premium")
                    logger.info(f"Reconciliation: User {user.email} upgraded to premium.")

            # 6. Notifications
            # Notify Tenant
            if invoice.issued_to_email:
                EmailManager.send_payment_receipt_email(
                    transaction=transaction_obj,
                    invoice=invoice,
                    tenant_email=invoice.issued_to_email,
                    tenant_name=invoice.issued_to_name
                )
                
                tenant_user = User.objects.filter(email=invoice.issued_to_email).first()
                if tenant_user:
                    send_push_notification(
                        tenant_user,
                        "Payment Successful",
                        f"Your payment for {invoice.invoice_number} was successful.",
                        f"/pay/{invoice.public_id}"
                    )

            # Notify Landlord
            if invoice.issued_by:
                EmailManager.send_landlord_payment_notification(
                    transaction=transaction_obj,
                    landlord=invoice.issued_by
                )
                send_push_notification(
                    invoice.issued_by,
                    "Payment Received",
                    f"You received {amount_paid} {invoice.currency} for {invoice.invoice_number}.",
                    "/dashboard/invoices",
                    notification_type='payment'
                )

        return True
    except Exception as e:
        logger.error(f"Reconciliation Error for Invoice {invoice.invoice_number}: {e}", exc_info=True)
        return False
