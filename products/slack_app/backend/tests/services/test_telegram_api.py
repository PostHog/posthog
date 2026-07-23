import pytest
from unittest.mock import MagicMock, patch

import requests

from products.slack_app.backend.services.telegram_api import TelegramApiError, TelegramBotClient

_TOKEN = "123456:test-bot-token"


def _response(status_code: int, body: dict | None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    if body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body
    return response


@patch("products.slack_app.backend.services.telegram_api.requests.post")
def test_send_message_posts_expected_payload(mock_post):
    mock_post.return_value = _response(200, {"ok": True, "result": {"message_id": 7}})

    result = TelegramBotClient(token=_TOKEN).send_message(chat_id="-100123", text="hello", reply_to_message_id="42")

    assert result == {"message_id": 7}
    url = mock_post.call_args.args[0]
    assert url == f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "-100123"
    assert payload["text"] == "hello"
    assert "parse_mode" not in payload
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert payload["reply_parameters"] == {"message_id": 42, "allow_sending_without_reply": True}


@patch("products.slack_app.backend.services.telegram_api.requests.post")
def test_non_ok_response_raises_sanitized_error(mock_post):
    mock_post.return_value = _response(400, {"ok": False, "description": "Bad Request: chat not found"})

    with pytest.raises(TelegramApiError) as exc_info:
        TelegramBotClient(token=_TOKEN).send_message(chat_id="1", text="hi")

    assert _TOKEN not in str(exc_info.value)
    assert "chat not found" in str(exc_info.value)


@patch("products.slack_app.backend.services.telegram_api.requests.post")
def test_transport_error_raises_sanitized_error(mock_post):
    mock_post.side_effect = requests.ConnectionError(f"https://api.telegram.org/bot{_TOKEN}/sendMessage boom")

    with pytest.raises(TelegramApiError) as exc_info:
        TelegramBotClient(token=_TOKEN).send_message(chat_id="1", text="hi")

    assert _TOKEN not in str(exc_info.value)
