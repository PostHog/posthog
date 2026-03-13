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


@dataclass
class CommandResult:
    success: bool
    status_code: int
    data: dict[str, Any] | None = None
    error: str | None = None
    retryable: bool = False


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


def _build_headers(
    connect_token: str | None,
    auth_token: str | None,
) -> dict[str, str]:
    """Build request headers with appropriate auth scheme.

    When auth_token is provided (API callers): dual-header auth with
    Authorization: Bearer {auth_token} and modal-token: {connect_token}.
    Otherwise (internal callers like Slack): single Authorization: Bearer {connect_token}.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        if connect_token:
            headers["modal-token"] = connect_token
    elif connect_token:
        headers["Authorization"] = f"Bearer {connect_token}"
    return headers


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
        auth_token: Optional JWT connection token for API callers.
            When provided, sent as Authorization header with connect_token
            as modal-token. When omitted, connect_token is used as Authorization.
    """
    sandbox_url, connect_token = _get_sandbox_url_and_token(task_run)
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

    headers = _build_headers(connect_token, auth_token)
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
        error_msg = rpc_error.get("message", "Unknown agent error") if isinstance(rpc_error, dict) else str(rpc_error)
        return CommandResult(
            success=False,
            status_code=resp.status_code,
            data=data,
            error=error_msg,
            retryable=False,
        )

    return CommandResult(
        success=True,
        status_code=resp.status_code,
        data=data,
    )


def send_user_message(
    task_run: Any,
    message: str,
    auth_token: str | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
) -> CommandResult:
    """Send a user_message command to the sandbox agent."""
    return send_agent_command(
        task_run,
        method="user_message",
        params={"content": message},
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
