import logging
from typing import cast

import requests
from posthoganalytics import capture_exception

from products.workflows.backend.facade.contracts import TwilioAccount, TwilioPhoneNumber

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
            logger.exception(f"Twilio API error: {e}")
            raise

    def get_phone_numbers(self) -> list[TwilioPhoneNumber]:
        """
        Get all phone numbers owned by the account.
        """
        try:
            endpoint = "/IncomingPhoneNumbers.json"
            response = self._make_request("GET", endpoint)
            return response.get("incoming_phone_numbers", [])
        except requests.exceptions.HTTPError as e:
            capture_exception(Exception(f"TwilioIntegration: Failed to list twilio phone numbers: {e}"))
            return []

    def get_account_info(self) -> TwilioAccount:
        """
        Get account info.
        """
        try:
            endpoint = ".json"
            response = self._make_request("GET", endpoint)
            return cast(TwilioAccount, response)
        except requests.exceptions.HTTPError as e:
            capture_exception(Exception(f"TwilioIntegration: Failed to get account info: {e}"))
            return {}
