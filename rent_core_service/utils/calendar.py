"""
Calendar conflict utility — single source of truth for availability checks.

Checks a date range against both:
  - Active Rent records (long-term leases)
  - Confirmed/pending Bookings (short-term stays)

Returns a human-readable conflict string if blocked, or None if the range is free.
"""
from django.db.models import Q


def check_booking_conflict(property_id, check_in, check_out, exclude_booking_id=None, exclude_rent_id=None):
    """
    Returns a conflict description string if the date range overlaps an existing
    lease or booking, otherwise returns None.

    Overlap condition: existing.start < requested.end AND existing.end > requested.start
    """
    from Rent.models import Rent
    from Bookings.models import Booking

    # Check against active leases
    lease_qs = Rent.objects.filter(
        rental_property_id=property_id,
        payment_status__in=['pending', 'paid'],
    ).filter(
        Q(start_date__lt=check_out) & Q(end_date__gt=check_in)
    )

    if exclude_rent_id:
        lease_qs = lease_qs.exclude(id=exclude_rent_id)

    if lease_qs.exists():
        lease = lease_qs.first()
        return f"lease from {lease.start_date} to {lease.end_date}"

    # Check against bookings (confirmed or checked_in block dates; pending also blocks to prevent races)
    booking_qs = Booking.objects.filter(
        property_id=property_id,
        status__in=['pending', 'confirmed', 'checked_in'],
    ).filter(
        Q(check_in_date__lt=check_out) & Q(check_out_date__gt=check_in)
    )

    if exclude_booking_id:
        booking_qs = booking_qs.exclude(id=exclude_booking_id)

    if booking_qs.exists():
        booking = booking_qs.first()
        return f"booking {booking.booking_reference} ({booking.check_in_date} to {booking.check_out_date})"

    return None


def get_blocked_ranges(property_id, year, month):
    """
    Returns a dict of blocked date ranges for a property in a given month.
    Used by the calendar endpoint.
    """
    import calendar as cal
    from datetime import date

    from Rent.models import Rent
    from Bookings.models import Booking

    first_day = date(year, month, 1)
    last_day = date(year, month, cal.monthrange(year, month)[1])

    leases = Rent.objects.filter(
        rental_property_id=property_id,
        payment_status__in=['pending', 'paid'],
        start_date__lte=last_day,
        end_date__gte=first_day,
    ).values('start_date', 'end_date')

    bookings = Booking.objects.filter(
        property_id=property_id,
        status__in=['confirmed', 'checked_in'],
        check_in_date__lte=last_day,
        check_out_date__gte=first_day,
    ).values('check_in_date', 'check_out_date', 'booking_reference')

    return {
        "leases": list(leases),
        "bookings": list(bookings),
    }
