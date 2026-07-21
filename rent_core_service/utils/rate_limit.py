import functools
import logging
from datetime import timedelta
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        # Take the rightmost IP — appended by our trusted proxy (Render).
        # The leftmost values are client-supplied and can be spoofed.
        ips = [ip.strip() for ip in forwarded_for.split(",")]
        return ips[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(limit, window_seconds, endpoint_key):
    """
    Decorator that enforces a request rate limit per IP using the database.

    Args:
        limit: Maximum number of requests allowed in the window.
        window_seconds: Duration of the time window in seconds.
        endpoint_key: A short string identifying the endpoint (e.g. 'login').
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            from Users.models import RateLimitEntry

            ip = get_client_ip(request)
            now = timezone.now()
            window_start = now - timedelta(seconds=window_seconds)

            entry, created = RateLimitEntry.objects.get_or_create(
                ip=ip,
                endpoint=endpoint_key,
                defaults={"window_start": now, "request_count": 1},
            )

            if not created:
                if entry.window_start < window_start:
                    # Window has expired — reset
                    entry.window_start = now
                    entry.request_count = 1
                    entry.save(update_fields=["window_start", "request_count"])
                else:
                    if entry.request_count >= limit:
                        logger.warning(
                            f"Rate limit exceeded for IP {ip} on endpoint '{endpoint_key}'"
                        )
                        return JsonResponse({
                            "success": False,
                            "response": None,
                            "message": "Too many requests. Please slow down and try again later.",
                            "error_code": 429,
                        }, status=429)

                    entry.request_count += 1
                    entry.save(update_fields=["request_count"])

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
