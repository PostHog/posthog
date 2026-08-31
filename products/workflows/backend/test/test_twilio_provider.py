from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.workflows.backend.providers.twilio import TwilioCredentialsRejectedError, TwilioProvider

ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _http_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if status_code >= 400:
        error = requests.exceptions.HTTPError(response=response)
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


class TestTwilioProvider(TestCase):
    def setUp(self) -> None:
        self.provider = TwilioProvider(account_sid=ACCOUNT_SID, auth_token="secret-token")

    @parameterized.expand([("401", 401), ("403", 403), ("404", 404)])
    @patch("products.workflows.backend.providers.twilio.capture_exception")
    @patch("products.workflows.backend.providers.twilio.requests.request")
    def test_4xx_is_a_rejected_credential_and_is_not_captured(
        self, _name: str, status_code: int, mock_request: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_request.return_value = _http_response(status_code)

        with self.assertRaises(TwilioCredentialsRejectedError):
            self.provider.get_account_info()

        mock_capture.assert_not_called()

    @patch("products.workflows.backend.providers.twilio.capture_exception")
    @patch("products.workflows.backend.providers.twilio.requests.request")
    def test_5xx_is_captured_without_the_account_sid(self, mock_request: MagicMock, mock_capture: MagicMock) -> None:
        mock_request.return_value = _http_response(500)

        with self.assertRaises(requests.exceptions.HTTPError):
            self.provider.get_account_info()

        mock_capture.assert_called_once()
        captured_message = str(mock_capture.call_args.args[0])
        assert ACCOUNT_SID not in captured_message
        assert "api.twilio.com" not in captured_message

    @patch("products.workflows.backend.providers.twilio.capture_exception")
    @patch("products.workflows.backend.providers.twilio.requests.request")
    def test_connection_error_is_captured_without_the_account_sid(
        self, mock_request: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_request.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaises(requests.exceptions.ConnectionError):
            self.provider.get_phone_numbers()

        mock_capture.assert_called_once()
        assert ACCOUNT_SID not in str(mock_capture.call_args.args[0])
