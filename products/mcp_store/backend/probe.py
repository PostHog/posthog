"""Probe a remote MCP server end-to-end, up to (but not through) the OAuth consent screen.

Verifies that a catalog entry actually works before it gets activated: speaks the
MCP initialize handshake, classifies the server's auth model, mints a real DCR
client when the provider supports one, and checks that the authorization endpoint
serves a plausible login page.

Deliberately dependency-light (pure HTTP plus the helpers in ``oauth.py`` — no
Django models, no database access) so it can run from management commands and
catalog sync jobs alike.
"""

import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlencode, urljoin

from django.conf import settings

import requests
import structlog

from posthog.security.pinned_requests import SSRFBlockedError, pinned_request

from .oauth import (
    TIMEOUT,
    discover_oauth_metadata,
    generate_pkce,
    oauth_resource,
    register_dcr_client,
    requested_oauth_scopes,
)

logger = structlog.get_logger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_AUTHORIZE_REDIRECTS = 3

_AUTH_REQUIRED_STATUSES = (401, 403)
# A rendered login/consent page, or an immediate redirect into a hosted login flow.
_AUTHORIZE_ALIVE_STATUSES = (200, 302, 303)
_AUTHORIZE_FOLLOWABLE_STATUSES = (301, 307, 308)

AuthFlavor = Literal["open", "oauth_dcr", "oauth_shared", "api_key_or_unknown"]
_InitializeOutcome = Literal["open", "auth_required", "failed"]


@dataclass
class ProbeResult:
    reachable: bool = False
    speaks_mcp: bool = False
    server_info: dict | None = None
    auth_flavor: AuthFlavor = "api_key_or_unknown"
    oauth_metadata: dict | None = None
    dcr_registered: bool = False
    authorize_endpoint_ok: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def passed_activation_gate(self) -> bool:
        """Whether the probe outcome is strong enough to auto-activate a catalog entry."""
        if not (self.reachable and self.speaks_mcp):
            return False
        if self.auth_flavor == "oauth_dcr":
            return self.dcr_registered and self.authorize_endpoint_ok
        # oauth_shared needs manually provisioned shared client credentials, and
        # api_key_or_unknown carries no MCP evidence (a bare 401/403 could be any
        # protected endpoint) — neither may auto-activate.
        return self.auth_flavor == "open"


def probe_mcp_server(url: str) -> ProbeResult:
    """Probe ``url`` and return a :class:`ProbeResult`. Never raises."""
    result = ProbeResult()
    try:
        _run_probe(url, result)
    except Exception as exc:
        logger.exception("MCP server probe failed unexpectedly", server_url=url)
        result.errors.append(f"Probe aborted unexpectedly: {exc}")
    return result


def _run_probe(url: str, result: ProbeResult) -> None:
    outcome = _probe_initialize(url, result)
    if outcome == "failed":
        return

    metadata = _discover_metadata(url, result, auth_required=outcome == "auth_required")
    if metadata is None:
        if outcome == "open":
            result.auth_flavor = "open"
            return
        # A bare 401/403 is indistinguishable from any auth-walled endpoint, so
        # without OAuth metadata there is no evidence the server speaks MCP.
        result.auth_flavor = "api_key_or_unknown"
        result.errors.append(
            "Initialize was rejected and no OAuth metadata was discovered; cannot verify the server speaks MCP"
        )
        return

    # OAuth protected-resource metadata (RFC 9728) served for this URL is the
    # strongest MCP evidence available without credentials.
    result.speaks_mcp = True
    result.oauth_metadata = metadata
    client_id = _register_probe_client(metadata, result)
    if client_id is None:
        result.auth_flavor = "oauth_shared"
        return

    result.auth_flavor = "oauth_dcr"
    result.dcr_registered = True
    result.authorize_endpoint_ok = _check_authorize_endpoint(metadata, client_id, result)


def _probe_redirect_uri() -> str:
    # Mirrors the redirect URI the install flow registers (views._get_oauth_redirect_uri).
    return f"{settings.SITE_URL}/api/mcp_store/oauth_redirect/"


def _probe_initialize(url: str, result: ProbeResult) -> _InitializeOutcome:
    """Run the MCP initialize handshake.

    "open" means the server completed the handshake without auth (MCP verified);
    "auth_required" means it rejected the call with 401/403, which proves nothing
    about MCP until OAuth discovery corroborates it; "failed" means it did not
    respond like an MCP server.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "posthog-mcp-store-probe", "version": "1.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        response = pinned_request("POST", url, json=payload, headers=headers, timeout=TIMEOUT)
    except SSRFBlockedError as exc:
        result.errors.append(f"MCP server URL blocked by SSRF protection: {exc}")
        return "failed"
    except requests.RequestException as exc:
        result.errors.append(f"MCP initialize request failed: {exc}")
        return "failed"

    result.reachable = True
    if 300 <= response.status_code < 400:
        # A redirect target never went through SSRF validation, and a catalog URL
        # should point at the MCP endpoint itself — refuse rather than follow.
        result.errors.append(f"MCP initialize returned a redirect (HTTP {response.status_code}); not following it")
        return "failed"
    if response.status_code in _AUTH_REQUIRED_STATUSES:
        return "auth_required"
    if response.status_code != 200:
        result.errors.append(f"MCP initialize returned HTTP {response.status_code}")
        return "failed"

    rpc_result = _jsonrpc_result(response)
    if rpc_result is None:
        content_type = response.headers.get("Content-Type", "")
        result.errors.append(
            f"MCP initialize returned HTTP 200 without a JSON-RPC result (content-type: {content_type})"
        )
        return "failed"

    result.speaks_mcp = True
    server_info = rpc_result.get("serverInfo")
    if isinstance(server_info, dict):
        result.server_info = server_info
    return "open"


def _iter_sse_data(body: str) -> Iterator[str]:
    """Yield the ``data:`` payload of each SSE event, joining multi-line data frames."""
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
        elif not line.strip() and data_lines:
            yield "\n".join(data_lines)
            data_lines = []
    if data_lines:
        yield "\n".join(data_lines)


def _jsonrpc_result(response: requests.Response) -> dict | None:
    """Extract the JSON-RPC ``result`` object from a JSON or SSE-wrapped initialize response.

    MCP streamable HTTP servers may answer directly with JSON or over a
    ``text/event-stream`` frame; sniff the body as a fallback because some
    proxies mislabel the stream (same approach as ``tools._parse_jsonrpc_response``).
    """
    content_type = response.headers.get("Content-Type", "").lower()
    body = response.text
    candidates: Iterator[str]
    if "text/event-stream" in content_type or body.lstrip().startswith(("event:", "data:", ":")):
        candidates = _iter_sse_data(body)
    else:
        candidates = iter([body])

    for candidate in candidates:
        try:
            message = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            continue
        rpc_result = message.get("result")
        if isinstance(rpc_result, dict):
            return rpc_result
    return None


def _discover_metadata(url: str, result: ProbeResult, *, auth_required: bool) -> dict | None:
    try:
        return discover_oauth_metadata(url)
    except Exception as exc:
        # Open servers legitimately have no discoverable OAuth metadata; only note
        # the failure when the server demanded auth we now can't classify.
        if auth_required:
            result.errors.append(f"OAuth discovery failed: {exc}")
        return None


def _register_probe_client(metadata: dict, result: ProbeResult) -> str | None:
    """Mint a real DCR client. Returns its client_id, or None when DCR is unavailable."""
    if not metadata.get("registration_endpoint"):
        return None
    try:
        client_id, _client_secret, _auth_method = register_dcr_client(metadata, _probe_redirect_uri())
    except ValueError as exc:
        # Mirrors views._register_dcr_client_or_raise: ValueError means DCR isn't supported.
        result.errors.append(f"Dynamic Client Registration not supported: {exc}")
        return None
    except Exception as exc:
        result.errors.append(f"Dynamic Client Registration failed: {exc}")
        return None
    return client_id


def _build_authorize_url(metadata: dict, client_id: str) -> str | None:
    authorization_endpoint = metadata.get("authorization_endpoint")
    if not isinstance(authorization_endpoint, str) or not authorization_endpoint:
        return None

    code_challenge = generate_pkce().code_challenge
    query_params = {
        "client_id": client_id,
        "redirect_uri": _probe_redirect_uri(),
        "response_type": "code",
        "state": secrets.token_urlsafe(16),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if scopes := requested_oauth_scopes(metadata):
        query_params["scope"] = " ".join(scopes)
    if resource := oauth_resource(metadata):
        query_params["resource"] = resource
    return f"{authorization_endpoint}?{urlencode(query_params)}"


def _check_authorize_endpoint(metadata: dict, client_id: str, result: ProbeResult) -> bool:
    """GET the authorization URL and report whether it serves a plausible login/consent page."""
    authorize_url = _build_authorize_url(metadata, client_id)
    if authorize_url is None:
        result.errors.append("OAuth metadata is missing authorization_endpoint")
        return False

    current_url = authorize_url
    for _hop in range(MAX_AUTHORIZE_REDIRECTS + 1):
        try:
            response = pinned_request("GET", current_url, timeout=TIMEOUT)
        except SSRFBlockedError as exc:
            result.errors.append(f"Authorization endpoint blocked by SSRF protection: {exc}")
            return False
        except requests.RequestException as exc:
            result.errors.append(f"Authorization endpoint request failed: {exc}")
            return False

        if response.status_code in _AUTHORIZE_ALIVE_STATUSES:
            return True
        location = response.headers.get("Location", "")
        if response.status_code in _AUTHORIZE_FOLLOWABLE_STATUSES and location:
            current_url = urljoin(current_url, location)
            continue
        result.errors.append(f"Authorization endpoint returned HTTP {response.status_code}")
        return False

    result.errors.append(f"Authorization endpoint redirected more than {MAX_AUTHORIZE_REDIRECTS} times")
    return False
