import requests
from posthoganalytics import capture_exception

TWILIO_API_BASE_URL: str = "https://api.twilio.com/2010-04-01"


class TwilioCredentialsRejectedError(Exception):
    """Twilio rejected the Account SID or auth token (a 4xx response)."""


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
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            if 400 <= status_code < 500:
                # Twilio rejected what the person typed. The caller turns this into a field error.
                raise TwilioCredentialsRejectedError() from None
            # Server error worth reporting, but never with the URL — it carries the account SID.
            capture_exception(Exception(f"TwilioIntegration: Twilio API request failed with status {status_code}"))
            raise
        except requests.exceptions.RequestException:
            # Connection or timeout failure, reported without the URL.
            capture_exception(Exception("TwilioIntegration: Twilio API request failed"))
            raise
        if response.status_code == 204:  # No Content
            return {}
        return response.json()

    def get_phone_numbers(self) -> list[dict]:
        """
        Get all phone numbers owned by the account.
        """
        response = self._make_request("GET", "/IncomingPhoneNumbers.json")
        return response.get("incoming_phone_numbers", [])

    def get_account_info(self) -> dict:
        """
        Get account info.
        """
        return self._make_request("GET", ".json")
