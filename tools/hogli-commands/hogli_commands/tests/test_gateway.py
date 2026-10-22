from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse

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


def _run(post: MagicMock, *args: str) -> tuple[Any, list[str]]:
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
        result = CliRunner(mix_stderr=False).invoke(gateway.gateway_token, ["--host", f"{_HOST}/", *args])
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
