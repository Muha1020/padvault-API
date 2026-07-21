import json
import logging
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework import serializers

from utils.monnify import MonnifyProvider
from .models import Transaction
from .services import process_monnify_webhook

logger = logging.getLogger(__name__)

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = '__all__'

class TransactionListView(APIView):
    """
    GET /api/transactions/
    Lists transactions where the current user is either payer or payee.
    """
    def get(self, request):
        try:
            user = request.user
            # Transactions where user is involved
            from django.db.models import Q
            qs = Transaction.objects.filter(
                Q(payer=user) | Q(payee=user)
            ).order_by('-initiated_at')

            paginator = PageNumberPagination()
            paginator.page_size = 20
            page = paginator.paginate_queryset(qs, request)
            serializer = TransactionSerializer(page, many=True)
            
            return Response({
                "success": True,
                "data": serializer.data,
                "count": qs.count()
            })
        except Exception as e:
            logger.error(f"Error fetching transactions: {e}")
            return Response({"success": False, "message": "Internal error"}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class MonnifyWebhookView(View):
    """
    POST /api/transactions/monnify-webhook/
    Universal webhook for Monnify notifications.
    Now offloads processing to a background thread to ensure fast 200 OK response.
    """
    def post(self, request):
        monnify = MonnifyProvider()
        signature = request.META.get('HTTP_MONNIFY_SIGNATURE')
        
        if not signature:
            logger.warning("Webhook received without signature.")
            return JsonResponse({"message": "No signature"}, status=400)

        # 1. Verify Signature
        if not monnify.verify_webhook(request.body, signature):
            logger.error("Invalid Monnify Webhook Signature.")
            return JsonResponse({"message": "Invalid signature"}, status=400)

        try:
            data = json.loads(request.body)
            event_type = data.get('eventType')
            
            # We only care about successful transactions
            if event_type != 'SUCCESSFUL_TRANSACTION':
                return JsonResponse({"message": "Event ignored"}, status=200)

            payload = data.get('eventData', {})
            
            # CRITICAL FIX: Ensure paymentStatus is actually PAID
            if payload.get('paymentStatus') != 'PAID':
                logger.warning(f"Payment not completed. Status: {payload.get('paymentStatus')}")
                return JsonResponse({"status": "ignored"}, status=200)

            reference = payload.get('paymentReference')
            amount = payload.get('amountPaid')
            
            # Metadata can be a string or dict
            metadata = payload.get('metaData', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            # Dispatch the background thread (returns immediately)
            import threading
            threading.Thread(
                target=process_monnify_webhook,
                args=(
                    reference, 
                    amount, 
                    metadata,
                    payload.get('transactionReference', '')
                ),
                daemon=True
            ).start()

            # Return 200 immediately to Monnify to prevent timeouts and retries
            return JsonResponse({"status": "success"}, status=200)

        except Exception as e:
            logger.error(f"Webhook Initial Processing Error: {e}", exc_info=True)
            return JsonResponse({"message": "Internal error"}, status=500)
