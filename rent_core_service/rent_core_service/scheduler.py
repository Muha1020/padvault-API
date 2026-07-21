from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


def cleanup_blacklisted_tokens():
    call_command("cleanup_blacklisted_tokens")


def cleanup_rate_limits():
    call_command("cleanup_rate_limits")


def process_subscriptions():
    call_command("process_subscriptions")


def send_rent_reminders():
    call_command("send_rent_reminders")


def mark_overdue_rents():
    call_command("mark_overdue_rents")


def update_booking_statuses():
    call_command("update_booking_statuses")


def start():
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")

    scheduler.add_job(
        cleanup_blacklisted_tokens,
        trigger="interval",
        hours=6,
        id="cleanup_blacklisted_tokens",
        replace_existing=True,
    )

    scheduler.add_job(
        cleanup_rate_limits,
        trigger="interval",
        hours=1,
        id="cleanup_rate_limits",
        replace_existing=True,
    )

    scheduler.add_job(
        update_booking_statuses,
        trigger="interval",
        hours=1,
        id="update_booking_statuses",
        replace_existing=True,
    )

    scheduler.add_job(
        process_subscriptions,
        trigger="interval",
        hours=24,  # Run daily
        id="process_subscriptions",
        replace_existing=True,
    )

    scheduler.add_job(
        send_rent_reminders,
        trigger="cron",
        hour=9,
        id="send_rent_reminders",
        replace_existing=True,
    )

    scheduler.add_job(
        mark_overdue_rents,
        trigger="cron",
        hour=8,  # Run daily at 8 AM, before reminders fire at 9 AM
        id="mark_overdue_rents",
        replace_existing=True,
    )

    logger.info("Starting scheduler...")
    scheduler.start()
