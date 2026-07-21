import requests
import base64
import logging
import hashlib
import hmac
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

class MonnifyProvider:
    def __init__(self):
        self.api_key = settings.MONNIFY_API_KEY
        self.secret_key = settings.MONNIFY_SECRET_KEY
        self.base_url = settings.MONNIFY_BASE_URL
        self.contract_code = settings.MONNIFY_CONTRACT_CODE

    def _get_auth_token(self):
        """Get Bearer token from Monnify, utilizing cache"""
        cache_key = "monnify_access_token"
        cached_token = cache.get(cache_key)
        
        if cached_token:
            return cached_token

        auth_str = f"{self.api_key}:{self.secret_key}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {"Authorization": f"Basic {encoded_auth}"}
        url = f"{self.base_url}/api/v1/auth/login"
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            data = response.json()
            if data.get("requestSuccessful") and "responseBody" in data:
                token = data["responseBody"].get("accessToken")
                expires_in = data["responseBody"].get("expiresIn", 3600)
                # Cache for slightly less than the expiration time (e.g., 5 mins less)
                cache_timeout = max(0, expires_in - 300) 
                cache.set(cache_key, token, timeout=cache_timeout)
                return token
            logger.error(f"Monnify Auth Failed: {data.get('responseMessage')}")
            return None
        except Exception as e:
            logger.error(f"Monnify Connection Error: {str(e)}")
            return None

    def get_banks(self):
        """Fetch list of banks from Monnify with caching"""
        cache_key = "monnify_banks_list"
        cached_banks = cache.get(cache_key)
        if cached_banks:
            return cached_banks

        token = self._get_auth_token()
        if not token: return []

        url = f"{self.base_url}/api/v1/banks"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            if data.get("requestSuccessful") and "responseBody" in data:
                banks = data["responseBody"]
                # Cache for 24 hours
                cache.set(cache_key, banks, timeout=86400)
                return banks
            return []
        except Exception as e:
            logger.error(f"Monnify Get Banks Error: {str(e)}")
            return []

    def verify_bank_account(self, account_number, bank_code):
        """Validate bank account details using Disbursement Validation endpoint"""
        # --- SANDBOX BYPASS FOR TESTING ---
        if getattr(settings, 'DEBUG', False) or "sandbox.monnify.com" in self.base_url:
            logger.info("SANDBOX MODE: Bypassing real bank account validation.")
            return {"status": True, "account_name": "SANDBOX TEST ACCOUNT"}
        # ----------------------------------

        token = self._get_auth_token()
        if not token: return {"status": False, "message": "Auth failed"}

        # Correct endpoint for standard account name resolution
        url = f"{self.base_url}/api/v1/disbursements/account/validate"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"accountNumber": account_number, "bankCode": bank_code}

        try:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            if data.get("requestSuccessful") and "responseBody" in data:
                return {"status": True, "account_name": data["responseBody"]["accountName"]}
            return {"status": False, "message": data.get("responseMessage") or "Account validation failed"}
        except Exception as e:
            return {"status": False, "message": str(e)}

    def create_subaccount(self, bank_code, account_number, account_name, email):
        """Create a sub-account for split payments (Landlord)"""
        token = self._get_auth_token()
        url = f"{self.base_url}/api/v1/sub-accounts"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        from Admin.models import SystemConfig
        try:
            platform_fee = float(SystemConfig.objects.get(key='platform_fee_percentage').value)
        except SystemConfig.DoesNotExist:
            platform_fee = 10.0
        landlord_default_split = 100.0 - platform_fee

        payload = [
            {
                "currencyCode": "NGN",
                "bankCode": bank_code,
                "accountNumber": account_number,
                "accountName": account_name,
                "email": email,
                "defaultSplitPercentage": landlord_default_split
            }
        ]

        try:
            logger.info(f"Attempting to create sub-account for {email}...")
            response = requests.post(url, headers=headers, json=payload)
            data = response.json()
            
            if data.get("requestSuccessful") and isinstance(data.get("responseBody"), list) and len(data["responseBody"]) > 0:
                sub_account = data["responseBody"][0]
                logger.info(f"Sub-account created: {sub_account.get('subAccountCode')}")
                return {"status": True, "subAccountCode": sub_account["subAccountCode"]}
            
            error_msg = data.get("responseMessage") or "Unknown error from Monnify"
            logger.error(f"Monnify Sub-account Creation Failed: {error_msg}")
            return {"status": False, "message": error_msg}
        except Exception as e:
            logger.error(f"Monnify sub-account error: {str(e)}", exc_info=True)
            return {"status": False, "message": str(e)}

    def delete_subaccount(self, sub_account_code):
        """Delete a sub-account for a landlord who is closing their account"""
        token = self._get_auth_token()
        if not token: return {"status": False, "message": "Auth failed"}

        url = f"{self.base_url}/api/v1/sub-accounts/{sub_account_code}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            logger.info(f"Attempting to delete sub-account: {sub_account_code}...")
            response = requests.delete(url, headers=headers, timeout=10)
            data = response.json()
            
            if data.get("requestSuccessful"):
                logger.info(f"Successfully deleted Monnify sub-account: {sub_account_code}")
                return {"status": True}
                
            error_msg = data.get("responseMessage") or "Unknown error deleting sub-account"
            logger.error(f"Monnify Sub-account Deletion Failed: {error_msg}")
            return {"status": False, "message": error_msg}
        except Exception as e:
            logger.error(f"Monnify sub-account deletion error: {str(e)}", exc_info=True)
            return {"status": False, "message": str(e)}

    def initialize_transaction(self, amount, name, email, reference, description, redirect_url, sub_account_code=None, metadata=None):
        """
        Initialize a one-time transaction using Monnify Checkout.
        If sub_account_code is provided, implements a 90/10 split: 
        - Landlord (sub-account) gets exactly 90%
        - Platform (main account) gets 10% MINUS Monnify's fees (Platform is fee bearer)
        """
        token = self._get_auth_token()
        if not token: return {"status": False, "message": "Auth failed"}
        
        url = f"{self.base_url}/api/v1/merchant/transactions/init-transaction"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = {
            "amount": amount,
            "customerName": name,
            "customerEmail": email,
            "paymentReference": reference,
            "paymentDescription": description,
            "currencyCode": "NGN",
            "contractCode": self.contract_code,
            "redirectUrl": redirect_url,
            "paymentMethods": ["CARD", "ACCOUNT_TRANSFER", "USSD"]
        }
        
        if sub_account_code:
            from Admin.models import SystemConfig
            try:
                platform_fee = float(SystemConfig.objects.get(key='platform_fee_percentage').value)
            except SystemConfig.DoesNotExist:
                platform_fee = 10.0
            landlord_split = 100.0 - platform_fee

            payload["incomeSplitConfig"] = [
                {
                    "subAccountCode": sub_account_code,
                    "feePercentage": 0,
                    "splitPercentage": landlord_split,
                    "feeBearer": False
                }
            ]
            
        if metadata:
            payload["metaData"] = metadata

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            data = response.json()
            if data.get("requestSuccessful"):
                return {
                    "status": True,
                    "checkoutUrl": data["responseBody"]["checkoutUrl"],
                    "transactionReference": data["responseBody"]["transactionReference"]
                }
            return {"status": False, "message": data.get("responseMessage")}
        except Exception as e:
            logger.error(f"Monnify Init Transaction Error: {str(e)}")
            return {"status": False, "message": str(e)}

    def verify_transaction(self, reference):
        """Manual check for transaction status using paymentReference"""
        token = self._get_auth_token()
        if not token: return {"status": False, "message": "Auth failed"}

        # Correct Monnify endpoint for querying by paymentReference.
        # /api/v2/transactions/query (without /merchant/) returns 404 — the
        # merchant-scoped path is required.
        url = f"{self.base_url}/api/v2/merchant/transactions/query"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"paymentReference": reference}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            data = response.json()
            if data.get("requestSuccessful"):
                return {"status": True, "data": data["responseBody"]}
            logger.error(f"Monnify verify failed: {data.get('responseMessage')} | ref={reference}")
            return {"status": False, "message": data.get("responseMessage")}
        except Exception as e:
            return {"status": False, "message": str(e)}

    def verify_bvn_match(self, bvn, bank_code, account_number):
        """
        Verify if a BVN matches the provided bank account details.
        Endpoint: POST /api/v1/vas/bvn-account-match
        """
        # --- SANDBOX BYPASS FOR TESTING ---
        # If we are in the Sandbox (not Production), automatically mock a successful match
        # so local development and KYC testing isn't blocked.
        if getattr(settings, 'DEBUG', False) or "sandbox.monnify.com" in self.base_url:
            logger.info("SANDBOX MODE: Bypassing strict BVN-Account match API call.")
            return {"status": True, "match": True}
        # ----------------------------------

        token = self._get_auth_token()
        if not token: return {"status": False, "message": "Auth failed"}

        url = f"{self.base_url}/api/v1/vas/bvn-account-match"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "bankCode": bank_code,
            "accountNumber": account_number,
            "bvn": bvn
        }

        try:
            logger.info(f"Attempting BVN Match for account {account_number}...")
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            data = response.json()
            
            if data.get("requestSuccessful"):
                response_body = data.get("responseBody", {})
                match_status = response_body.get("matchStatus")
                is_match = response_body.get("match", False) or match_status in ["FULL_MATCH", "PARTIAL_MATCH"]
                return {"status": True, "match": is_match}
            
            # Detailed logging for the "error processing request" case
            logger.error(f"Monnify BVN Match Failed: Status {response.status_code}, Response: {response.text}")
            return {"status": False, "message": data.get("responseMessage") or "BVN matching service error"}
        except Exception as e:
            logger.error(f"BVN Match Exception: {str(e)}")
            return {"status": False, "message": str(e)}

    def verify_webhook(self, request_body, signature):
        """
        Validate Monnify Webhook Signature.
        Algorithm: HMAC-SHA512(secret_key, request_body)
        """
        if not signature:
            return False
            
        # Monnify uses HMAC-SHA512 with the secret key
        computed_hash = hmac.new(
            self.secret_key.encode(),
            request_body,
            hashlib.sha512
        ).hexdigest()
        
        return hmac.compare_digest(computed_hash.lower(), signature.lower())
