import logging
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .models import Invoice
from .serializers import InvoiceCreateSerializer, InvoiceSerializer
from Properties.views.base import IsLandlordOrAdmin

from Users.models import User
from utils.push_notifications import send_push_notification

logger = logging.getLogger(__name__)


from utils.monnify import MonnifyProvider

class PublicInvoiceDetailView(APIView):
    """
    GET /api/invoices/public/<public_id>/
    Publicly accessible view for tenants to see invoice and get transfer details.
    """
    authentication_classes = [] # No auth required
    permission_classes = []

    def get(self, request, public_id):
        try:
            invoice = get_object_or_404(
                Invoice.objects.select_related('issued_by', 'rent', 'rent__rental_property', 'booking'),
                public_id=public_id,
            )

            return Response({
                "success": True,
                "message": "Invoice retrieved",
                "data": InvoiceSerializer(invoice).data
            })
        except Exception as e:
            logger.error(f"Error in public invoice view: {e}", exc_info=True)
            return Response({"success": False, "message": "An error occurred"}, status=500)

class PublicInvoiceInitPaymentView(APIView):
    """
    POST /api/invoices/public/<public_id>/init-payment/
    Initializes a Monnify Checkout session for the invoice.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        try:
            invoice = get_object_or_404(Invoice, public_id=public_id)
            
            if invoice.status == 'paid':
                return Response({
                    "success": False,
                    "message": "This invoice is already paid."
                }, status=status.HTTP_400_BAD_REQUEST)
                
            monnify = MonnifyProvider()
            
            if not invoice.issued_by or not invoice.issued_by.monnify_subaccount_code:
                return Response({
                    "success": False, 
                    "message": "This landlord cannot receive online payments yet. Please contact them."
                }, status=status.HTTP_400_BAD_REQUEST)
                
            redirect_url = request.data.get('redirect_url') or f"https://padvault.io/pay/{invoice.public_id}"

            import uuid
            # Append a short unique ID so Monnify doesn't reject repeated payment attempts for the same invoice
            unique_reference = f"{invoice.invoice_number}_{uuid.uuid4().hex[:6]}"

            res = monnify.initialize_transaction(
                amount=float(invoice.total),
                name=invoice.issued_to_name,
                email=invoice.issued_to_email or "tenant@padvault.ng",
                reference=unique_reference,
                description=f"Rent Payment - {invoice.invoice_number}",
                redirect_url=redirect_url,
                sub_account_code=invoice.issued_by.monnify_subaccount_code
            )
            
            if res['status']:
                # Persist our paymentReference so we can query status later
                invoice.monnify_reference = unique_reference
                invoice.save(update_fields=['monnify_reference', 'updated_at'])

                return Response({
                    "success": True,
                    "checkoutUrl": res['checkoutUrl'],
                    "transactionReference": res['transactionReference']
                })
            else:
                logger.error(f"Monnify Init Failed for {invoice.invoice_number}: {res.get('message')}")
                return Response({
                    "success": False,
                    "message": "Failed to initialize payment gateway."
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error in public invoice init view: {e}", exc_info=True)
            return Response({"success": False, "message": "An error occurred"}, status=500)

class PublicInvoiceVerifyPaymentView(APIView):
    """
    POST /api/invoices/public/<public_id>/verify-payment/
    Called by the frontend after returning from Monnify checkout.
    Queries Monnify directly and triggers reconciliation if the payment succeeded.
    This is the fallback path for when the webhook hasn't fired yet (e.g. local dev).
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, public_id):
        try:
            invoice = get_object_or_404(Invoice, public_id=public_id)

            if invoice.status == 'paid':
                return Response({
                    "success": True,
                    "paid": True,
                    "data": InvoiceSerializer(invoice).data
                })

            if not invoice.monnify_reference:
                return Response({
                    "success": True,
                    "paid": False,
                    "message": "No payment session found for this invoice."
                })

            monnify = MonnifyProvider()
            res = monnify.verify_transaction(invoice.monnify_reference)

            if not res['status']:
                logger.warning(f"Monnify verify failed for {invoice.invoice_number}: {res.get('message')}")
                return Response({
                    "success": False,
                    "paid": False,
                    "message": "Could not verify payment status with gateway."
                }, status=status.HTTP_502_BAD_GATEWAY)

            payment_status = res['data'].get('paymentStatus', '')

            if payment_status in ('PAID', 'OVERPAID'):
                from decimal import Decimal
                from utils.reconciliation import reconcile_payment

                amount_paid = Decimal(str(res['data'].get('amountPaid', invoice.total)))
                # Use Monnify's internal transactionReference as the gateway reference
                gateway_reference = res['data'].get('transactionReference', invoice.monnify_reference)

                reconcile_payment(invoice, amount_paid, gateway_reference)

                invoice.refresh_from_db()
                return Response({
                    "success": True,
                    "paid": invoice.status == 'paid',
                    "data": InvoiceSerializer(invoice).data
                })

            return Response({
                "success": True,
                "paid": False,
                "payment_status": payment_status,
                "data": InvoiceSerializer(invoice).data
            })

        except Exception as e:
            logger.error(f"Verify payment error for {public_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Verification failed."}, status=500)


class InvoicePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class InvoiceListCreateView(APIView):
    """
    GET  /api/invoices/  — List all invoices issued by this landlord
    POST /api/invoices/  — Create a new invoice
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            qs = Invoice.objects.filter(issued_by=request.user).select_related('issued_by', 'rent', 'booking')

            status_filter = request.GET.get('status')
            if status_filter:
                qs = qs.filter(status=status_filter)

            paginator = InvoicePagination()
            page = paginator.paginate_queryset(qs, request)
            serializer = InvoiceSerializer(page, many=True)
            return Response({
                "success": True,
                "message": "Invoices retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": serializer.data,
            })
        except Exception as e:
            logger.error(f"Error listing invoices: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve invoices"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            serializer = InvoiceCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"success": False, "message": "Validation failed",
                                 "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            invoice = serializer.save(issued_by=request.user)

            # Push Notification to Tenant (if they are a user)
            tenant_user = User.objects.filter(email=invoice.issued_to_email).first()
            if tenant_user:
                send_push_notification(
                    tenant_user,
                    "New Invoice Received",
                    f"You have a new invoice {invoice.invoice_number} for {invoice.total} {invoice.currency}.",
                    f"/pay/{invoice.public_id}",
                    notification_type='invoice'
                )

            return Response({
                "success": True,
                "message": "Invoice created successfully",
                "data": InvoiceSerializer(invoice).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error creating invoice: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to create invoice"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InvoiceDetailView(APIView):
    """
    GET /api/invoices/<id>/  — Invoice detail
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_invoice(self, request, invoice_id):
        if request.user.role == 'admin':
            return get_object_or_404(Invoice, id=invoice_id)
        return get_object_or_404(Invoice, id=invoice_id, issued_by=request.user)

    def get(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        return Response({
            "success": True,
            "message": "Invoice retrieved successfully",
            "data": InvoiceSerializer(invoice).data,
        })


class InvoiceMarkPaidView(APIView):
    """
    PATCH /api/invoices/<id>/mark-paid/  — Manually mark invoice as paid
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, invoice_id):
        try:
            if request.user.role == 'admin':
                invoice = get_object_or_404(Invoice, id=invoice_id)
            else:
                invoice = get_object_or_404(Invoice, id=invoice_id, issued_by=request.user)

            if invoice.status == 'paid':
                return Response({"success": False, "message": "Invoice is already marked as paid."},
                                status=status.HTTP_400_BAD_REQUEST)

            from utils.reconciliation import reconcile_payment

            # Using reconcile_payment handles the transaction logging, schedule updates, 
            # and auto-generation of the next invoice.
            success = reconcile_payment(invoice, invoice.total, gateway_reference="MANUAL")

            if not success:
                 return Response({"success": False, "message": "Failed to process manual payment reconciliation."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Refresh from db since reconcile_payment mutated it
            invoice.refresh_from_db()

            return Response({
                "success": True,
                "message": "Invoice marked as paid",
                "data": InvoiceSerializer(invoice).data,
            })
        except Exception as e:
            logger.error(f"Error marking invoice {invoice_id} as paid: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update invoice"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
