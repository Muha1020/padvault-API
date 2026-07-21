import logging
import requests
import json
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)

class EmailManager:
    @staticmethod
    def _send_email(subject, template_name, context, recipient_list):
        """Helper to send HTML emails via Brevo HTTP API (v3)"""
        try:
            # 1. Check if API Key is configured
            api_key = getattr(settings, 'BREVO_API_KEY', None)
            if not api_key:
                logger.error("Brevo API Key is missing from settings. Email not sent.")
                return False

            # 2. Render HTML content from Django templates
            html_content = render_to_string(f'emails/{template_name}.html', context)
            
            # 3. Prepare Brevo API Payload
            # API Reference: https://developers.brevo.com/reference/sendtransacemail
            payload = {
                "sender": {
                    "name": "Padvault",
                    "email": settings.BREVO_SENDER_EMAIL
                },
                "to": [{"email": email} for email in recipient_list],
                "subject": subject,
                "htmlContent": html_content
            }
            
            headers = {
                "api-key": api_key,
                "content-type": "application/json",
                "accept": "application/json"
            }
            
            # 4. Dispatch HTTP POST request
            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            # 5. Handle response
            if response.status_code in [200, 201, 202]:
                logger.info(f"Brevo: Email sent successfully! Subject: '{subject}' to {recipient_list}")
                return True
            else:
                logger.error(f"Brevo API Error ({response.status_code}): {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to dispatch Brevo email '{subject}': {str(e)}", exc_info=True)
            return False

    @classmethod
    def send_welcome_email(cls, user):
        context = {'user': user}
        cls._send_email(
            subject="Welcome to Padvault!",
            template_name="welcome",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_password_change_email(cls, user):
        context = {'user': user}
        cls._send_email(
            subject="Your Padvault Password was Changed",
            template_name="password_change",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_account_deletion_email(cls, user_email, user_name):
        context = {'name': user_name}
        cls._send_email(
            subject="Your Padvault Account has been Deleted",
            template_name="account_deletion",
            context=context,
            recipient_list=[user_email]
        )

    @classmethod
    def send_payment_invoice_email(cls, invoice, tenant_email, tenant_name, lease_property_title):
        context = {
            'invoice': invoice,
            'tenant_name': tenant_name,
            'property_title': lease_property_title,
            'payment_link': f"https://padvault.io/pay/{invoice.public_id}" 
        }
        cls._send_email(
            subject=f"New Rent Invoice: {lease_property_title}",
            template_name="payment_invoice",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_booking_payment_email(cls, invoice, guest_email, guest_name, property_title):
        context = {
            'invoice': invoice,
            'tenant_name': guest_name,
            'property_title': property_title,
            'payment_link': f"https://padvault.io/pay/{invoice.public_id}"
        }
        cls._send_email(
            subject=f"Stay Reservation: {property_title}",
            template_name="booking_payment",
            context=context,
            recipient_list=[guest_email]
        )

    @classmethod
    def send_payment_receipt_email(cls, transaction, invoice, tenant_email, tenant_name):
        context = {
            'transaction': transaction,
            'invoice': invoice,
            'tenant_name': tenant_name,
        }
        cls._send_email(
            subject=f"Payment Receipt: {invoice.invoice_number}",
            template_name="payment_receipt",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_landlord_payment_notification(cls, transaction, landlord):
        context = {
            'transaction': transaction,
            'landlord': landlord,
        }
        cls._send_email(
            subject=f"You received a payment: {transaction.reference}",
            template_name="landlord_notification",
            context=context,
            recipient_list=[landlord.email]
        )

    @classmethod
    def send_subscription_confirmation(cls, user, plan_name):
        context = {
            'user': user,
            'plan_name': plan_name,
        }
        cls._send_email(
            subject="Padvault Subscription Confirmed",
            template_name="subscription_confirmation",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_subscription_expiring_soon(cls, user, invoice):
        context = {
            'user': user,
            'invoice': invoice,
            'expires_at': user.subscription_expires_at,
            'payment_link': f"https://padvault.io/pay/{invoice.public_id}"
        }
        cls._send_email(
            subject="Action Required: Your Padvault Premium expires in 3 days",
            template_name="subscription_expiring_soon",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_subscription_expiring_urgent(cls, user, invoice):
        context = {
            'user': user,
            'invoice': invoice,
            'expires_at': user.subscription_expires_at,
            'payment_link': f"https://padvault.io/pay/{invoice.public_id}"
        }
        cls._send_email(
            subject="Urgent: Your Padvault Premium expires in 24 hours!",
            template_name="subscription_expiring_urgent",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_subscription_expired(cls, user, invoice):
        import datetime
        from django.utils.timezone import timedelta
        context = {
            'user': user,
            'invoice': invoice,
            'downgrade_date': user.subscription_expires_at + timedelta(days=3) if user.subscription_expires_at else datetime.date.today() + timedelta(days=3),
            'payment_link': f"https://padvault.io/pay/{invoice.public_id}"
        }
        cls._send_email(
            subject="Your Padvault Premium has expired (Grace Period Active)",
            template_name="subscription_expired",
            context=context,
            recipient_list=[user.email]
        )

    @classmethod
    def send_otp_email(cls, user_email, user_name, otp_code):
        context = {
            'name': user_name,
            'otp_code': otp_code,
        }
        cls._send_email(
            subject="Your Padvault Verification Code",
            template_name="otp_verification",
            context=context,
            recipient_list=[user_email]
        )

    @classmethod
    def send_password_reset_email(cls, user_email, user_name, otp_code):
        context = {
            'name': user_name,
            'otp_code': otp_code,
        }
        cls._send_email(
            subject="Reset your Padvault Password",
            template_name="password_reset_otp",
            context=context,
            recipient_list=[user_email]
        )

    @classmethod
    def send_lease_signature_email(cls, rent, tenant_email, tenant_name, lease_property_title):
        context = {
            'tenant_name': tenant_name,
            'property_title': lease_property_title,
            'sign_link': f"https://padvault.io/lease/{rent.lease_public_id}" 
        }
        cls._send_email(
            subject=f"Action Required: Sign Your Lease for {lease_property_title}",
            template_name="lease_signature",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_final_lease_document(cls, rent, tenant_email, landlord_email, document_url):
        # Provide a link to the secure frontend document viewer
        secure_download_url = f"https://padvault.io/documents/view/{rent.lease_public_id}"
        
        context = {
            'property_title': rent.rental_property.title,
            'document_url': secure_download_url,
        }
        cls._send_email(
            subject=f"Final Signed Lease Agreement: {rent.rental_property.title}",
            template_name="lease_final_document",
            context=context,
            recipient_list=[tenant_email, landlord_email]
        )

    @classmethod
    def send_new_initiation_notification(cls, landlord, initiation):
        context = {
            'landlord_name': landlord.firstname,
            'applicant_name': initiation.tenant_name,
            'property_title': initiation.rental_property.title,
            'proposed_amount': initiation.proposed_amount,
            'message': initiation.message,
            'dashboard_link': "https://padvault.io/dashboard/rent"
        }
        cls._send_email(
            subject=f"New Rent Application: {initiation.rental_property.title}",
            template_name="landlord_new_application",
            context=context,
            recipient_list=[landlord.email]
        )

    @classmethod
    def send_application_confirmation_email(cls, initiation):
        context = {
            'applicant_name': initiation.tenant_name,
            'property_title': initiation.rental_property.title,
        }
        cls._send_email(
            subject=f"Application Received: {initiation.rental_property.title}",
            template_name="application_confirmation",
            context=context,
            recipient_list=[initiation.tenant_email]
        )

    @classmethod
    def send_rent_reminder_email(cls, tenant_email, tenant_name, property_title, amount_due, due_date):
        context = {
            'tenant_name': tenant_name,
            'property_title': property_title,
            'amount_due': amount_due,
            'due_date': due_date,
        }
        cls._send_email(
            subject=f"Rent Reminder: Payment Due in 3 Days – {property_title}",
            template_name="rent_reminder",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_overdue_rent_email(cls, tenant_email, tenant_name, property_title, amount_due, days_overdue):
        context = {
            'tenant_name': tenant_name,
            'property_title': property_title,
            'amount_due': amount_due,
            'days_overdue': days_overdue,
        }
        cls._send_email(
            subject=f"Urgent: Overdue Rent Payment – {property_title}",
            template_name="rent_overdue",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_application_rejection_email(cls, tenant_email, tenant_name, property_title, reason=''):
        context = {
            'applicant_name': tenant_name,
            'property_title': property_title,
            'reason': reason,
        }
        cls._send_email(
            subject=f"Your Application for {property_title} — Update",
            template_name="application_rejection",
            context=context,
            recipient_list=[tenant_email]
        )

    @classmethod
    def send_admin_notification_email(cls, recipient_email, recipient_name, title, message):
        context = {
            'name': recipient_name,
            'title': title,
            'message': message,
        }
        cls._send_email(
            subject=f"Message from Padvault: {title}",
            template_name="admin_notification",
            context=context,
            recipient_list=[recipient_email]
        )

    @classmethod
    def send_support_reply_email(cls, recipient_email, recipient_name, subject, reply_body, original_message):
        context = {
            'name': recipient_name,
            'subject': subject,
            'reply_body': reply_body,
            'original_message': original_message,
        }
        cls._send_email(
            subject=f"Re: {subject}",
            template_name="support_reply",
            context=context,
            recipient_list=[recipient_email]
        )

    @classmethod
    def send_contact_email(cls, name, email, subject, message):
        context = {
            'name': name,
            'email': email,
            'subject': subject,
            'message': message,
        }
        cls._send_email(
            subject=f"New Contact Form Submission: {subject}",
            template_name="contact_us_admin",
            context=context,
            recipient_list=[settings.BREVO_SENDER_EMAIL]
        )
