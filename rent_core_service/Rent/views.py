import logging
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q, Prefetch
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import Rent, RentInitiation, RentPayment, PaymentSchedule
from .serializers import (
    RentInitiationCreateSerializer, RentInitiationSerializer,
    RentSerializer, RentPaymentCreateSerializer, RentPaymentSerializer,
    PaymentScheduleSerializer, RentInitiationRejectSerializer,
    RentUpdateSerializer, PublicRentInitiationSerializer,
)
from Properties.models import properties
from Properties.views.base import IsLandlordOrAdmin
from utils.calendar import check_booking_conflict
from utils.email import EmailManager
from utils.push_notifications import send_push_notification
from utils.rate_limit import rate_limit
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)


class PublicRentInitiationCreateView(APIView):
    """
    POST /api/rent/initiations/public/
    Allow any user to apply for a property without an account.
    """
    permission_classes = [AllowAny]

    @method_decorator(rate_limit(10, 3600, 'public_init_ip')) # 10 per hour per IP
    def post(self, request):
        try:
            serializer = PublicRentInitiationSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "errors": serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            email = serializer.validated_data['tenant_email']

            # 1. Rate Limit by Email (3 per 24 hours)
            from datetime import timedelta
            yesterday = timezone.now() - timedelta(days=1)
            recent_apps = RentInitiation.objects.filter(
                tenant_email=email,
                created_at__gte=yesterday
            ).count()

            if recent_apps >= 3:
                return Response({
                    "success": False,
                    "message": "You have reached the application limit. Please try again later."
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)

            # 2. Verify Property
            prop = serializer.validated_data['rental_property']
            if not prop.is_published or prop.status != 'available':
                return Response({
                    "success": False,
                    "message": "This property is no longer available for applications."
                }, status=status.HTTP_400_BAD_REQUEST)

            # 3. Create record
            initiation = serializer.save(landlord=prop.landlord)

            # 4. Notify Landlord
            try:
                EmailManager.send_new_initiation_notification(prop.landlord, initiation)
            except Exception as e:
                logger.error(f"Failed to notify landlord of app #{initiation.id}: {e}")

            try:
                send_push_notification(
                    prop.landlord,
                    "New Rental Application",
                    f"{initiation.tenant_name} applied for {prop.title}.",
                    "/dashboard/rent",
                    notification_type='lease'
                )
            except Exception as e:
                logger.error(f"Failed to push-notify landlord of app #{initiation.id}: {e}")

            # 5. Notify Applicant
            try:
                EmailManager.send_application_confirmation_email(initiation)
            except Exception as e:
                logger.error(f"Failed to notify applicant of app #{initiation.id}: {e}")

            return Response({
                "success": True,
                "message": "Your application has been received. The landlord will be in touch via your email address."
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Public App Error: {e}", exc_info=True)
            return Response({"success": False, "message": "An error occurred"}, status=500)


def generate_invoice_for_schedule(schedule_entry):
    """
    Auto-generate an Invoice for a specific PaymentSchedule entry.
    Links the invoice back to the schedule and the parent rent.
    Returns the created Invoice or None on failure.
    """
    from Invoices.models import Invoice

    rent = schedule_entry.rent

    # Don't generate if one already exists
    if schedule_entry.invoice:
        return schedule_entry.invoice

    invoice = Invoice(
        issued_by=rent.rental_property.landlord,
        issued_to_name=rent.tenant_name or 'Tenant',
        issued_to_email=rent.tenant_email or '',
        issued_to_phone=rent.tenant_phone or '',
        rent=rent,
        line_items=[{
            'description': f'{rent.rental_property.title} — '
                           f'Installment {schedule_entry.installment_number} of {rent.total_periods} '
                           f'({rent.get_rent_type_display()})',
            'amount': str(schedule_entry.amount_due),
        }],
        due_date=schedule_entry.due_date,
        notes=f'Auto-generated for lease #{rent.id}, installment #{schedule_entry.installment_number}.',
        status='sent',
    )
    invoice.save()

    # Link invoice to schedule entry
    schedule_entry.invoice = invoice
    schedule_entry.save(update_fields=['invoice'])

    logger.info(
        f"Auto-generated invoice {invoice.invoice_number} for "
        f"Rent #{rent.id} installment #{schedule_entry.installment_number}"
    )
    return invoice


class RentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ── Initiations ──────────────────────────────────────────────────────────────

class RentInitiationListCreateView(APIView):
    """
    GET  /api/rent/initiations/  — List all initiations for landlord's properties
    POST /api/rent/initiations/  — Create a new lease proposal
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            qs = RentInitiation.objects.filter(
                landlord=request.user
            ).select_related('rental_property', 'tenant')

            status_filter = request.GET.get('status')
            property_id = request.GET.get('property')
            if status_filter:
                qs = qs.filter(status=status_filter)
            if property_id:
                qs = qs.filter(rental_property_id=property_id)

            paginator = RentPagination()
            page = paginator.paginate_queryset(qs, request)
            serializer = RentInitiationSerializer(page, many=True)
            return Response({
                "success": True,
                "message": "Initiations retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": serializer.data,
            })
        except Exception as e:
            logger.error(f"Error listing initiations: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve initiations"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            serializer = RentInitiationCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"success": False, "message": "Validation failed",
                                 "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            prop = serializer.validated_data['rental_property']
            if prop.landlord != request.user and request.user.role != 'admin':
                return Response({"success": False, "message": "You do not own this property."},
                                status=status.HTTP_403_FORBIDDEN)

            initiation = serializer.save(landlord=request.user)
            return Response({
                "success": True,
                "message": "Lease initiation created successfully",
                "data": RentInitiationSerializer(initiation).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error creating initiation: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to create initiation"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RentInitiationApproveView(APIView):
    """
    PATCH /api/rent/initiations/<id>/approve/
    Approve a lease initiation — runs conflict check, creates Rent + PaymentSchedule + first Invoice.
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, initiation_id):
        try:
            with transaction.atomic():
                # Support Admin role
                if request.user.role == 'admin':
                    initiation = RentInitiation.objects.get(id=initiation_id, status='pending')
                else:
                    initiation = RentInitiation.objects.get(id=initiation_id, landlord=request.user, status='pending')
                    
                from Properties.models import properties as Property
                Property.objects.select_for_update().get(pk=initiation.rental_property_id)

                conflict = check_booking_conflict(
                    initiation.rental_property_id,
                    initiation.proposed_start_date,
                    initiation.proposed_end_date,
                )
                if conflict:
                    return Response({
                        "success": False,
                        "message": f"Cannot approve: date conflict with {conflict}.",
                    }, status=status.HTTP_409_CONFLICT)

                rent = initiation.convert_to_rent()
                rent.generate_schedule()

                # Generate the first invoice but do NOT send the payment email yet
                # We will send the e-signature link instead
                first_installment = rent.schedule.order_by('installment_number').first()
                if first_installment:
                    generate_invoice_for_schedule(first_installment)

                if rent.tenant_email:
                    EmailManager.send_lease_signature_email(
                        rent=rent,
                        tenant_email=rent.tenant_email,
                        tenant_name=rent.tenant_name or "Tenant",
                        lease_property_title=rent.rental_property.title
                    )

                prop = initiation.rental_property
                prop.status = 'occupied'
                prop.save(update_fields=['status'])

                # Auto-reject any other pending applications for this property
                RentInitiation.objects.filter(
                    rental_property=prop,
                    status='pending'
                ).exclude(id=initiation.id).update(
                    status='rejected',
                    rejection_reason='Property has been leased to another applicant.'
                )

                # Push Notification to Tenant
                if rent.tenant:
                    send_push_notification(
                        rent.tenant,
                        "Lease Approved!",
                        f"Your lease for {rent.rental_property.title} has been approved.",
                        "/dashboard/rent",
                        notification_type='lease'
                    )

            return Response({
                "success": True,
                "message": "Initiation approved. Lease created.",
                "data": RentInitiationSerializer(initiation).data,
            })
        except RentInitiation.DoesNotExist:
            return Response({"success": False, "message": "Initiation not found or you don't have permission"},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error approving initiation {initiation_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to approve initiation"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RentInitiationRejectView(APIView):
    """
    PATCH /api/rent/initiations/<id>/reject/
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, initiation_id):
        try:
            if request.user.role == 'admin':
                initiation = RentInitiation.objects.get(id=initiation_id, status='pending')
            else:
                initiation = RentInitiation.objects.get(id=initiation_id, landlord=request.user, status='pending')
                
            serializer = RentInitiationRejectSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            reason = serializer.validated_data.get('rejection_reason', '')
            initiation.status = 'rejected'
            initiation.rejection_reason = reason
            initiation.save()

            # Push Notification to registered tenant
            if initiation.tenant:
                send_push_notification(
                    initiation.tenant,
                    "Lease Initiation Rejected",
                    f"Your lease initiation for {initiation.rental_property.title} was rejected.",
                    "/dashboard/rent",
                    notification_type='lease'
                )

            # Email all applicants (covers both public applicants and registered tenants)
            if initiation.tenant_email:
                try:
                    EmailManager.send_application_rejection_email(
                        tenant_email=initiation.tenant_email,
                        tenant_name=initiation.tenant_name or "Applicant",
                        property_title=initiation.rental_property.title,
                        reason=reason,
                    )
                except Exception as e:
                    logger.warning(f"Rejection email failed for {initiation.tenant_email}: {e}")

            return Response({
                "success": True,
                "message": "Initiation rejected.",
                "data": RentInitiationSerializer(initiation).data,
            })
        except RentInitiation.DoesNotExist:
            return Response({"success": False, "message": "Initiation not found or you don't have permission"},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error rejecting initiation {initiation_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to reject initiation"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Active Leases ─────────────────────────────────────────────────────────────

class RentListView(APIView):
    """
    GET /api/rent/  — List all active leases for landlord's properties
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            next_installment_qs = PaymentSchedule.objects.filter(
                status__in=['pending', 'partial', 'overdue']
            ).order_by('installment_number')

            qs = Rent.objects.filter(
                rental_property__landlord=request.user
            ).select_related('rental_property', 'tenant').prefetch_related(
                Prefetch('schedule', queryset=next_installment_qs, to_attr='active_schedules')
            )

            payment_status_filter = request.GET.get('payment_status')
            property_id = request.GET.get('property')
            if payment_status_filter:
                qs = qs.filter(payment_status=payment_status_filter)
            if property_id:
                qs = qs.filter(rental_property_id=property_id)

            paginator = RentPagination()
            page = paginator.paginate_queryset(qs, request)
            serializer = RentSerializer(page, many=True)
            return Response({
                "success": True,
                "message": "Leases retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": serializer.data,
            })
        except Exception as e:
            logger.error(f"Error listing rents: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve leases"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RentDetailView(APIView):
    """
    GET /api/rent/<id>/  — Lease detail with schedule and payment history
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request, rent_id):
        try:
            if request.user.role == 'admin':
                rent = get_object_or_404(Rent.objects.select_related('rental_property', 'tenant'), id=rent_id)
            else:
                rent = get_object_or_404(
                    Rent.objects.select_related('rental_property', 'tenant'),
                    id=rent_id, rental_property__landlord=request.user
                )
            return Response({
                "success": True,
                "message": "Lease retrieved successfully",
                "data": RentSerializer(rent).data,
            })
        except Exception as e:
            logger.error(f"Error retrieving rent {rent_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve lease"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request, rent_id):
        try:
            if request.user.role == 'admin':
                rent = get_object_or_404(Rent, id=rent_id)
            else:
                rent = get_object_or_404(Rent, id=rent_id, rental_property__landlord=request.user)
                
            serializer = RentUpdateSerializer(rent, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "errors": serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
                
            rent = serializer.save()
            return Response({
                "success": True,
                "message": "Lease updated successfully",
                "data": RentSerializer(rent).data,
            })
        except Exception as e:
            logger.error(f"Error updating rent {rent_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update lease"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RentCancelView(APIView):
    """
    PATCH /api/rent/<id>/cancel/  — Cancel an active lease
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, rent_id):
        try:
            if request.user.role == 'admin':
                rent = get_object_or_404(Rent, id=rent_id)
            else:
                rent = get_object_or_404(Rent, id=rent_id, rental_property__landlord=request.user)

            if rent.payment_status == 'cancelled':
                return Response({
                    "success": False, 
                    "message": "Lease is already cancelled."
                }, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                rent.payment_status = 'cancelled'
                rent.save(update_fields=['payment_status'])
                
                # Mark pending schedules as cancelled
                PaymentSchedule.objects.filter(rent=rent, status__in=['pending', 'partial', 'overdue']).update(status='cancelled')
                
                # Mark property as available
                prop = rent.rental_property
                prop.status = 'available'
                prop.save(update_fields=['status'])

            return Response({
                "success": True,
                "message": "Lease cancelled successfully.",
                "data": RentSerializer(rent).data,
            })
        except Exception as e:
            logger.error(f"Error cancelling rent {rent_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to cancel lease"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Payments ──────────────────────────────────────────────────────────────────

class RentPaymentCreateView(APIView):
    """
    POST /api/rent/<id>/payments/  — Record a manual payment against a lease
    GET  /api/rent/<id>/payments/  — List all payments for a lease
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_rent(self, request, rent_id):
        if request.user.role == 'admin':
            return get_object_or_404(Rent, id=rent_id)
        return get_object_or_404(Rent, id=rent_id, rental_property__landlord=request.user)

    def get(self, request, rent_id):
        rent = self._get_rent(request, rent_id)
        payments = RentPayment.objects.filter(rent=rent).order_by('-payment_date')
        return Response({
            "success": True,
            "message": "Payments retrieved successfully",
            "data": RentPaymentSerializer(payments, many=True).data,
        })

    def post(self, request, rent_id):
        try:
            rent = self._get_rent(request, rent_id)
            data = request.data.copy()
            data['rent'] = rent.id

            # Auto-fill period dates from the next unpaid schedule entry if not provided
            if not data.get('due_date') or not data.get('period_start') or not data.get('period_end'):
                unpaid_schedule = PaymentSchedule.objects.filter(
                    rent=rent, status__in=['pending', 'partial', 'overdue']
                ).first()
                if unpaid_schedule:
                    data.setdefault('due_date', str(unpaid_schedule.due_date))
                    data.setdefault('period_start', str(unpaid_schedule.due_date))
                    data.setdefault('period_end', str(rent.end_date))
                else:
                    data.setdefault('due_date', str(rent.next_payment_date))
                    data.setdefault('period_start', str(rent.next_payment_date))
                    data.setdefault('period_end', str(rent.end_date))

            serializer = RentPaymentCreateSerializer(data=data)
            if not serializer.is_valid():
                return Response({"success": False, "message": "Validation failed",
                                 "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

            amount = serializer.validated_data['amount']

            # Validate amount does not exceed the outstanding balance
            if rent.balance <= 0:
                return Response({
                    "success": False,
                    "message": "This lease has no outstanding balance.",
                }, status=status.HTTP_400_BAD_REQUEST)

            if amount > rent.balance:
                return Response({
                    "success": False,
                    "message": f"Payment amount ({amount}) exceeds the outstanding balance ({rent.balance}). "
                               f"Record a payment of at most {rent.balance}.",
                }, status=status.HTTP_400_BAD_REQUEST)

            payment = serializer.save(
                tenant=rent.tenant,
                payment_status='completed',
                payment_date=timezone.now(),
            )

            # Update rent balance
            rent.mark_as_paid(payment.amount)

            # Tick off the earliest unpaid installment
            unpaid = PaymentSchedule.objects.filter(
                rent=rent, status__in=['pending', 'partial', 'overdue']
            ).first()
            if unpaid:
                unpaid.amount_paid += payment.amount
                if unpaid.amount_paid >= unpaid.amount_due:
                    unpaid.status = 'paid'
                    unpaid.paid_at = timezone.now()
                else:
                    unpaid.status = 'partial'
                unpaid.save()

            return Response({
                "success": True,
                "message": "Payment recorded successfully",
                "data": RentPaymentSerializer(payment).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error recording payment for rent {rent_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to record payment"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RentScheduleView(APIView):
    """
    GET /api/rent/<id>/schedule/  — View the full installment schedule for a lease
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request, rent_id):
        if request.user.role == 'admin':
            rent = get_object_or_404(Rent, id=rent_id)
        else:
            rent = get_object_or_404(Rent, id=rent_id, rental_property__landlord=request.user)

        schedule = PaymentSchedule.objects.filter(rent=rent)
        return Response({
            "success": True,
            "message": "Payment schedule retrieved successfully",
            "data": PaymentScheduleSerializer(schedule, many=True).data,
        })


class SendRentPaymentEmailView(APIView):
    """
    POST /api/rent/schedule/<id>/send-payment-email/
    Manually resend the payment link for a specific rent installment.
    """
    permission_classes = [IsLandlordOrAdmin]

    def post(self, request, schedule_id):
        try:
            if request.user.role == 'admin':
                schedule = get_object_or_404(PaymentSchedule.objects.select_related('rent', 'rent__rental_property', 'invoice'), id=schedule_id)
            else:
                schedule = get_object_or_404(
                    PaymentSchedule.objects.select_related('rent', 'rent__rental_property', 'invoice'), 
                    id=schedule_id, 
                    rent__rental_property__landlord=request.user
                )

            rent = schedule.rent

            if not rent.tenant_email:
                return Response({
                    "success": False,
                    "message": "This lease has no tenant email address."
                }, status=status.HTTP_400_BAD_REQUEST)

            invoice = schedule.invoice
            if not invoice:
                # Try to generate one if it doesn't exist
                invoice = generate_invoice_for_schedule(schedule)
                if not invoice:
                    return Response({
                        "success": False,
                        "message": "Could not find or generate an invoice for this installment."
                    }, status=status.HTTP_404_NOT_FOUND)

            # Dispatch email
            EmailManager.send_payment_invoice_email(
                invoice=invoice,
                tenant_email=rent.tenant_email,
                tenant_name=rent.tenant_name or "Tenant",
                lease_property_title=rent.rental_property.title
            )

            return Response({
                "success": True,
                "message": "Payment link sent successfully."
            })
        except Exception as e:
            logger.error(f"Error resending rent invoice email: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to send email"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ── Public E-Signature Endpoints ──────────────────────────────────────────────

class PublicLeaseDetailView(APIView):
    """
    GET /api/rent/lease/<lease_public_id>/
    Publicly accessible endpoint for tenants to view the lease before signing.
    """
    permission_classes = [] # Public

    def get(self, request, public_id):
        try:
            rent = get_object_or_404(Rent.objects.select_related('rental_property', 'rental_property__landlord'), lease_public_id=public_id)
            
            return Response({
                "success": True,
                "data": {
                    "id": rent.id,
                    "lease_public_id": rent.lease_public_id,
                    "property_title": rent.rental_property.title,
                    "property_address": rent.rental_property.address_id.street if rent.rental_property.address_id else "",
                    "landlord_name": f"{rent.rental_property.landlord.lastname[0]}." if rent.rental_property.landlord.lastname else "Landlord",
                    "tenant_name": rent.tenant_name,
                    "tenant_email": f"{rent.tenant_email[:3]}***@{rent.tenant_email.split('@')[-1]}" if '@' in rent.tenant_email else "***",
                    "start_date": rent.start_date,
                    "end_date": rent.end_date,
                    "amount": rent.amount,
                    "rent_type": rent.get_rent_type_display(),
                    "total_amount": rent.total_amount,
                    "security_deposit": rent.security_deposit,
                    "is_signed": rent.is_signed,
                    "signed_at": rent.signed_at,
                    "lease_document_url": rent.lease_document_url
                }
            })
        except Exception as e:
            logger.error(f"Error retrieving public lease details: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve lease details"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class PublicLeaseSignView(APIView):
    """
    POST /api/rent/lease/<lease_public_id>/sign/
    Accepts tenant signature, generates PDF, uploads to Cloudinary, and returns payment link.
    """
    permission_classes = [] # Public

    def post(self, request, public_id):
        try:
            tenant_signature = request.data.get('signature')
            if not tenant_signature:
                return Response({"success": False, "message": "Signature is required."}, status=status.HTTP_400_BAD_REQUEST)

            rent = get_object_or_404(Rent.objects.select_related('rental_property', 'rental_property__landlord'), lease_public_id=public_id)
            
            if rent.is_signed:
                return Response({"success": False, "message": "Lease is already signed."}, status=status.HTTP_400_BAD_REQUEST)

            # Check if landlord has a saved signature
            landlord = rent.rental_property.landlord
            if not landlord.saved_signature:
                return Response({
                    "success": False, 
                    "message": "Landlord has not yet set up their digital signature. Please contact the landlord."
                }, status=status.HTTP_400_BAD_REQUEST)

            # Save signatures
            rent.tenant_signature = tenant_signature
            rent.landlord_signature = landlord.saved_signature
            rent.is_signed = True
            rent.signed_at = timezone.now()
            rent.save()

            # Generate PDF using xhtml2pdf
            from django.template.loader import render_to_string
            import cloudinary.uploader
            from io import BytesIO
            from xhtml2pdf import pisa

            # Get first invoice to return its payment link
            first_schedule = rent.schedule.order_by('installment_number').first()
            if not first_schedule:
                rent.generate_schedule()
                first_schedule = rent.schedule.order_by('installment_number').first()

            if first_schedule and not first_schedule.invoice:
                generate_invoice_for_schedule(first_schedule)

            invoice_public_id = first_schedule.invoice.public_id if first_schedule and first_schedule.invoice else None

            # Render HTML template
            context = {
                'rent': rent,
                'landlord': rent.rental_property.landlord,
                'property': rent.rental_property,
            }
            html_string = render_to_string('emails/lease_document.html', context)
            
            # Create PDF
            pdf_file = BytesIO()
            # xhtml2pdf can take the html string directly. 
            # We ensure it's encoded as utf-8.
            pisa_status = pisa.CreatePDF(
                src=html_string,
                dest=pdf_file,
                encoding='utf-8'
            )

            if pisa_status.err:
                logger.error(f"PDF Generation Error for Rent #{rent.id}: {pisa_status.err}")
                return Response({"success": False, "message": f"PDF engine error: {pisa_status.err}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            pdf_size = pdf_file.tell()
            if pdf_size < 100: # A valid PDF is never this small
                logger.error(f"Generated PDF for Rent #{rent.id} is suspiciously small: {pdf_size} bytes")
                return Response({"success": False, "message": "The generated lease document is empty. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            pdf_file.seek(0)
            
            # Upload as resource_type="raw" — Cloudinary's image CDN enforces "Restrict PDF and ZIP
            # file delivery" by default, returning 403 for any PDF served from /image/upload/.
            # Raw resources bypass that restriction and serve the file as-is.
            try:
                upload_result = cloudinary.uploader.upload(
                    pdf_file,
                    resource_type="raw",
                    type="upload",
                    folder="padvault/leases",
                    public_id=f"lease_{rent.lease_public_id}.pdf",
                    overwrite=True
                )

                rent.lease_document_url = upload_result.get('secure_url')

                rent.save(update_fields=['lease_document_url'])
            except Exception as e:
                logger.error(f"Cloudinary Upload Error for Rent #{rent.id}: {str(e)}")
                return Response({"success": False, "message": "Failed to upload lease document to cloud storage."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Email the document to both parties
            if rent.tenant_email and rent.rental_property.landlord.email:
                EmailManager.send_final_lease_document(
                    rent=rent,
                    tenant_email=rent.tenant_email,
                    landlord_email=rent.rental_property.landlord.email,
                    document_url=rent.lease_document_url
                )



            return Response({
                "success": True,
                "message": "Lease signed successfully.",
                "data": {
                    "invoice_public_id": invoice_public_id,
                    "lease_document_url": rent.lease_document_url
                }
            })

        except Exception as e:
            logger.error(f"Error signing public lease: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to sign lease."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.permissions import AllowAny

class DocumentViewRateThrottle(AnonRateThrottle):
    rate = '30/min'

class DocumentUserRateThrottle(UserRateThrottle):
    rate = '30/min'

class DownloadLeaseView(APIView):
    """
    Public endpoint to view the lease document.
    Fetches the PDF from Cloudinary and streams it directly to the browser with
    Content-Disposition: inline so it renders in an iframe rather than triggering
    a download. Streaming avoids all Cloudinary iframe/X-Frame-Options restrictions
    and removes any dependency on env-var-based URL signing.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [DocumentViewRateThrottle, DocumentUserRateThrottle]

    def get(self, request, public_id):
        import requests as http_requests
        from django.http import HttpResponse

        try:
            rent = Rent.objects.get(lease_public_id=public_id)
            if not rent.lease_document_url:
                return Response({"error": "Lease document not generated yet."}, status=status.HTTP_404_NOT_FOUND)

            upstream = http_requests.get(rent.lease_document_url, timeout=15)
            if upstream.status_code != 200:
                logger.error(f"Cloudinary fetch failed for lease {public_id}: HTTP {upstream.status_code}")
                return Response({"error": "Could not retrieve document."}, status=status.HTTP_502_BAD_GATEWAY)

            response = HttpResponse(upstream.content, content_type="application/pdf")
            response["Content-Disposition"] = f'inline; filename="lease_{public_id}.pdf"'
            return response

        except Rent.DoesNotExist:
            return Response({"error": "Lease not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error retrieving lease {public_id}: {e}", exc_info=True)
            return Response({"error": "Internal server error while retrieving document."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

