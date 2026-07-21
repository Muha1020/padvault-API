from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from Rent.models import PaymentSchedule
from utils.push_notifications import send_push_notification
from utils.email import EmailManager

class Command(BaseCommand):
    help = 'Checks for upcoming rent due dates and sends reminders'

    def handle(self, *args, **options):
        today = timezone.now().date()
        reminder_date = today + timedelta(days=3) # Reminder 3 days before

        # Find schedules due in 3 days that aren't paid yet
        upcoming_schedules = PaymentSchedule.objects.filter(
            due_date=reminder_date,
            status__in=['pending', 'partial']
        ).select_related('rent', 'rent__tenant', 'rent__rental_property')

        self.stdout.write(f"Checking reminders for {reminder_date}...")

        count = 0
        for schedule in upcoming_schedules:
            tenant = schedule.rent.tenant
            if tenant:
                property_title = schedule.rent.rental_property.title
                amount_due = schedule.amount_due
                due_date = schedule.due_date.strftime('%d %B %Y')

                try:
                    send_push_notification(
                        tenant,
                        "Rent Reminder",
                        f"Hi {tenant.firstname}, your rent for {property_title} is due in 3 days.",
                        "/dashboard/rent",
                        notification_type='invoice'
                    )
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Push failed for tenant {tenant.id}: {e}"))

                try:
                    EmailManager.send_rent_reminder_email(
                        tenant_email=tenant.email,
                        tenant_name=tenant.firstname,
                        property_title=property_title,
                        amount_due=amount_due,
                        due_date=due_date,
                    )
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Email failed for tenant {tenant.id}: {e}"))

                count += 1
        
        self.stdout.write(self.style.SUCCESS(f"Sent {count} rent reminders."))
