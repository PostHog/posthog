import logging

import requests
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

TWILIO_API_BASE_URL: str = "https://api.twilio.com/2010-04-01"


class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.auth = (self.account_sid, self.auth_token)

    def _make_request(self, method: str, endpoint: str, data: dict | None = None, params: dict | None = None) -> dict:
        url = f"{TWILIO_API_BASE_URL}/Accounts/{self.account_sid}{endpoint}"
        try:
            response = requests.request(method, url, auth=self.auth, data=data, params=params)
            response.raise_for_status()
            if response.status_code == 204:  # No Content
                return {}
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning("Twilio API error: %s", e)
            raise

    def get_phone_numbers(self) -> list[dict]:
        """
        Get all phone numbers owned by the account.
        """
        try:
            endpoint = "/IncomingPhoneNumbers.json"
            response = self._make_request("GET", endpoint)
            return response.get("incoming_phone_numbers", [])
        except requests.exceptions.HTTPError:
            return []

    def get_account_info(self) -> dict:
        """
        Get account info.
        """
        try:
            endpoint = ".json"
            return self._make_request("GET", endpoint)
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403, 404):
                raise ValidationError({"account_info": "Invalid Twilio credentials"})
            raise
