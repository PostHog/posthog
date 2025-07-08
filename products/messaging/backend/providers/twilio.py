import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class TwilioResponse:
    def __init__(self, data: list[dict]):
        self.data = data

    def get_data(self) -> list[dict]:
        return self.data


class TwilioConfig:
    API_BASE_URL: str = "https://api.twilio.com/2010-04-01"

    def get_account_sid(self) -> str:
        account_sid = settings.TWILIO_ACCOUNT_SID
        if not account_sid:
            raise ValueError("TWILIO_ACCOUNT_SID is not set in environment or settings")
        return account_sid

    def get_auth_token(self) -> str:
        auth_token = settings.TWILIO_AUTH_TOKEN
        if not auth_token:
            raise ValueError("TWILIO_AUTH_TOKEN is not set in environment or settings")
        return auth_token


class TwilioProvider:
    def __init__(self):
        self.config = TwilioConfig()
        self.account_sid = self.config.get_account_sid()
        self.auth_token = self.config.get_auth_token()
        self.auth = (self.account_sid, self.auth_token)

    def _make_request(self, method: str, endpoint: str, data: dict | None = None) -> dict:
        url = f"{TwilioConfig.API_BASE_URL}/Accounts/{self.account_sid}{endpoint}"
        try:
            response = requests.request(method, url, auth=self.auth, data=data)
            response.raise_for_status()
            if response.status_code == 204:  # No Content
                return {}
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Twilio API error: {e}")
            raise

    def search_available_numbers(self, country_code: str, contains: str | None = None):
        """
        Search for available phone numbers in a specific country.
        """
        endpoint = f"/AvailablePhoneNumbers/{country_code}/Local.json"
        params = {"SmsEnabled": "true"}
        if contains:
            params["contains"] = contains

        # Twilio API uses GET for search with params in URL, not in request body
        url = f"{TwilioConfig.API_BASE_URL}/Accounts/{self.account_sid}{endpoint}"
        try:
            response = requests.get(url, auth=self.auth, params=params)
            response.raise_for_status()
            return response.json().get("available_phone_numbers", [])
        except requests.exceptions.RequestException as e:
            logger.exception(f"Twilio API error searching numbers: {e}")
            raise

    def verify_phone_number(self, phone_number: str):
        """
        Verify that a phone number is owned by the account and has SMS/MMS capabilities.
        """
        endpoint = f"/IncomingPhoneNumbers.json"
        params = {"PhoneNumber": phone_number}

        # Twilio API uses GET for search with params in URL, not in request body
        url = f"{TwilioConfig.API_BASE_URL}/Accounts/{self.account_sid}{endpoint}"
        try:
            response = requests.get(url, auth=self.auth, params=params)
            response.raise_for_status()
            numbers = response.json().get("incoming_phone_numbers", [])
            if not numbers:
                return {"status": "error", "message": "Phone number not found in Twilio account."}

            number = numbers[0]
            sms_enabled = number.get("capabilities", {}).get("sms", False)
            mms_enabled = number.get("capabilities", {}).get("mms", False)

            if sms_enabled and mms_enabled:
                return {"status": "success", "message": "Phone number verified."}

            errors = []
            if not sms_enabled:
                errors.append("SMS not enabled")
            if not mms_enabled:
                errors.append("MMS not enabled")
            return {"status": "error", "message": f"Verification failed: {', '.join(errors)}."}

        except requests.exceptions.RequestException as e:
            logger.exception(f"Twilio API error verifying number: {e}")
            raise

    def send_sms(self, to_number: str, from_number: str, body: str):
        """
        Send an SMS message.
        """
        endpoint = "/Messages.json"
        data = {
            "To": to_number,
            "From": from_number,
            "Body": body,
        }
        return self._make_request("POST", endpoint, data=data)
