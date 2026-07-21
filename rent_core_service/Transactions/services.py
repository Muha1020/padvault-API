import logging
import json
from django.db import transaction
from django.utils import timezone

# We will import the necessary models inside the task or at the top
from Transactions.models import Transaction
from Users.models import User
from Invoices.models import Invoice
from utils.email import EmailManager
from utils.push_notifications import send_push_notification

logger = logging.getLogger(__name__)

def process_monnify_webhook(reference, amount_paid, metadata, gateway_reference):
    """
    Background thread to handle the heavy lifting of the Monnify Webhook.
    """
    logger.info(f"Starting background processing for payment: {reference}")
    from decimal import Decimal
    amount_paid = Decimal(str(amount_paid))
    
    # Strip the unique suffix appended during initialization to get the actual invoice/reference number
    # e.g., INV-12345_a1b2c3 -> INV-12345
    base_reference = reference.split('_')[0]

    try:
        # Re-verify inside lock for absolute safety
        with transaction.atomic():
            if Transaction.objects.select_for_update().filter(reference=base_reference, status='success').exists():
                 logger.info(f"Transaction {base_reference} already processed. Skipping.")
                 return f"Skipped {base_reference}"

            # Case A: Premium Subscription
            if metadata.get('type') == 'subscription':
                user_id = metadata.get('user_id')
                user = User.objects.select_for_update().get(id=user_id)
                
                # Validate against configured price (with fallback)
                from Admin.models import SystemConfig
                try:
                    expected_amount = Decimal(SystemConfig.objects.get(key='subscription_price').value)
                except SystemConfig.DoesNotExist:
                    expected_amount = Decimal("15000.00")
                if amount_paid < expected_amount:
                     logger.warning(f"Underpayment for subscription {base_reference}. Expected {expected_amount}, got {amount_paid}")
                     # Record transaction but don't upgrade
                     Transaction.objects.create(
                        transaction_type='subscription',
                        reference=base_reference,
                        amount=amount_paid,
                        net_amount=amount_paid,
                        payer=user,
                        status='success',
                        description="Partial Subscription Payment (Underpayment)",
                        payment_gateway="Monnify",
                        gateway_reference=gateway_reference
                     )
                     return f"Underpayment {reference}"

                user.subscription_tier = 'premium'
                user.subscription_status = 'active'
                user.subscription_started_at = timezone.now()
                from datetime import timedelta
                user.subscription_expires_at = timezone.now() + timedelta(days=30)
                user.save(update_fields=['subscription_tier', 'subscription_status', 'subscription_started_at', 'subscription_expires_at'])
                
                Transaction.objects.create(
                    transaction_type='subscription',
                    reference=base_reference,
                    amount=amount_paid,
                    net_amount=amount_paid, # Simplify net for now
                    payer=user,
                    status='success',
                    description="Premium Subscription Upgrade",
                    payment_gateway="Monnify",
                    gateway_reference=gateway_reference
                )
                logger.info(f"User {user.email} upgraded to premium.")
                
                # Notify user
                EmailManager.send_subscription_confirmation(user, plan_name="Premium")
                
                # Push Notification
                send_push_notification(
                    user,
                    "Premium Upgrade Successful",
                    "Your account has been upgraded to Premium. Enjoy unlimited properties!",
                    "/dashboard/settings",
                    notification_type='subscription'
                )

            # Case B: Rent / Booking via Invoice
            else:
                # Match reference to Invoice
                invoice = Invoice.objects.select_for_update().get(invoice_number=base_reference)
                
                from utils.reconciliation import reconcile_payment
                
                # Use the centralized reconciliation logic
                # This handles invoice status, transaction creation, schedule updates, 
                # cascading next invoices, and property status updates.
                success = reconcile_payment(
                    invoice=invoice, 
                    amount_paid=amount_paid, 
                    gateway_reference=gateway_reference
                )
                
                if success:
                    logger.info(f"Webhook: Successfully reconciled Invoice {base_reference}")
                else:
                    logger.error(f"Webhook: Reconciliation failed for Invoice {base_reference}")

        return f"Processed {base_reference}"

    except Invoice.DoesNotExist:
        logger.error(f"Webhook Thread Error: Invoice {base_reference} not found.")
        return f"Invoice not found: {base_reference}"
    except User.DoesNotExist:
        logger.error(f"Webhook Thread Error: User {metadata.get('user_id')} not found.")
        return f"User not found: {reference}"
    except Exception as e:
        logger.error(f"Webhook Thread Processing Error: {e}", exc_info=True)