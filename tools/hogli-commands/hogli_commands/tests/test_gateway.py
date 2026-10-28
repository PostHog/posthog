from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from click.testing import CliRunner
from hogli_commands import gateway, posthog_auth

_HOST = "https://us.posthog.com"
_MINTED = {
    "id": "0190c0de-0000-7000-8000-000000000000",
    "token": "phe_minted",
    "expires_at": "2026-10-22T08:00:00Z",
    "cap_usd": "25.00",
    "gateway_url": "https://gateway.us.posthog.com",
    "product": "dev",
}


def _response(status_code: int, payload: Any) -> MagicMock:
    # `text` differs from the payload so an assertion on `detail` can't pass on the raw body.
    response = MagicMock(status_code=status_code, text="<html>proxy page</html>")
    response.json.return_value = payload
    return response


def _run(post: MagicMock, *args: str, host: str = f"{_HOST}/") -> tuple[Any, list[str]]:
    opened: list[str] = []

    def browser(url: str) -> bool:
        # Plays the settings page approving the request.
        opened.append(url)
        query = parse_qs(urlparse(url).query)
        params = {"code": "one-time-code", "state": query["cli_state"][0]}
        requests.get(f"http://127.0.0.1:{query['cli_port'][0]}/callback", params=params, timeout=5)
        return True

    with (
        patch.object(posthog_auth.webbrowser, "open", browser),
        patch.object(posthog_auth, "_readable_terminal", lambda: False),
        # A broken port fails the test at this deadline instead of hanging it.
        patch.object(posthog_auth, "_LOGIN_TIMEOUT_SECONDS", 5.0),
        patch.object(gateway.requests, "post", post),
    ):
        result = CliRunner(mix_stderr=False).invoke(gateway.gateway_token, ["--host", host, *args])
    return result, opened


def test_the_exchanged_verifier_matches_the_approved_challenge_and_stdout_holds_only_the_token() -> None:
    post = MagicMock(return_value=_response(201, _MINTED))

    result, opened = _run(post)

    assert result.exit_code == 0, result.output
    assert result.stdout == "phe_minted\n"
    approval = urlparse(opened[0])
    assert f"{approval.scheme}://{approval.netloc}{approval.path}" == f"{_HOST}/settings/user-ai-gateway-dev-mode"
    assert post.call_args.args[0] == f"{_HOST}/api/ai_gateway/dev_tokens/cli_exchange/"
    sent = post.call_args.kwargs["json"]
    assert sent["code"] == "one-time-code"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=")
    assert parse_qs(approval.query)["cli_challenge"] == [challenge.decode()]


def test_a_refused_exchange_reports_the_server_detail_and_prints_no_token() -> None:
    post = MagicMock(return_value=_response(400, {"code": "invalid_code", "detail": "code is expired or used"}))

    result, _ = _run(post)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "code is expired or used" in result.stderr


@pytest.mark.parametrize(
    "host,args,expected_origin",
    [
        ("https://EU.posthog.com/", (), "https://eu.posthog.com"),
        ("http://localhost:8010", (), "http://localhost:8010"),
        ("https://attacker.example", (), None),
        ("https://us.posthog.com.attacker.example", (), None),
        ("http://us.posthog.com", (), None),
        ("https://attacker.example", ("--allow-any-host",), "https://attacker.example"),
    ],
)
def test_host_allowlist(host: str, args: tuple[str, ...], expected_origin: str | None) -> None:
    post = MagicMock(return_value=_response(201, _MINTED))

    result, opened = _run(post, *args, host=host)

    if expected_origin is None:
        assert result.exit_code == 2
        assert opened == []
        post.assert_not_called()
        assert "--host" in result.stderr and "--allow-any-host" in result.stderr
    else:
        assert result.exit_code == 0, result.output
        assert opened[0].startswith(f"{expected_origin}/settings/")
        assert post.call_args.args[0].startswith(f"{expected_origin}/api/")
        assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "stdin,env,sent",
    [
        ("phe_piped\n", {"POSTHOG_GATEWAY_TOKEN": "phe_env"}, "phe_piped"),
        # A real provider key in ANTHROPIC_API_KEY is skipped, never sent to PostHog.
        ("", {"ANTHROPIC_API_KEY": "sk-ant-real", "OPENAI_API_KEY": "phe_openai"}, "phe_openai"),
    ],
)
def test_status_sends_only_a_phe_token(
    stdin: str, env: dict[str, str], sent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in gateway._TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    status = {"status": "live", "cap_usd": "25.00", "remaining_usd": "24.999343", "expires_at": "2026-10-23T22:00:00Z"}
    post = MagicMock(return_value=_response(200, status))

    with patch.object(gateway.requests, "post", post):
        result = CliRunner(mix_stderr=False).invoke(gateway.gateway_status, [], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    assert post.call_args.kwargs["json"] == {"token": sent}
    assert "$24.9993 of $25.00 left ($0.0007 spent)." in result.output


def test_status_refuses_without_a_phe_token(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in gateway._TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    post = MagicMock()

    with patch.object(gateway.requests, "post", post):
        result = CliRunner(mix_stderr=False).invoke(
            gateway.gateway_status, [], env={"ANTHROPIC_API_KEY": "sk-ant-real"}
        )

    assert result.exit_code != 0
    post.assert_not_called()
