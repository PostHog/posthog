import pytest
from unittest.mock import MagicMock, patch

import requests

from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, WhatsAppBotClient, get_bot_phone_number

_TOKEN = "EAAB-test-access-token"
_PHONE_ID = "111222333"


def _client() -> WhatsAppBotClient:
    return WhatsAppBotClient(access_token=_TOKEN, phone_number_id=_PHONE_ID)


def _response(status_code: int, body: dict | None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    if body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


@patch("products.slack_app.backend.services.whatsapp_api.requests.request")
def test_send_message_posts_expected_payload(mock_request):
    mock_request.return_value = _response(200, {"messages": [{"id": "wamid.OUT"}]})

    _client().send_message(to="15550001111", text="hello", reply_to_message_id="wamid.ROOT")

    assert mock_request.call_args.args[1] == f"https://graph.facebook.com/v23.0/{_PHONE_ID}/messages"
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    payload = mock_request.call_args.kwargs["json"]
    assert payload["to"] == "15550001111"
    assert payload["type"] == "text"
    assert payload["text"] == {"preview_url": False, "body": "hello"}
    assert payload["context"] == {"message_id": "wamid.ROOT"}


@patch("products.slack_app.backend.services.whatsapp_api.requests.request")
def test_error_response_raises_sanitized_error_with_code(mock_request):
    mock_request.return_value = _response(400, {"error": {"message": "Re-engagement message", "code": 131047}})

    with pytest.raises(WhatsAppApiError) as exc_info:
        _client().send_message(to="1", text="hi")

    assert _TOKEN not in str(exc_info.value)
    assert exc_info.value.code == 131047
    assert exc_info.value.is_window_closed


@patch("products.slack_app.backend.services.whatsapp_api.requests.request")
def test_transport_error_raises_sanitized_error(mock_request):
    mock_request.side_effect = requests.ConnectionError(f"POST with Bearer {_TOKEN} boom")

    with pytest.raises(WhatsAppApiError) as exc_info:
        _client().send_message(to="1", text="hi")

    assert _TOKEN not in str(exc_info.value)
    assert not exc_info.value.is_window_closed


@patch("products.slack_app.backend.services.whatsapp_api.cache")
@patch("products.slack_app.backend.services.whatsapp_api.WhatsAppBotClient")
def test_bot_phone_number_is_reduced_to_digits(mock_client_cls, mock_cache):
    # wa.me deep links break on the display formatting Graph API returns.
    mock_cache.get.return_value = None
    mock_client_cls.return_value.get_phone_number.return_value = {"display_phone_number": "+1 555-025-3483"}

    assert get_bot_phone_number() == "15550253483"
