from __future__ import annotations

import socket
import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)

COMMAND_TIMEOUT_SECONDS = 15
CANCEL_TIMEOUT_SECONDS = 10
# Refresh triggers a query.interrupt() + resume with a 30s SDK timeout on the
# agent-server, so we need more headroom than a plain command.
REFRESH_TIMEOUT_SECONDS = 45
# Follow-up delivery blocks until the agent has fully ingested the new turn,
# which can take a while. Must stay below the activity's start_to_close_timeout
# so a hung socket doesn't keep a worker thread blocked after Temporal has
# already abandoned the activity.
FOLLOWUP_TIMEOUT_SECONDS = 30 * 60  # 30 min

REFRESH_SESSION_METHOD = "_posthog/refresh_session"

ALLOWED_SANDBOX_SCHEMES = {"https"}
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

NO_ACTIVE_SESSION_ERROR = "No active session for this run"
CONTENT_BLOCK_STREAM_ERROR = "API Error: Content block not found"
CONTENT_BLOCK_STREAM_USER_ERROR = "The model response could not be completed. Please retry the task."
TURN_ENDED_WITHOUT_RESPONSE_ERROR = "[ede_diagnostic] result_type=user"


def is_retryable_agent_rpc_error(error: str) -> bool:
    return CONTENT_BLOCK_STREAM_ERROR in error or TURN_ENDED_WITHOUT_RESPONSE_ERROR in error


def user_facing_agent_error(error: str | None) -> str:
    if error and CONTENT_BLOCK_STREAM_ERROR in error:
        return CONTENT_BLOCK_STREAM_USER_ERROR
    return error or "Failed to send message to sandbox"


@dataclass
class CommandResult:
    success: bool
    status_code: int
    data: dict[str, Any] | None = None
    error: str | None = None
    retryable: bool = False
    # True only when the request body was fully sent and the agent is still
    # processing it (local read timeout). A 504 *response* (e.g. from the
    # Modal tunnel) leaves this False — there delivery is unknown.
    turn_in_flight: bool = False


def validate_sandbox_url(url: str) -> str | None:
    """Validate a sandbox URL against SSRF risks. Returns error string or None if valid."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    hostname = parsed.hostname
    if settings.DEBUG and parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1"}:
        return None

    if parsed.scheme not in ALLOWED_SANDBOX_SCHEMES:
        return f"Scheme {parsed.scheme!r} not allowed"

    if not hostname:
        return "No hostname in URL"

    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Cannot resolve hostname {hostname!r}"

    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        for blocked in BLOCKED_IP_RANGES:
            if ip in blocked:
                return f"Address {ip} is in blocked range"

    return None


def _get_sandbox_url_and_token(task_run: Any) -> tuple[str | None, str | None]:
    """Extract sandbox_url and connect_token from a TaskRun's state."""
    state = task_run.state or {}
    return state.get("sandbox_url"), state.get("sandbox_connect_token")


def _is_loopback_host(hostname: str | None) -> bool:
    """Whether ``hostname`` is a loopback address (``localhost``/``127.0.0.1``/``::1``)."""
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_hogland_sandbox_url(sandbox_url: str | None) -> bool:
    """Whether ``sandbox_url`` points at the configured hogland control plane.

    The hogland bearer is an account-wide credential, so it must only ever be
    attached to a request bound for the real hogland host. Gating on the URL host
    (not the mutable ``sandbox_backend`` state flag) means a forged run state
    cannot redirect the credential to an attacker-controlled server, even on the
    ``send_agent_command`` path whose SSRF check permits arbitrary public hosts.
    """
    hogland_api_url = getattr(settings, "HOGLAND_API_URL", None)
    if not sandbox_url or not hogland_api_url:
        return False
    try:
        target = urlparse(sandbox_url)
        expected = urlparse(hogland_api_url)
    except Exception:
        return False
    # A scheme-less HOGLAND_API_URL parses to hostname=None; refusing that stops a
    # None==None match from attaching the bearer to a scheme-less or mismatched-port URL.
    if not target.hostname or not expected.hostname:
        return False
    # Require an https origin matching the configured host AND port. The one exception is
    # local dev (SANDBOX_PROVIDER=hogland, DEBUG), which talks to a loopback host over
    # http; allow http only when both hosts are loopback. Every real remote origin must
    # still be https to receive the account-wide bearer.
    loopback_dev = settings.DEBUG and _is_loopback_host(target.hostname) and _is_loopback_host(expected.hostname)
    if not loopback_dev and (target.scheme != "https" or expected.scheme != "https"):
        return False
    return (target.hostname, target.port) == (expected.hostname, expected.port)


def sandbox_transport_token(state: dict[str, Any] | None, sandbox_url: str | None = None) -> tuple[str | None, str]:
    """(token, query_param_name) for the sandbox tunnel/proxy layer.

    Modal mints a per-sandbox connect token that is persisted in ``TaskRun.state``.
    Hogland has no per-sandbox token: its proxy authenticates with the backend's
    bearer — a rotating projected ServiceAccount JWT read fresh per request (the
    static token is the local-dev fallback) — attached here at request time so it
    never touches persisted state or Temporal payloads.

    The hogland bearer is only returned when ``sandbox_url`` is the configured
    hogland host. That host check, not the ``sandbox_backend`` state flag, is what
    authorizes attaching an account-wide credential — ``sandbox_backend`` /
    ``sandbox_url`` are also protected run-state keys, so this is defense in depth.
    """
    if (state or {}).get("sandbox_backend") == "hogland" and _is_hogland_sandbox_url(sandbox_url):
        # Deferred: hogland_sandbox pulls in the hogland SDK + httpx, which every
        # non-hogland caller of this module would otherwise pay for.
        from products.tasks.backend.logic.services.hogland_sandbox import get_hogland_api_token  # noqa: PLC0415

        return get_hogland_api_token(), "token"
    return (state or {}).get("sandbox_connect_token"), "_modal_connect_token"


def _build_request_args(
    connect_token: str | None,
    auth_token: str | None,
    token_param: str = "_modal_connect_token",
) -> tuple[dict[str, str], dict[str, str]]:
    """Build request headers and query params with appropriate auth scheme.

    When auth_token is provided (callers going through the provider tunnel/proxy):
    JWT goes as Authorization header, the transport token as the provider's query
    param. Otherwise (internal callers on same network): a Modal connect token goes
    in the Authorization header, while hogland's bearer stays a query param — its
    proxy strips an Authorization header it consumed, and only header-free requests
    reach the agent-server unauthenticated the way Modal's do.

    Returns:
        Tuple of (headers, query_params).
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    query_params: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        if connect_token:
            query_params[token_param] = connect_token
    elif connect_token:
        if token_param == "_modal_connect_token":
            headers["Authorization"] = f"Bearer {connect_token}"
        else:
            query_params[token_param] = connect_token
    return headers, query_params


def send_agent_command(
    task_run: Any,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    auth_token: str | None = None,
) -> CommandResult:
    """Send a JSON-RPC command to the sandbox agent.

    Uses the sandbox_url and connect_token stored in task_run.state.

    Args:
        auth_token: Optional JWT connection token for external callers.
            When provided, sent as Authorization header with connect_token
            as ``_modal_connect_token`` query param for Modal tunnel auth.
            When omitted, connect_token is used directly as Authorization.
    """
    sandbox_url, _ = _get_sandbox_url_and_token(task_run)
    connect_token, token_param = sandbox_transport_token(task_run.state, sandbox_url)
    if not sandbox_url:
        return CommandResult(
            success=False,
            status_code=0,
            error="No sandbox URL available",
            retryable=False,
        )

    validation_error = validate_sandbox_url(sandbox_url)
    if validation_error:
        logger.warning(
            "agent_command_ssrf_blocked",
            sandbox_url=sandbox_url,
            error=validation_error,
            task_run_id=str(task_run.id),
        )
        return CommandResult(
            success=False,
            status_code=0,
            error=f"Sandbox URL validation failed: {validation_error}",
            retryable=False,
        )

    headers, query_params = _build_request_args(connect_token, auth_token, token_param)
    command_url = f"{sandbox_url.rstrip('/')}/command"

    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params

    try:
        resp = requests.post(
            command_url,
            json=payload,
            headers=headers,
            timeout=timeout,
            params=query_params or None,
        )
    except requests.ReadTimeout:
        # The request body was already sent — the sandbox has the command and
        # is still processing it. Callers rely on turn_in_flight meaning
        # "delivered but not finished" (e.g. a long agent turn), as opposed to
        # the connection failures below where the command never arrived.
        # ConnectTimeout subclasses both Timeout and ConnectionError; catching
        # ReadTimeout first keeps it in the 502 bucket.
        return CommandResult(
            success=False,
            status_code=504,
            error="Sandbox request timed out",
            retryable=True,
            turn_in_flight=True,
        )
    except requests.ConnectionError:
        return CommandResult(
            success=False,
            status_code=502,
            error="Connection to sandbox failed",
            retryable=True,
        )
    except requests.Timeout:
        return CommandResult(
            success=False,
            status_code=504,
            error="Sandbox request timed out",
            retryable=True,
        )
    except requests.RequestException as e:
        return CommandResult(
            success=False,
            status_code=502,
            error=f"Request failed: {e}",
            retryable=True,
        )

    if resp.status_code >= 500:
        return CommandResult(
            success=False,
            status_code=resp.status_code,
            error=f"Sandbox returned {resp.status_code}",
            retryable=True,
        )

    if resp.status_code >= 400:
        try:
            error_data = resp.json()
        except ValueError:
            error_data = None

        if isinstance(error_data, dict) and error_data.get("error") == NO_ACTIVE_SESSION_ERROR:
            return CommandResult(
                success=False,
                status_code=resp.status_code,
                data=error_data,
                error=NO_ACTIVE_SESSION_ERROR,
                retryable=True,
            )
        return CommandResult(
            success=False,
            status_code=resp.status_code,
            error=f"Sandbox returned {resp.status_code}",
            retryable=False,
        )

    try:
        data = resp.json()
    except ValueError:
        data = None

    if isinstance(data, dict) and "error" in data and "result" not in data:
        rpc_error = data["error"]
        raw_error_msg = rpc_error.get("message") if isinstance(rpc_error, dict) else rpc_error
        error_msg = raw_error_msg if isinstance(raw_error_msg, str) and raw_error_msg else "Unknown agent error"
        return CommandResult(
            success=False,
            status_code=resp.status_code,
            data=data,
            error=error_msg,
            retryable=is_retryable_agent_rpc_error(error_msg),
        )

    return CommandResult(
        success=True,
        status_code=resp.status_code,
        data=data,
    )


def send_user_message(
    task_run: Any,
    message: str | None = None,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    auth_token: str | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    message_id: str | None = None,
    steer: bool = False,
) -> CommandResult:
    """Send a user_message command to the sandbox agent.

    ``message_id`` is an idempotency key: the agent-server ignores a
    redelivery carrying an id it has already accepted, which makes retrying
    delivery after an attempt-level death (worker restart) safe.
    """
    params: dict[str, Any] = {}
    if message:
        params["content"] = message
    if artifacts:
        params["artifacts"] = artifacts
    if message_id:
        params["messageId"] = message_id
    if steer:
        params["steer"] = True
    return send_agent_command(
        task_run,
        method="user_message",
        params=params,
        auth_token=auth_token,
        timeout=timeout,
    )


def send_set_config_option(
    task_run: Any,
    config_id: str,
    value: str,
    auth_token: str | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Change one option on the agent-server's live session (`model`, `effort`, `mode`).

    The agent applies the change to the session it is already holding, so the run keeps
    its conversation history and the new setting takes effect from the next turn. Only
    options the session currently offers are accepted — a model belonging to a runtime
    this sandbox isn't running comes back as an RPC error, since the harness is the
    process the sandbox was started with.
    """
    return send_agent_command(
        task_run,
        method="set_config_option",
        params={"configId": config_id, "value": value},
        auth_token=auth_token,
        timeout=timeout,
    )


def send_cancel(task_run: Any, auth_token: str | None = None) -> CommandResult:
    """Send a cancel command to the sandbox agent."""
    return send_agent_command(
        task_run,
        method="cancel",
        timeout=CANCEL_TIMEOUT_SECONDS,
        auth_token=auth_token,
    )


def send_refresh_session(
    task_run: Any,
    mcp_servers: list[dict[str, Any]],
    auth_token: str | None = None,
    timeout: int = REFRESH_TIMEOUT_SECONDS,
) -> CommandResult:
    """Push updated MCP server configs into a live sandbox agent-server.

    The agent-server handles this by interrupting its current ACP query and
    resuming with the new ``mcpServers`` list (preserving conversation
    history). Must be dispatched between turns — the agent-server will reply
    with JSON-RPC error -32002 if a prompt is currently in flight.

    """
    params: dict[str, Any] = {"mcpServers": mcp_servers}
    return send_agent_command(
        task_run,
        method=REFRESH_SESSION_METHOD,
        params=params,
        auth_token=auth_token,
        timeout=timeout,
    )
