from __future__ import annotations

import json
import stat
import time
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

import requests
from click.testing import CliRunner
from hogli_commands import posthog_auth, posthog_auth_cli

_HOST = "https://us.posthog.com"
_SCOPE = "engineering_analytics:read"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path) -> Iterator[Path]:
    """Never touch the developer's real ~/.config/posthog while testing."""
    with patch.object(posthog_auth, "_CACHE_ROOT", tmp_path / "oauth"):
        yield tmp_path / "oauth"


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in posthog_auth.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _credential(**overrides: Any) -> posthog_auth.Credential:
    fields: dict[str, Any] = {
        "host": _HOST,
        "client_id": "client-abc",
        "access_token": "pha_cached",
        "refresh_token": "phr_cached",
        "expires_at": time.time() + 3600,
        "granted": (_SCOPE,),
        "registered": (_SCOPE,),
    }
    return posthog_auth.Credential(**{**fields, **overrides})


class _Poster:
    """Replaces `requests.post`, recording each call and replaying canned responses per endpoint."""

    def __init__(self, **bodies: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._bodies = bodies

    def __call__(self, url: str, *, json: Any = None, data: Any = None, timeout: float) -> Any:
        self.calls.append({"url": url, "json": json, "data": data})
        endpoint = "register" if url.rstrip("/").endswith("register") else "token"
        status, body = self._bodies.get(endpoint, (200, {}))
        return _Response(status, body)

    def body_for(self, endpoint: str) -> dict[str, Any]:
        call = next(call for call in self.calls if call["url"].rstrip("/").endswith(endpoint))
        return call["json"] or call["data"] or {}


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


# --- env-var ladder: the path CI and unattended agents take -------------------------------------


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"POSTHOG_PERSONAL_API_KEY": "phx_direct"}, "phx_direct"),
        ({"POSTHOG_AUTH_HEADER": "Bearer phx_from_header"}, "phx_from_header"),
        ({"POSTHOG_AUTH_HEADER": "phx_bare_header"}, "phx_bare_header"),
        ({"POSTHOG_PERSONAL_API_KEY": "phx_wins", "POSTHOG_AUTH_HEADER": "Bearer phx_loses"}, "phx_wins"),
    ],
)
def test_environment_key_ladder(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str) -> None:
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == expected


def test_environment_key_wins_over_a_cached_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit key is an override; a stale cache silently outranking it would be unexplainable."""
    posthog_auth.save(_credential())
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_explicit")
    assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "phx_explicit"


# --- cache: the path every command after the first login takes ----------------------------------


def test_a_fresh_cached_credential_is_reused_without_any_request() -> None:
    posthog_auth.save(_credential())
    with patch.object(posthog_auth.requests, "post", side_effect=AssertionError("must not call the network")):
        assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "pha_cached"


def test_the_credential_file_is_owner_only() -> None:
    """It holds a bearer token, so a default-umask 0644 would expose it to every local process."""
    posthog_auth.save(_credential())
    path = posthog_auth._cache_path(_HOST)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_hosts_are_cached_separately() -> None:
    """us and eu are different accounts; one overwriting the other would log you out sideways."""
    posthog_auth.save(_credential())
    posthog_auth.save(_credential(host="https://eu.posthog.com", access_token="pha_eu"))
    assert posthog_auth.load(_HOST) is not None
    assert posthog_auth.load(_HOST).access_token == "pha_cached"  # type: ignore[union-attr]
    assert posthog_auth.load("https://eu.posthog.com").access_token == "pha_eu"  # type: ignore[union-attr]


@pytest.mark.parametrize("content", ["not json at all", '{"host": "x"}'])
def test_an_unreadable_cache_reads_as_absent(cache_dir: Path, content: str) -> None:
    """Derived state: a corrupt or older-shaped file must send you to a login, never crash a command."""
    path = posthog_auth._cache_path(_HOST)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    assert posthog_auth.load(_HOST) is None


def test_an_expired_credential_refreshes_and_persists_the_new_tokens() -> None:
    posthog_auth.save(_credential(access_token="pha_old", expires_at=time.time() - 10))
    poster = _Poster(token=(200, {"access_token": "pha_new", "refresh_token": "phr_new", "expires_in": 3600}))
    with patch.object(posthog_auth.requests, "post", poster):
        assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "pha_new"
    assert poster.body_for("token")["grant_type"] == "refresh_token"
    stored = posthog_auth.load(_HOST)
    assert stored is not None and stored.access_token == "pha_new" and stored.refresh_token == "phr_new"


def test_a_refresh_that_reissues_no_refresh_token_keeps_the_working_one() -> None:
    """Rotation is optional. Dropping the old token on a non-rotating server would force a
    re-login on every expiry."""
    posthog_auth.save(_credential(expires_at=time.time() - 10))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(200, {"access_token": "pha_new"}))):
        posthog_auth.token(scopes=[_SCOPE], host=_HOST)
    stored = posthog_auth.load(_HOST)
    assert stored is not None and stored.refresh_token == "phr_cached"


def test_a_credential_expiring_within_the_margin_refreshes_early() -> None:
    """A token valid for another second would otherwise be handed to a request that outlives it."""
    posthog_auth.save(_credential(access_token="pha_old", expires_at=time.time() + 30))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(200, {"access_token": "pha_new"}))):
        assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "pha_new"


# --- non-interactive callers: agents and pipes ---------------------------------------------------


def test_a_non_interactive_caller_never_opens_a_browser() -> None:
    """Agents run this piped. Blocking five minutes on a consent screen nobody can see is worse
    than exiting with a code the caller can branch on."""
    with patch.object(posthog_auth.webbrowser, "open", side_effect=AssertionError("must not open")):
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)
    assert caught.value.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert "auth:posthog:login" in caught.value.message


def test_a_dead_refresh_token_reports_not_configured_rather_than_the_http_error() -> None:
    """The caller's next step is a login either way, so it should reach the same branch as no cache."""
    posthog_auth.save(_credential(expires_at=time.time() - 10))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(400, {"error": "invalid_grant"}))):
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)
    assert caught.value.exit_code == posthog_auth.EXIT_NOT_CONFIGURED


# --- scopes: the reason this is general rather than one command's helper -------------------------


def test_a_credential_short_of_the_requested_scope_does_not_satisfy_it() -> None:
    """Returning it would send a request that 403s on a scope check, reported as a permission
    problem the user cannot act on."""
    posthog_auth.save(_credential(granted=("query:read",), registered=("query:read",)))
    with pytest.raises(posthog_auth.AuthError):
        posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)


def test_a_login_for_a_new_scope_keeps_the_scopes_already_registered() -> None:
    """Two commands wanting different scopes must not take turns un-authorizing each other."""
    posthog_auth.save(_credential(granted=("query:read",), registered=("query:read",)))
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": f"query:read {_SCOPE}"}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert set(poster.body_for("register")["scope"].split()) == {"query:read", _SCOPE}


def test_a_login_reuses_the_registered_client_when_its_ceiling_already_covers_the_scopes() -> None:
    """Re-registering per login would litter the account's connected-apps list with duplicates."""
    posthog_auth.save(_credential())
    poster = _Poster(token=(200, {"access_token": "pha_new", "expires_in": 3600}))
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        credential = posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert not [call for call in poster.calls if call["url"].rstrip("/").endswith("register")]
    assert credential.client_id == "client-abc"


def test_a_login_that_did_not_get_every_scope_asked_for_says_so() -> None:
    """The server strips a scope a self-registering client may not have and only 400s when nothing
    survives. Returning quietly would surface later as an unactionable 403 on a scope check."""
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "scope": _SCOPE}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.login(scopes=[_SCOPE, "llm_gateway:read"], host=_HOST)
    assert "llm_gateway:read" in caught.value.message
    # The partial grant still works for what it does cover, so it is kept rather than thrown away.
    assert (posthog_auth.load(_HOST) or _credential()).granted == (_SCOPE,)


def test_the_granted_scopes_come_from_the_server_not_the_request() -> None:
    """PostHog widens some grants. Storing what we asked for would re-authorize forever, or claim
    a scope the token does not carry."""
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "scope": f"{_SCOPE} engineering_analytics:write"}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        credential = posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert credential.granted == (_SCOPE, "engineering_analytics:write")


# --- the browser handoff ------------------------------------------------------------------------


def _fake_browser(query: dict[str, list[str]] | None = None) -> Any:
    """Stand in for the browser: answer the pending authorization with a matching redirect."""

    def collect(self: Any, url: str, *, state: str, open_browser: bool) -> str:
        return posthog_auth._code_from(query or {"code": ["auth-code"], "state": [state]}, state=state)

    return patch.object(posthog_auth._CallbackServer, "collect", collect)


def test_the_registered_redirect_is_portless_loopback_and_the_request_carries_the_bound_port() -> None:
    """RFC 8252 §7.3 exempts a loopback port from matching, which is the whole reason an ephemeral
    port works against one registration. A registered port would break the next login that got a
    different one."""
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert poster.body_for("register")["redirect_uris"] == ["http://127.0.0.1/callback"]
    sent = poster.body_for("token")["redirect_uri"]
    assert sent.startswith("http://127.0.0.1:") and sent.endswith("/callback")
    assert int(sent.rsplit(":", 1)[1].split("/")[0]) > 0


def test_the_code_exchange_proves_possession_of_the_pkce_verifier() -> None:
    """A public client has no secret, so the verifier is the only thing binding the code to us."""
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    body = poster.body_for("token")
    assert body["grant_type"] == "authorization_code" and body["code_verifier"]
    assert poster.body_for("register")["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize(
    "query, expected",
    [
        ({"code": ["c"], "state": ["mismatched"]}, "wrong state"),
        ({"error": ["access_denied"], "state": ["expected"]}, "refused"),
        ({"state": ["expected"]}, "no authorization code"),
    ],
)
def test_a_redirect_that_does_not_answer_our_request_is_rejected(query: dict[str, list[str]], expected: str) -> None:
    """Without the state check the flow would accept a code from a request we never made."""
    with pytest.raises(posthog_auth.AuthError) as caught:
        posthog_auth._code_from(query, state="expected")
    assert expected in caught.value.message


def test_the_callback_listener_ignores_paths_that_are_not_the_redirect() -> None:
    """A browser also fetches /favicon.ico; treating any request as the callback would end the
    wait on the wrong one."""
    with posthog_auth._CallbackServer() as server:
        threading.Thread(
            target=lambda: (
                requests.get(f"http://127.0.0.1:{_port_of(server)}/favicon.ico", timeout=5),
                requests.get(f"{server.redirect_uri}?code=real&state=s", timeout=5),
            ),
            daemon=True,
        ).start()
        assert server.collect("http://example.invalid", state="s", open_browser=False) == "real"


def test_a_browser_that_blocks_until_it_exits_does_not_deadlock_the_listener() -> None:
    """`webbrowser.open` blocks for a terminal-mode browser (and anything $BROWSER points at that
    doesn't detach). Opening in the foreground would wait on the redirect only this listener can
    serve, so the login would hang until its timeout."""
    released = threading.Event()

    def blocking_open(url: str) -> bool:
        # What a real blocking browser does: fetch the redirect, then stay open.
        threading.Thread(
            target=lambda: requests.get(f"{urls['redirect']}?code=blocked&state=s", timeout=5), daemon=True
        ).start()
        released.wait(10)
        return True

    with posthog_auth._CallbackServer() as server:
        urls = {"redirect": server.redirect_uri}
        with patch.object(posthog_auth.webbrowser, "open", blocking_open):
            assert server.collect("http://example.invalid", state="s", open_browser=True) == "blocked"
    released.set()


def _port_of(server: posthog_auth._CallbackServer) -> int:
    return int(server.redirect_uri.rsplit(":", 1)[1].split("/")[0])


# --- the CLI surface ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [posthog_auth_cli.posthog_login, posthog_auth_cli.posthog_status, posthog_auth_cli.posthog_logout],
)
def test_help_works_with_nothing_configured(runner: CliRunner, command: Any) -> None:
    """tools/hogli/tests/test_cli.py asserts --help exits 0 for every manifest `click:` entry."""
    result = runner.invoke(command, ["--help"])
    assert result.exit_code == 0 and "Usage:" in result.output


def test_status_exits_not_configured_when_nothing_is_cached(runner: CliRunner) -> None:
    """So a script can gate on the exit code instead of grepping the table."""
    result = runner.invoke(posthog_auth_cli.posthog_status, [])
    assert result.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert "auth:posthog:login" in result.output


def test_status_never_prints_the_token(runner: CliRunner) -> None:
    """It is run to diagnose auth, often with a terminal being shared or logged."""
    posthog_auth.save(_credential())
    for argv in ([], ["--json"]):
        result = runner.invoke(posthog_auth_cli.posthog_status, argv)
        assert result.exit_code == 0
        assert "pha_cached" not in result.output and "phr_cached" not in result.output
    assert json.loads(result.output)["credential"]["access_token"] == "<redacted>"


def test_status_warns_when_an_environment_key_outranks_the_cached_credential(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a stale exported key makes a fresh login look like it did nothing."""
    posthog_auth.save(_credential())
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_exported")
    result = runner.invoke(posthog_auth_cli.posthog_status, [])
    assert result.exit_code == 0 and "wins over" in result.output


def test_logout_reports_whether_there_was_anything_to_forget(runner: CliRunner) -> None:
    posthog_auth.save(_credential())
    assert "Forgot" in runner.invoke(posthog_auth_cli.posthog_logout, []).output
    assert "No cached credential" in runner.invoke(posthog_auth_cli.posthog_logout, []).output
