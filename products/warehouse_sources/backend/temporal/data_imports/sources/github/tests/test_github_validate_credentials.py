import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _response(status_code: int, *, json_body: object | None = None, text: str = "") -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    if json_body is None:
        response.json.side_effect = requests.exceptions.JSONDecodeError("no json", "", 0)
    else:
        response.json.return_value = json_body
    return response


def _validate_with(response: mock.Mock) -> tuple[bool, str | None]:
    session = mock.Mock()
    session.get.return_value = response
    with mock.patch.object(github, "make_tracked_session", return_value=session):
        return github.validate_credentials("token", "owner/repo")


@pytest.mark.parametrize(
    "status_code,expected_substring",
    [
        # GitHub's 5xx "Unicorn!" page is HTML, so response.json() raises — we must never echo the markup.
        (503, "temporarily unavailable"),
        (418, "status 418"),
    ],
)
def test_non_json_body_is_not_leaked(status_code, expected_substring):
    is_valid, message = _validate_with(_response(status_code, text="<!DOCTYPE html><html>...</html>"))
    assert is_valid is False
    assert message is not None
    assert "<" not in message
    assert expected_substring in message


def test_json_error_message_is_surfaced():
    is_valid, message = _validate_with(_response(422, json_body={"message": "Validation failed"}))
    assert is_valid is False
    assert message == "Validation failed"
