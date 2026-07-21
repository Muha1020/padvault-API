import logging
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.db import transaction

from .models import Booking
from .serializers import BookingCreateSerializer, BookingSerializer, BookingStatusSerializer
from Properties.models import properties
from Users.models import User
from Properties.views.base import IsLandlordOrAdmin
from utils.calendar import check_booking_conflict
from utils.rate_limit import rate_limit
from utils.email import EmailManager
from utils.push_notifications import send_push_notification

logger = logging.getLogger(__name__)


class BookingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@method_decorator(rate_limit(limit=50, window_seconds=3600, endpoint_key='booking_create'), name='post')
class BookingListCreateView(APIView):
    """
    GET  /api/bookings/           — List all bookings for landlord's properties
    POST /api/bookings/           — Log a new booking on behalf of a guest
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request):
        try:
            qs = Booking.objects.filter(
                property__landlord=request.user
            ).select_related('property', 'property__address_id')

            # Filters
            status_filter = request.GET.get('status')
            property_id = request.GET.get('property')
            search = request.GET.get('search')

            if status_filter:
                qs = qs.filter(status=status_filter)
            if property_id:
                qs = qs.filter(property_id=property_id)
            if search:
                qs = qs.filter(
                    Q(guest_name__icontains=search) |
                    Q(booking_reference__icontains=search) |
                    Q(guest_phone__icontains=search)
                )

            paginator = BookingPagination()
            page = paginator.paginate_queryset(qs, request)
            serializer = BookingSerializer(page, many=True)
            return Response({
                "success": True,
                "message": "Bookings retrieved successfully",
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "data": serializer.data,
            })

        except Exception as e:
            logger.error(f"Error listing bookings: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve bookings"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            serializer = BookingCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                }, status=status.HTTP_400_BAD_REQUEST)

            prop = serializer.validated_data['property']

            # Verify landlord owns this property
            if prop.landlord != request.user and request.user.role != 'admin':
                return Response({
                    "success": False,
                    "message": "You do not own this property.",
                }, status=status.HTTP_403_FORBIDDEN)

            # Reject bookings on lease-only properties
            if prop.listing_type == 'lease':
                return Response({
                    "success": False,
                    "message": "This property is not available for short-term bookings.",
                }, status=status.HTTP_400_BAD_REQUEST)

            # Pull nightly_rate from the property — never accept it from the request
            if not prop.nightly_rate:
                return Response({
                    "success": False,
                    "message": "This property does not have a nightly rate configured.",
                }, status=status.HTTP_400_BAD_REQUEST)

            check_in = serializer.validated_data['check_in_date']
            check_out = serializer.validated_data['check_out_date']

            # Atomic transaction + row-level lock on the property to prevent
            # race conditions where two simultaneous requests both pass the
            # conflict check before either has written to the database.
            with transaction.atomic():
                properties.objects.select_for_update().get(pk=prop.pk)

                conflict = check_booking_conflict(prop.id, check_in, check_out)
                if conflict:
                    return Response({
                        "success": False,
                        "message": f"Date conflict: property is already booked/leased during {conflict}.",
                    }, status=status.HTTP_409_CONFLICT)

                # Inject the authoritative nightly_rate from the property record
                booking = serializer.save(
                    created_by=request.user,
                    nightly_rate=prop.nightly_rate,
                )

                # Generate Monnify Invoice for the short-stay booking
                from Invoices.models import Invoice
                from datetime import timedelta
                
                # Default due date to check-in date
                due_date = booking.check_in_date
                
                invoice = Invoice.objects.create(
                    issued_by=request.user,
                    issued_to_name=booking.guest_name,
                    issued_to_email=booking.guest_email or '',
                    issued_to_phone=booking.guest_phone or '',
                    booking=booking,
                    line_items=[{
                        'description': f'{prop.title} — {booking.total_nights} Night(s) Stay ({booking.check_in_date} to {booking.check_out_date})',
                        'amount': str(booking.total_amount),
                    }, {
                        'description': 'Caution Fee',
                        'amount': str(booking.caution_fee),
                    }],
                    due_date=due_date,
                    notes=f'Auto-generated for Booking #{booking.booking_reference}.',
                    status='sent',
                )
                
                # AUTOMATION: Send the payment link to the guest's email
                if booking.guest_email:
                    try:
                        EmailManager.send_payment_invoice_email(
                            invoice=invoice,
                            tenant_email=booking.guest_email,
                            tenant_name=booking.guest_name or "Guest",
                            lease_property_title=prop.title
                        )
                        logger.info(f"Booking invoice email sent to {booking.guest_email}")
                    except Exception as email_err:
                        logger.error(f"Failed to send booking invoice email: {email_err}")

                # Push Notification to Guest (if they are a user)
                if booking.guest_email:
                    guest_user = User.objects.filter(email=booking.guest_email).first()
                    if guest_user:
                        send_push_notification(
                            guest_user,
                            "New Booking Logged",
                            f"A new booking for {prop.title} has been logged.",
                            "/dashboard/bookings",
                            notification_type='booking'
                        )

            return Response({
                "success": True,
                "message": "Booking created successfully. Invoice generated and sent to guest.",
                "data": BookingSerializer(booking).data,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating booking: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to create booking"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendBookingPaymentEmailView(APIView):
    """
    POST /api/bookings/<id>/send-payment-email/
    Manually resend the payment link for a booking.
    """
    permission_classes = [IsLandlordOrAdmin]

    def post(self, request, booking_id):
        try:
            if request.user.role == 'admin':
                booking = get_object_or_404(Booking, id=booking_id)
            else:
                booking = get_object_or_404(Booking, id=booking_id, property__landlord=request.user)

            if not booking.guest_email:
                return Response({
                    "success": False,
                    "message": "This booking has no guest email address."
                }, status=status.HTTP_400_BAD_REQUEST)

            # Find the associated invoice
            invoice = booking.invoices.first()
            if not invoice:
                return Response({
                    "success": False,
                    "message": "No invoice found for this booking."
                }, status=status.HTTP_404_NOT_FOUND)

            # Dispatch email
            EmailManager.send_booking_payment_email(
                invoice=invoice,
                guest_email=booking.guest_email,
                guest_name=booking.guest_name or "Guest",
                property_title=booking.property.title
            )

            return Response({
                "success": True,
                "message": "Payment link sent successfully."
            })
        except Exception as e:
            logger.error(f"Error resending booking email: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to send email"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BookingDetailView(APIView):
    """
    GET   /api/bookings/<id>/   — Booking detail
    PATCH /api/bookings/<id>/   — Update notes / guest info
    """
    permission_classes = [IsLandlordOrAdmin]

    def _get_booking(self, request, booking_id):
        if request.user.role == 'admin':
            return get_object_or_404(Booking.objects.select_related('property'), id=booking_id)
        return get_object_or_404(
            Booking.objects.select_related('property'),
            id=booking_id,
            property__landlord=request.user
        )

    def get(self, request, booking_id):
        booking = self._get_booking(request, booking_id)
        return Response({
            "success": True,
            "message": "Booking retrieved successfully",
            "data": BookingSerializer(booking).data,
        })

    def patch(self, request, booking_id):
        try:
            booking = self._get_booking(request, booking_id)
            allowed_fields = {'guest_name', 'guest_phone', 'guest_email', 'guest_count',
                              'special_requests', 'landlord_notes', 'source'}
            data = {k: v for k, v in request.data.items() if k in allowed_fields}
            serializer = BookingCreateSerializer(booking, data=data, partial=True)
            if not serializer.is_valid():
                return Response({"success": False, "errors": serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)
            booking = serializer.save()
            return Response({
                "success": True,
                "message": "Booking updated successfully",
                "data": BookingSerializer(booking).data,
            })
        except Exception as e:
            logger.error(f"Error updating booking {booking_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update booking"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BookingStatusUpdateView(APIView):
    """
    PATCH /api/bookings/<id>/status/  — Confirm, check-in, check-out, or cancel a booking
    """
    permission_classes = [IsLandlordOrAdmin]

    def patch(self, request, booking_id):
        try:
            if request.user.role == 'admin':
                booking = get_object_or_404(Booking, id=booking_id)
            else:
                booking = get_object_or_404(Booking, id=booking_id, property__landlord=request.user)

            serializer = BookingStatusSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"success": False, "errors": serializer.errors},
                                status=status.HTTP_400_BAD_REQUEST)

            new_status = serializer.validated_data['status']

            with transaction.atomic():
                # Re-fetch with a row lock so concurrent confirms are serialised
                booking = (
                    Booking.objects.select_for_update()
                    .get(pk=booking.pk)
                )

                # Guard against confirming a booking that now has a conflict
                if new_status == 'confirmed' and booking.status == 'pending':
                    conflict = check_booking_conflict(
                        booking.property_id,
                        booking.check_in_date,
                        booking.check_out_date,
                        exclude_booking_id=booking.id
                    )
                    if conflict:
                        return Response({
                            "success": False,
                            "message": f"Cannot confirm: date conflict with {conflict}.",
                        }, status=status.HTTP_409_CONFLICT)

                booking.status = new_status
                if 'landlord_notes' in serializer.validated_data:
                    booking.landlord_notes = serializer.validated_data['landlord_notes']
                booking.save()

                # Push Notification to Guest (if they are a user)
                if booking.guest_email:
                    guest_user = User.objects.filter(email=booking.guest_email).first()
                    if guest_user:
                        send_push_notification(
                            guest_user,
                            "Booking Update",
                            f"Your booking status for {booking.property.title} is now {new_status}.",
                            "/dashboard/bookings",
                            notification_type='booking'
                        )

            return Response({
                "success": True,
                "message": f"Booking status updated to '{new_status}'",
                "data": BookingSerializer(booking).data,
            })

        except Exception as e:
            logger.error(f"Error updating booking status {booking_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to update booking status"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PropertyBookingsView(APIView):
    """
    GET /api/bookings/property/<property_id>/  — All bookings for a specific property
    """
    permission_classes = [IsLandlordOrAdmin]

    def get(self, request, property_id):
        try:
            if request.user.role == 'admin':
                prop = get_object_or_404(properties, id=property_id)
            else:
                prop = get_object_or_404(properties, id=property_id, landlord=request.user)

            qs = Booking.objects.filter(property=prop).order_by('-check_in_date')
            status_filter = request.GET.get('status')
            if status_filter:
                qs = qs.filter(status=status_filter)

            serializer = BookingSerializer(qs, many=True)
            return Response({
                "success": True,
                "message": "Property bookings retrieved successfully",
                "data": serializer.data,
            })
        except Exception as e:
            logger.error(f"Error fetching bookings for property {property_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to retrieve property bookings"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PublicBookingRequestView(APIView):
    """
    POST /api/bookings/public/request/
    """
    permission_classes = [AllowAny]
    
    @method_decorator(rate_limit(limit=10, window_seconds=3600, endpoint_key='public_booking_request'), name='dispatch')
    def post(self, request):
        try:
            data = request.data
            prop_id = data.get('property_id')
            guest_name = data.get('guest_name')
            guest_email = data.get('guest_email')
            guest_phone = data.get('guest_phone', '')
            check_in_date = data.get('check_in_date')
            check_out_date = data.get('check_out_date')

            if not all([prop_id, guest_name, guest_email, check_in_date, check_out_date]):
                return Response({"success": False, "message": "Missing required fields."}, status=status.HTTP_400_BAD_REQUEST)
            
            prop = get_object_or_404(properties, id=prop_id, is_published=True)
            
            if prop.listing_type == 'lease':
                return Response({"success": False, "message": "Property not available for short-term booking."}, status=status.HTTP_400_BAD_REQUEST)

            if not prop.nightly_rate:
                return Response({"success": False, "message": "Nightly rate not configured for this property."}, status=status.HTTP_400_BAD_REQUEST)

            from django.db import transaction
            from utils.calendar import check_booking_conflict
            from utils.push_notifications import send_push_notification

            with transaction.atomic():
                prop = properties.objects.select_for_update().get(pk=prop.pk)
                conflict = check_booking_conflict(prop.id, check_in_date, check_out_date)
                if conflict:
                    return Response({"success": False, "message": f"Dates are already booked."}, status=status.HTTP_409_CONFLICT)
                
                booking = Booking(
                    property=prop,
                    guest_name=guest_name,
                    guest_email=guest_email,
                    guest_phone=guest_phone,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    nightly_rate=prop.nightly_rate,
                    status='pending',
                    source='direct'
                )
                booking.save() # Triggers the save() method to calculate total_amount and balance

                if prop.landlord:
                    # Notify Landlord
                    send_push_notification(
                        prop.landlord,
                        "New Booking Request",
                        f"You have a new booking request for {prop.title} from {guest_name}.",
                        "/dashboard/bookings",
                        notification_type='booking_request'
                    )

            return Response({
                "success": True,
                "message": "Booking request sent successfully. The landlord will review it.",
                "data": BookingSerializer(booking).data
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error submitting public booking: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to submit booking request."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BookingApproveView(APIView):
    """
    POST /api/bookings/<id>/approve/
    """
    permission_classes = [IsLandlordOrAdmin]

    def post(self, request, booking_id):
        try:
            if request.user.role == 'admin':
                booking = get_object_or_404(Booking, id=booking_id)
            else:
                booking = get_object_or_404(Booking, id=booking_id, property__landlord=request.user)

            if booking.status != 'pending':
                return Response({"success": False, "message": "Only pending bookings can be approved."}, status=status.HTTP_400_BAD_REQUEST)

            from django.db import transaction
            from utils.calendar import check_booking_conflict
            
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(pk=booking.pk)
                
                # Check conflicts
                conflict = check_booking_conflict(booking.property_id, booking.check_in_date, booking.check_out_date, exclude_booking_id=booking.id)
                if conflict:
                    return Response({"success": False, "message": f"Conflict with {conflict}."}, status=status.HTTP_409_CONFLICT)
                
                booking.status = 'confirmed'
                booking.save()

                from Invoices.models import Invoice
                # Generate invoice
                invoice = Invoice.objects.create(
                    issued_by=request.user,
                    issued_to_name=booking.guest_name,
                    issued_to_email=booking.guest_email or '',
                    issued_to_phone=booking.guest_phone or '',
                    booking=booking,
                    line_items=[{
                        'description': f'{booking.property.title} � {booking.total_nights} Night(s) Stay ({booking.check_in_date} to {booking.check_out_date})',
                        'amount': str(booking.total_amount),
                    }, {
                        'description': 'Caution Fee',
                        'amount': str(booking.caution_fee),
                    }],
                    due_date=booking.check_in_date,
                    notes=f'Auto-generated for Booking #{booking.booking_reference}.',
                    status='sent',
                )

                if booking.guest_email:
                    try:
                        from utils.email import EmailManager
                        EmailManager.send_booking_payment_email(
                            invoice=invoice,
                            guest_email=booking.guest_email,
                            guest_name=booking.guest_name or "Guest",
                            property_title=booking.property.title
                        )
                    except Exception as e:
                        logger.error(f"Error sending booking email: {e}")

                from utils.push_notifications import send_push_notification
                from Users.models import User
                if booking.guest_email:
                    guest_user = User.objects.filter(email=booking.guest_email).first()
                    if guest_user:
                        send_push_notification(
                            guest_user,
                            "Booking Approved!",
                            f"Your stay at {booking.property.title} was approved. Check your email to pay the invoice.",
                            "/dashboard/bookings",
                            notification_type='booking_approved'
                        )
                        
            return Response({"success": True, "message": "Booking approved successfully.", "data": BookingSerializer(booking).data})
        except Exception as e:
            logger.error(f"Error approving booking {booking_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to approve booking."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BookingRejectView(APIView):
    """
    POST /api/bookings/<id>/reject/
    """
    permission_classes = [IsLandlordOrAdmin]

    def post(self, request, booking_id):
        try:
            if request.user.role == 'admin':
                booking = get_object_or_404(Booking, id=booking_id)
            else:
                booking = get_object_or_404(Booking, id=booking_id, property__landlord=request.user)

            if booking.status != 'pending':
                return Response({"success": False, "message": "Only pending bookings can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

            booking.status = 'cancelled'
            booking.save()

            from utils.push_notifications import send_push_notification
            from Users.models import User
            if booking.guest_email:
                guest_user = User.objects.filter(email=booking.guest_email).first()
                if guest_user:
                    send_push_notification(
                        guest_user,
                        "Booking Declined",
                        f"Your request to stay at {booking.property.title} was not accepted.",
                        "/dashboard/bookings",
                        notification_type='booking_declined'
                    )
            
            return Response({"success": True, "message": "Booking rejected successfully.", "data": BookingSerializer(booking).data})
        except Exception as e:
            logger.error(f"Error rejecting booking {booking_id}: {e}", exc_info=True)
            return Response({"success": False, "message": "Failed to reject booking."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
