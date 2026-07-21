from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from Users.models import RateLimitEntry
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete expired rate limit entries from the database"

    def handle(self, *args, **kwargs):
        # Any entry whose window started more than 1 hour ago is expired
        cutoff = timezone.now() - timedelta(hours=1)
        deleted_count, _ = RateLimitEntry.objects.filter(window_start__lt=cutoff).delete()
        logger.info(f"cleanup_rate_limits: deleted {deleted_count} expired rate limit entries")
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} expired rate limit entry(s)."))
