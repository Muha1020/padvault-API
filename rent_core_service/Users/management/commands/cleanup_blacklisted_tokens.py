from django.core.management.base import BaseCommand
from django.utils import timezone
from Users.models import BlacklistedToken
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete expired blacklisted tokens from the database"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        deleted_count, _ = BlacklistedToken.objects.filter(expires_at__lt=now).delete()
        logger.info(f"cleanup_blacklisted_tokens: deleted {deleted_count} expired tokens")
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} expired blacklisted token(s)."))
