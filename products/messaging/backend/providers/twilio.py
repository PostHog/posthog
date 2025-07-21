import requests
import logging

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

    def verify_phone_number(self, phone_number: str) -> bool:
        """
        Verify that a phone number is owned by the account.
        """
        try:
            endpoint = "/IncomingPhoneNumbers.json"
            params = {"PhoneNumber": phone_number}
            response = self._make_request("GET", endpoint, params=params)
            return len(response.get("incoming_phone_numbers", [])) > 0
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Phone number verification failed. Error: {e}")
            return False
