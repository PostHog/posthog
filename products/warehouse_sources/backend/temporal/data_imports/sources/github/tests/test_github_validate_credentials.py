import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _response(status_code: int, *, json_body: object | None = None, text: str = "") -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.headers = {}
    response.text = text
    if json_body is None:
        response.json.side_effect = requests.exceptions.JSONDecodeError("no json", "", 0)
    else:
        response.json.return_value = json_body
    return response


def _validate_with(response: mock.Mock) -> tuple[bool, str | None]:
    session = mock.Mock()
    session.request.return_value = response
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


@pytest.mark.parametrize(
    "repository",
    [
        "owner",  # bare owner, no repo
        "owner/repo/extra",  # too many path segments
        "/repo",  # missing owner
        "https://gitlab.com/owner/repo.git",  # a URL for another host names no GitHub repo
    ],
)
def test_malformed_repository_gets_format_guidance(repository):
    # Guards the pre-request format check: without it these reach the API, 404, and get the
    # misleading "not found or not accessible" message instead of format guidance.
    is_valid, message = github.validate_credentials("token", repository)
    assert is_valid is False
    assert message is not None
    assert "owner/repo" in message
    # Naming the offending entry keeps two malformed repos from collapsing into one repeated
    # sentence when the source layer joins their failures.
    assert repository.strip() in message


@pytest.mark.parametrize(
    "repository",
    [
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/tree/main",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo.GIT",
        "github.com/owner/repo",
    ],
)
def test_repository_url_is_read_as_owner_repo(repository):
    # A pasted GitHub URL names the repo unambiguously, so it must reach the API as owner/repo
    # instead of being rejected for its format.
    session = mock.Mock()
    session.request.return_value = _response(200, json_body={})
    with mock.patch.object(github, "make_tracked_session", return_value=session):
        is_valid, message = github.validate_credentials("token", repository)

    assert (is_valid, message) == (True, None)
    assert session.request.call_args.args[1].endswith("/repos/owner/repo")


@pytest.mark.parametrize(
    "status_code,headers",
    [
        (429, {}),  # secondary rate limit
        (403, {"x-ratelimit-remaining": "0"}),  # primary limit exhausted
    ],
)
def test_rate_limit_is_not_read_as_a_credential_problem(status_code, headers):
    # A throttled validation must tell the user to retry, not surface the 403 or 429 as if the
    # token or repository were wrong.
    response = _response(status_code, json_body={"message": "API rate limit exceeded"})
    response.headers = headers
    is_valid, message = _validate_with(response)
    assert is_valid is False
    assert message is not None
    assert "retry" in message
