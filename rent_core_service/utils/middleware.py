# utils/response_middleware.py
import json
import logging
from django.http import JsonResponse
from django.conf import settings

logger = logging.getLogger(__name__)

class GlobalResponseMiddleware:
    """
    Global middleware that catches all responses, errors, and exceptions
    and formats them into a standardized structure.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        try:
            # Process the request and get response
            response = self.get_response(request)
            return self._process_response(request, response)
        except Exception as exc:
            # Catch any exceptions that occur during response processing
            return self.process_exception(request, exc)
    
    def process_exception(self, request, exception):
        """
        Handle all uncaught exceptions globally and log them loudly
        """
        import traceback
        error_msg = f"CRITICAL 500 ERROR: {str(exception)}"
        tb = traceback.format_exc()
        
        # Log to the Render console
        logger.error(error_msg)
        print(error_msg) # Direct print for Render logs
        print(tb)        # Full traceback for Render logs

        response_data = {
            "success": False,
            "response": None,
            "message": "A server error occurred. Please check the backend logs.",
            "error_detail": str(exception) if settings.DEBUG else None,
            "error_code": 500
        }

        return JsonResponse(response_data, status=500)
    
    def _process_response(self, request, response):
        """
        Process successful responses and convert to standardized format
        """
        # Don't process certain response types
        if hasattr(response, 'streaming') and response.streaming:
            return response

        if hasattr(response, 'is_redirect') and response.is_redirect:
            return response

        # Try to parse the response body as JSON regardless of content-type header.
        # Relying on content_type is fragile across Django versions.
        if hasattr(response, 'content'):
            try:
                original_data = json.loads(response.content)

                # Already in our standardized format — pass through untouched.
                if isinstance(original_data, dict) and 'success' in original_data:
                    return response

                # Error responses — preserve any message from the body.
                if 400 <= response.status_code < 600:
                    original_message = None
                    if isinstance(original_data, dict):
                        original_message = (
                            original_data.get('message') or
                            original_data.get('error') or
                            original_data.get('detail')
                        )
                    message = original_message or self._get_error_message(response.status_code)
                    return JsonResponse({
                        "success": False,
                        "response": None,
                        "message": message,
                        "error_code": response.status_code
                    }, status=response.status_code)

                # Successful non-standardized JSON response.
                return JsonResponse({
                    "success": True,
                    "response": original_data,
                    "message": "Operation completed successfully"
                }, status=response.status_code)

            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                # Body is not JSON — fall through to non-JSON handling below.
                pass

        # Non-JSON error responses
        if 400 <= response.status_code < 600:
            error_message = self._extract_error_message(response)
            if not error_message:
                error_message = self._get_error_message(response.status_code)
            return JsonResponse({
                "success": False,
                "response": None,
                "message": error_message,
                "error_code": response.status_code
            }, status=response.status_code)

        return response
    
    def _extract_error_message(self, response):
        """
        Try to extract error message from response content
        """
        try:
            if hasattr(response, 'content'):
                content = response.content.decode('utf-8')
                # Try to parse as JSON
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return data.get('message') or data.get('error') or data.get('detail')
                except json.JSONDecodeError:
                    # If not JSON, return the raw content if it's not HTML
                    if not content.strip().startswith('<!DOCTYPE html>') and not content.strip().startswith('<html'):
                        return content.strip() if content.strip() else None
        except (UnicodeDecodeError, AttributeError):
            pass
        return None
    
    # utils/response_middleware.py
    def _get_error_message(self, status_code):
        """
        Get appropriate default error message based on status code
        Only used when no specific message is provided in the response
        """
        error_messages = {
            # 4xx Client Errors - Specific default messages
            400: "Bad request - The server could not understand the request due to invalid syntax.",
            401: "Unauthorized - Authentication is required and has failed or not been provided.",
            402: "Payment required - Reserved for future use.",
            403: "Forbidden - The server understood the request but refuses to authorize it.",
            404: "Resource not found - The requested resource could not be found.",
            405: "Method not allowed - The request method is not supported for the requested resource.",
            406: "Not acceptable - The server cannot produce a response matching the list of acceptable values.",
            407: "Proxy authentication required - Authentication with the proxy is required.",
            408: "Request timeout - The server timed out waiting for the request.",
            409: "Conflict - The request could not be completed due to a conflict with the current state.",
            410: "Gone - The resource requested is no longer available.",
            411: "Length required - The request did not specify the length of its content.",
            412: "Precondition failed - The server does not meet one of the preconditions.",
            413: "Payload too large - The request is larger than the server is willing to process.",
            414: "URI too long - The URI provided was too long for the server to process.",
            415: "Unsupported media type - The request entity has a media type not supported.",
            416: "Range not satisfiable - The range specified cannot be fulfilled.",
            417: "Expectation failed - The server cannot meet the requirements of the Expect header.",
            418: "I'm a teapot - The server refuses to brew coffee because it is a teapot.",
            421: "Misdirected request - The request was directed to a server not able to produce a response.",
            422: "Unprocessable entity - The request was well-formed but unable to be followed.",
            423: "Locked - The resource that is being accessed is locked.",
            424: "Failed dependency - The request failed due to failure of a previous request.",
            425: "Too early - The server is unwilling to risk processing a request that might be replayed.",
            426: "Upgrade required - The client should switch to a different protocol.",
            428: "Precondition required - The origin server requires the request to be conditional.",
            429: "Too many requests - The user has sent too many requests in a given time.",
            431: "Request header fields too large - The server is unwilling to process the request.",
            451: "Unavailable for legal reasons - The resource is unavailable for legal reasons.",
            
            # 5xx Server Errors - Generic "oops" message for all server errors (as requested)
            500: "Oops! There's an issue on our end.",
            501: "Oops! There's an issue on our end.",
            502: "Oops! There's an issue on our end.",
            503: "Oops! There's an issue on our end.",
            504: "Oops! There's an issue on our end.",
            505: "Oops! There's an issue on our end.",
            506: "Oops! There's an issue on our end.",
            507: "Oops! There's an issue on our end.",
            508: "Oops! There's an issue on our end.",
            510: "Oops! There's an issue on our end.",
            511: "Oops! There's an issue on our end.",
        }
        
        return error_messages.get(status_code, "An error occurred")