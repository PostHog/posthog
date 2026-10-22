from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlparse

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli_commands import gateway

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
    response = MagicMock(status_code=status_code, text=str(payload))
    response.json.return_value = payload
    return response


def _run(post: MagicMock, *args: str) -> tuple[Any, dict[str, list[str]]]:
    approval: dict[str, list[str]] = {}

    def approve(url_for_port: Any, *, state: str) -> str:
        approval.update(parse_qs(urlparse(url_for_port(54321)).query))
        assert approval["cli_state"] == [state]
        return "one-time-code"

    with (
        patch.object(gateway.posthog_auth, "approve_in_browser", approve),
        patch.object(gateway.requests, "post", post),
    ):
        result = CliRunner(mix_stderr=False).invoke(gateway.gateway_token, ["--host", _HOST, *args])
    return result, approval


def test_the_exchanged_verifier_matches_the_approved_challenge_and_stdout_holds_only_the_token() -> None:
    post = MagicMock(return_value=_response(201, _MINTED))

    result, approval = _run(post)

    assert result.exit_code == 0, result.output
    assert result.stdout == "phe_minted\n"
    assert approval["cli_port"] == ["54321"]
    sent = post.call_args.kwargs["json"]
    assert sent["code"] == "one-time-code"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=")
    assert approval["cli_challenge"] == [challenge.decode()]


def test_a_refused_exchange_reports_the_server_detail_and_prints_no_token() -> None:
    post = MagicMock(return_value=_response(400, {"code": "invalid_code", "detail": "code is expired or used"}))

    result, _ = _run(post)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "code is expired or used" in result.stderr
