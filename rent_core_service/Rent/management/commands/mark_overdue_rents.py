from django.core.management.base import BaseCommand
from django.utils import timezone
from Rent.models import PaymentSchedule
from utils.push_notifications import send_push_notification
from utils.email import EmailManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Marks overdue PaymentSchedule entries and notifies landlords and tenants.'

    def handle(self, *args, **options):
        today = timezone.now().date()

        newly_overdue = PaymentSchedule.objects.filter(
            due_date__lt=today,
            status__in=['pending', 'partial'],
        ).select_related(
            'rent',
            'rent__tenant',
            'rent__rental_property',
            'rent__rental_property__landlord',
        )

        count = 0
        for schedule in newly_overdue:
            try:
                schedule.status = 'overdue'
                schedule.save(update_fields=['status'])

                rent = schedule.rent
                landlord = rent.rental_property.landlord
                days_overdue = (today - schedule.due_date).days

                try:
                    send_push_notification(
                        landlord,
                        "Rent Payment Overdue",
                        f"{rent.tenant_name or 'Your tenant'}'s rent for {rent.rental_property.title} "
                        f"is {days_overdue} day{'s' if days_overdue != 1 else ''} overdue.",
                        "/dashboard/rent",
                        notification_type='invoice',
                    )
                except Exception as e:
                    logger.warning(f"Push to landlord {landlord.id} failed: {e}")

                if rent.tenant:
                    try:
                        send_push_notification(
                            rent.tenant,
                            "Rent Payment Overdue",
                            f"Your rent for {rent.rental_property.title} is {days_overdue} "
                            f"day{'s' if days_overdue != 1 else ''} overdue. Please pay immediately.",
                            "/dashboard/rent",
                            notification_type='invoice',
                        )
                    except Exception as e:
                        logger.warning(f"Push to tenant {rent.tenant.id} failed: {e}")

                if rent.tenant_email:
                    try:
                        EmailManager.send_overdue_rent_email(
                            tenant_email=rent.tenant_email,
                            tenant_name=rent.tenant_name or 'Tenant',
                            property_title=rent.rental_property.title,
                            amount_due=schedule.amount_due,
                            days_overdue=days_overdue,
                        )
                    except Exception as e:
                        logger.warning(f"Overdue email failed for {rent.tenant_email}: {e}")

                count += 1

            except Exception as e:
                logger.error(f"Error processing overdue schedule #{schedule.id}: {e}", exc_info=True)

        self.stdout.write(self.style.SUCCESS(f"Marked {count} installment(s) as overdue."))
