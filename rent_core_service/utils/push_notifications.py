import logging
import json
from pywebpush import webpush, WebPushException
from django.conf import settings
from Notifications.models import PushSubscription, Notification

logger = logging.getLogger(__name__)

def send_push_notification(user, title, body, url='/', notification_type='system'):
    """
    Sends a push notification to all subscriptions of a user and saves it to the database.
    """
    # 1. Save to Database History
    try:
        Notification.objects.create(
            user=user,
            title=title,
            body=body,
            link=url,
            notification_type=notification_type
        )
    except Exception as e:
        logger.error(f"Failed to save notification to database: {e}")

    # 2. Send Push
    subscriptions = PushSubscription.objects.filter(user=user)
    if not subscriptions.exists():
        return False

    vapid_private_key = getattr(settings, 'VAPID_PRIVATE_KEY', None)
    vapid_public_key = getattr(settings, 'VAPID_PUBLIC_KEY', None)
    vapid_claims = {
        "sub": getattr(settings, 'VAPID_ADMIN_EMAIL', 'mailto:padvault.ng@gmail.com')
    }

    if not vapid_private_key or not vapid_public_key:
        logger.error("VAPID keys not configured in settings")
        return False

    success_count = 0
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                },
                data=json.dumps({
                    "title": title,
                    "body": body,
                    "url": url
                }),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims
            )
            success_count += 1
        except WebPushException as ex:
            logger.warning(f"Push failed for {sub.endpoint}: {ex}")
            # If the endpoint is no longer valid (404/410), we should probably delete it
            if ex.response and ex.response.status_code in [404, 410]:
                sub.delete()
        except Exception as e:
            logger.error(f"Unexpected error sending push: {e}")

    return success_count > 0
