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
    # Redirect the cache so no test reads or writes the developer's real ~/.config/posthog.
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


def _endpoint_of(url: str) -> str:
    return "register" if url.rstrip("/").endswith("register") else "token"


def _port_from(uri: str) -> int:
    return int(uri.rsplit(":", 1)[1].split("/")[0])


# Stands in for `requests.post`, recording every call and replaying a canned response per endpoint,
# so a test can assert both on what was sent and on which endpoints were reached at all.
class _Poster:
    def __init__(self, **bodies: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._bodies = bodies

    def __call__(self, url: str, *, json: Any = None, data: Any = None, timeout: float) -> Any:
        self.calls.append({"url": url, "json": json, "data": data})
        status, body = self._bodies.get(_endpoint_of(url), (200, {}))
        return _Response(status, body)

    def body_for(self, endpoint: str) -> dict[str, Any]:
        call = next(call for call in self.calls if _endpoint_of(call["url"]) == endpoint)
        return call["json"] or call["data"] or {}

    def reached(self, endpoint: str) -> bool:
        return any(_endpoint_of(call["url"]) == endpoint for call in self.calls)


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        # A None payload models a response that carries no JSON at all.
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


def _fake_browser(query: dict[str, list[str]] | None = None) -> Any:
    # Stands in for the browser, answering the pending authorization with a matching redirect.
    def collect(self: Any, url: str, *, state: str, open_browser: bool) -> str:
        return posthog_auth._code_from(query or {"code": ["auth-code"], "state": [state]}, state=state)

    return patch.object(posthog_auth._CallbackServer, "collect", collect)


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


@pytest.mark.parametrize("raw", ['"Bearer phx_quoted"', "'Bearer phx_quoted'", '"phx_quoted"', "Bearer phx_quoted"])
def test_a_quoted_environment_value_still_yields_the_bare_key(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    # hogli's dotenv loader assigns the raw value, so a quoted `.env.local` line arrives with its
    # quotes attached, the `Bearer ` prefix stops matching, and the key goes out to PostHog quoted.
    monkeypatch.setenv("POSTHOG_AUTH_HEADER", raw)
    assert posthog_auth.key_from_env() == "phx_quoted"


@pytest.mark.parametrize(
    "env, expected_source",
    [
        ({"POSTHOG_PERSONAL_API_KEY": "phx_a"}, "POSTHOG_PERSONAL_API_KEY"),
        ({"POSTHOG_AUTH_HEADER": "Bearer phx_b"}, "POSTHOG_AUTH_HEADER"),
        # Whitespace-only does not count as set. A second scan using bare truthiness reported this
        # as the source while the key actually came from the other variable.
        ({"POSTHOG_PERSONAL_API_KEY": "   ", "POSTHOG_AUTH_HEADER": "phx_b"}, "POSTHOG_AUTH_HEADER"),
    ],
)
def test_the_reported_environment_source_is_the_one_the_key_came_from(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected_source: str
) -> None:
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    found = posthog_auth.key_in_env()
    assert found is not None and found[0] == expected_source


def test_environment_key_wins_over_a_cached_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    # An explicit key is an override, so a stale cache silently outranking it would be unexplainable.
    posthog_auth.save(_credential())
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_explicit")
    assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "phx_explicit"


# --- cache: the path every command after the first login takes ----------------------------------


def test_a_fresh_cached_credential_is_reused_without_any_request() -> None:
    posthog_auth.save(_credential())
    with patch.object(posthog_auth.requests, "post", side_effect=AssertionError("must not call the network")):
        assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "pha_cached"


def test_the_credential_file_is_owner_only() -> None:
    posthog_auth.save(_credential())
    path = posthog_auth._cache_path(_HOST)
    # The file holds a bearer token, so a default-umask 0644 would expose it to every local process.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_hosts_are_cached_separately() -> None:
    # us and eu are different accounts, so one overwriting the other would log you out sideways.
    posthog_auth.save(_credential())
    posthog_auth.save(_credential(host="https://eu.posthog.com", access_token="pha_eu"))
    us, eu = posthog_auth.load(_HOST), posthog_auth.load("https://eu.posthog.com")
    assert us is not None and us.access_token == "pha_cached"
    assert eu is not None and eu.access_token == "pha_eu"


@pytest.mark.parametrize("content", ["not json at all", '{"host": "x"}'])
def test_an_unreadable_cache_reads_as_absent(content: str) -> None:
    # The cache is derived state, so a corrupt or older-shaped file must send you to a login rather
    # than crash the command that asked for a token.
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
    # Rotation is optional, so dropping the old token against a non-rotating server would force a
    # re-login on every expiry.
    posthog_auth.save(_credential(expires_at=time.time() - 10))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(200, {"access_token": "pha_new"}))):
        posthog_auth.token(scopes=[_SCOPE], host=_HOST)
    stored = posthog_auth.load(_HOST)
    assert stored is not None and stored.refresh_token == "phr_cached"


def test_a_credential_expiring_within_the_margin_refreshes_early() -> None:
    # A token with seconds left would otherwise be handed to a request that outlives it.
    posthog_auth.save(_credential(access_token="pha_old", expires_at=time.time() + 30))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(200, {"access_token": "pha_new"}))):
        assert posthog_auth.token(scopes=[_SCOPE], host=_HOST) == "pha_new"


# --- non-interactive callers: agents and pipes ---------------------------------------------------


def test_a_non_interactive_caller_never_opens_a_browser() -> None:
    # Agents run this piped. Blocking five minutes on a consent screen nobody can see is worse than
    # exiting with a code the caller can branch on.
    with patch.object(posthog_auth.webbrowser, "open", side_effect=AssertionError("must not open")):
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)
    assert caught.value.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert "auth:posthog:login" in caught.value.message


def test_a_dead_refresh_token_reports_not_configured_rather_than_the_http_error() -> None:
    # The caller's next step is a login either way, so a spent grant must reach the same branch as no
    # cached credential at all.
    posthog_auth.save(_credential(expires_at=time.time() - 10))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(400, {"error": "invalid_grant"}))):
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)
    assert caught.value.exit_code == posthog_auth.EXIT_NOT_CONFIGURED


@pytest.mark.parametrize("payload", [["gateway", "down"], None])
def test_a_non_object_error_body_reports_the_status_instead_of_crashing(payload: Any) -> None:
    # A proxy or load balancer can answer with valid JSON that is not an object, or with no JSON at
    # all. Reading `detail` off a list raises AttributeError, which escapes the AuthError handling
    # every caller relies on.
    posthog_auth.save(_credential(expires_at=time.time() - 10))
    with patch.object(posthog_auth.requests, "post", _Poster(token=(502, payload))):
        with pytest.raises(posthog_auth.AuthError) as caught:
            posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)
    assert caught.value.exit_code == posthog_auth.EXIT_NOT_CONFIGURED


# --- scopes: the reason this is general rather than one command's helper -------------------------


def test_a_credential_short_of_the_requested_scope_does_not_satisfy_it() -> None:
    # Returning it would send a request that 403s on a scope check, surfacing as a permission problem
    # the user cannot act on.
    posthog_auth.save(_credential(granted=("query:read",), registered=("query:read",)))
    with pytest.raises(posthog_auth.AuthError):
        posthog_auth.token(scopes=[_SCOPE], host=_HOST, interactive=False)


def test_a_login_for_a_new_scope_keeps_the_scopes_already_registered() -> None:
    # Two commands wanting different scopes must not take turns un-authorizing each other.
    posthog_auth.save(_credential(granted=("query:read",), registered=("query:read",)))
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": f"query:read {_SCOPE}"}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert set(poster.body_for("register")["scope"].split()) == {"query:read", _SCOPE}


def test_a_login_reuses_the_registered_client_when_its_ceiling_already_covers_the_scopes() -> None:
    # Re-registering per login would litter the account's connected-apps list with duplicates.
    posthog_auth.save(_credential())
    poster = _Poster(token=(200, {"access_token": "pha_new", "expires_in": 3600}))
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        credential = posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert not poster.reached("register")
    assert credential.client_id == "client-abc"


def test_a_scope_the_server_refuses_is_reported_before_the_browser_opens() -> None:
    # The server strips a scope a self-registering client may not have and only 400s when nothing
    # survives. Consenting first would spend the user's click to mint a token missing what was asked
    # for, and the failure would land after the click as an unactionable 403.
    poster = _Poster(register=(200, {"client_id": "client-new", "scope": _SCOPE}))
    with patch.object(posthog_auth.requests, "post", poster):
        with patch.object(posthog_auth.webbrowser, "open", side_effect=AssertionError("must not open")):
            with pytest.raises(posthog_auth.AuthError) as caught:
                posthog_auth.login(scopes=[_SCOPE, "llm_gateway:read"], host=_HOST)
    assert "llm_gateway:read" in caught.value.message
    assert not poster.reached("token")


def test_retrying_a_refused_scope_mints_no_grant_and_leaves_the_cache_alone() -> None:
    # Refusing after the exchange rather than before it would leave a live access and refresh grant
    # behind on every attempt, each needing its own revocation, and overwrite a working credential.
    posthog_auth.save(_credential())
    poster = _Poster(register=(200, {"client_id": "client-new", "scope": _SCOPE}))
    with patch.object(posthog_auth.requests, "post", poster):
        with patch.object(posthog_auth.webbrowser, "open", side_effect=AssertionError("must not open")):
            for _ in range(3):
                with pytest.raises(posthog_auth.AuthError):
                    posthog_auth.login(scopes=[_SCOPE, "llm_gateway:read"], host=_HOST)
    assert not poster.reached("token")
    survivor = posthog_auth.load(_HOST)
    assert survivor is not None and survivor.access_token == "pha_cached"


def test_the_granted_scopes_come_from_the_server_not_the_request() -> None:
    # PostHog widens some grants. Storing what we asked for would re-authorize forever, or claim a
    # scope the token does not carry.
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "scope": f"{_SCOPE} engineering_analytics:write"}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        credential = posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert credential.granted == (_SCOPE, "engineering_analytics:write")


def test_a_token_response_without_a_scope_field_records_what_was_asked_for() -> None:
    # RFC 6749 §5.1 omits `scope` when it matches the request, so an omission means the whole ask was
    # granted. Recording nothing would read as "scopes unknown" and satisfy every later request.
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        credential = posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert credential.granted == (_SCOPE,)


# --- the browser handoff ------------------------------------------------------------------------


def test_the_registered_redirect_is_portless_loopback_and_the_request_carries_the_bound_port() -> None:
    # RFC 8252 §7.3 exempts a loopback port from redirect matching, which is the whole reason an
    # ephemeral port works against one registration. A registered port would break the next login
    # that got a different one.
    poster = _Poster(
        register=(200, {"client_id": "client-new", "scope": _SCOPE}),
        token=(200, {"access_token": "pha_new", "expires_in": 3600}),
    )
    with patch.object(posthog_auth.requests, "post", poster), _fake_browser():
        posthog_auth.login(scopes=[_SCOPE], host=_HOST)
    assert poster.body_for("register")["redirect_uris"] == ["http://127.0.0.1/callback"]
    sent = poster.body_for("token")["redirect_uri"]
    assert sent.startswith("http://127.0.0.1:") and sent.endswith("/callback")
    assert _port_from(sent) > 0


def test_the_code_exchange_proves_possession_of_the_pkce_verifier() -> None:
    # A public client has no secret, so the verifier is the only thing binding the code to us.
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
    # Without the state check the flow would accept a code from a request we never made.
    with pytest.raises(posthog_auth.AuthError) as caught:
        posthog_auth._code_from(query, state="expected")
    assert expected in caught.value.message


def test_the_callback_listener_ignores_paths_that_are_not_the_redirect() -> None:
    # A browser also fetches /favicon.ico, so treating any request as the callback would end the wait
    # on the wrong one.
    with posthog_auth._CallbackServer() as server:
        threading.Thread(
            target=lambda: (
                requests.get(f"http://127.0.0.1:{_port_from(server.redirect_uri)}/favicon.ico", timeout=5),
                requests.get(f"{server.redirect_uri}?code=real&state=s", timeout=5),
            ),
            daemon=True,
        ).start()
        assert server.collect("http://example.invalid", state="s", open_browser=False) == "real"


def test_a_browser_that_blocks_until_it_exits_does_not_deadlock_the_listener() -> None:
    # `webbrowser.open` blocks for a terminal-mode browser, and for anything $BROWSER points at that
    # doesn't detach. Opened in the foreground it would wait on the redirect only this listener can
    # serve, so the login would hang until its timeout.
    released = threading.Event()
    with posthog_auth._CallbackServer() as server:

        def blocking_open(url: str) -> bool:
            # What a real blocking browser does: fetch the redirect, then stay open.
            threading.Thread(
                target=lambda: requests.get(f"{server.redirect_uri}?code=blocked&state=s", timeout=5), daemon=True
            ).start()
            released.wait(10)
            return True

        with patch.object(posthog_auth.webbrowser, "open", blocking_open):
            assert server.collect("http://example.invalid", state="s", open_browser=True) == "blocked"
    released.set()


# --- the CLI surface ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [posthog_auth_cli.posthog_login, posthog_auth_cli.posthog_status, posthog_auth_cli.posthog_logout],
)
def test_help_works_with_nothing_configured(runner: CliRunner, command: Any) -> None:
    # tools/hogli/tests/test_cli.py asserts --help exits 0 for every manifest `click:` entry.
    result = runner.invoke(command, ["--help"])
    assert result.exit_code == 0 and "Usage:" in result.output


def test_status_exits_not_configured_when_nothing_is_cached(runner: CliRunner) -> None:
    # So a script can gate on the exit code instead of grepping the table.
    result = runner.invoke(posthog_auth_cli.posthog_status, [])
    assert result.exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert "auth:posthog:login" in result.output


def test_status_reports_the_same_verdict_in_both_output_shapes(runner: CliRunner) -> None:
    # A script gating on the exit code must not read "configured" just because it asked for JSON.
    assert runner.invoke(posthog_auth_cli.posthog_status, []).exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    assert runner.invoke(posthog_auth_cli.posthog_status, ["--json"]).exit_code == posthog_auth.EXIT_NOT_CONFIGURED
    posthog_auth.save(_credential())
    assert runner.invoke(posthog_auth_cli.posthog_status, []).exit_code == 0
    assert runner.invoke(posthog_auth_cli.posthog_status, ["--json"]).exit_code == 0


# A token runs for days, so reporting only minutes prints "expires in 10079m" and leaves the reader
# dividing by hand. The absent case is here too because a server that issues no `expires_in` would
# otherwise reach the arithmetic with None and crash the whole status table.
@pytest.mark.parametrize(
    "seconds,expected",
    [
        (7 * 86400, "expires in 7d"),
        (90, "expires in 1m"),
        (30, "expires in under a minute"),
        (-1, "expired"),
        (None, "no expiry reported"),
    ],
)
def test_status_reports_a_lifetime_at_a_readable_unit(
    monkeypatch: pytest.MonkeyPatch, seconds: int | None, expected: str
) -> None:
    # Pinned, because flooring an exact multiple drops a unit as soon as the clock moves.
    monkeypatch.setattr(posthog_auth_cli.time, "time", lambda: 1_700_000_000.0)
    assert posthog_auth_cli._lifetime(None if seconds is None else 1_700_000_000.0 + seconds) == expected


def test_status_never_prints_the_token(runner: CliRunner) -> None:
    # Status is run to diagnose auth, often with a terminal being shared or logged.
    posthog_auth.save(_credential())
    table = runner.invoke(posthog_auth_cli.posthog_status, [])
    rendered = runner.invoke(posthog_auth_cli.posthog_status, ["--json"])
    for result in (table, rendered):
        assert result.exit_code == 0
        assert "pha_cached" not in result.output and "phr_cached" not in result.output
    assert json.loads(rendered.output)["credential"]["access_token"] == "<redacted>"


def test_status_warns_when_an_environment_key_outranks_the_cached_credential(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Otherwise a stale exported key makes a fresh login look like it did nothing.
    posthog_auth.save(_credential())
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_exported")
    result = runner.invoke(posthog_auth_cli.posthog_status, [])
    assert result.exit_code == 0 and "wins over" in result.output


def test_logout_reports_whether_there_was_anything_to_forget(runner: CliRunner) -> None:
    posthog_auth.save(_credential())
    assert "Forgot" in runner.invoke(posthog_auth_cli.posthog_logout, []).output
    assert "No cached credential" in runner.invoke(posthog_auth_cli.posthog_logout, []).output
