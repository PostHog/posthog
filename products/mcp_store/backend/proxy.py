import json
from collections.abc import Iterator
from typing import Any

from django.http import HttpResponse, StreamingHttpResponse

import httpx
import structlog

from posthog.security.url_validation import is_url_allowed
from posthog.settings import SERVER_GATEWAY_INTERFACE

from ee.hogai.utils.asgi import SyncIterableToAsync

from .models import MCPServerInstallation, MCPServerInstallationTool
from .oauth import TokenRefreshError, is_token_expiring, refresh_installation_token

logger = structlog.get_logger(__name__)

UPSTREAM_TIMEOUT = 180
MAX_PROXY_BODY_SIZE = 1_048_576  # 1 MB

# JSON-RPC error codes used by per-tool approval enforcement. -32000..-32099 is
# the implementation-defined server-error range; we deliberately use distinct
# codes so clients can tell "needs approval" apart from "disabled" apart from
# the batch-level rejection, which is not tied to any individual item.
TOOL_NEEDS_APPROVAL_CODE = -32001
TOOL_DISABLED_CODE = -32002
BATCH_REJECTED_CODE = -32000
METHOD_NOT_FOUND_CODE = -32601


def build_upstream_auth_headers(installation: MCPServerInstallation) -> dict[str, str]:
    sensitive = installation.sensitive_configuration or {}

    if installation.auth_type == "api_key":
        api_key = sensitive.get("api_key")
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    if installation.auth_type == "oauth":
        access_token = sensitive.get("access_token")
        if not access_token:
            return {}
        return {"Authorization": f"Bearer {access_token}"}

    return {}


def ensure_valid_token(installation: MCPServerInstallation) -> None:
    if not is_token_expiring(installation.sensitive_configuration or {}):
        return
    refresh_installation_token(installation)


def validate_installation_auth(
    installation: MCPServerInstallation,
) -> tuple[bool, HttpResponse | None]:
    """Validate that the installation has valid auth credentials.

    Returns (True, None) if auth is valid, or (False, error_response) if not.
    """
    if not installation.is_enabled:
        logger.warning(
            "Proxy auth failed: server is disabled",
            installation_id=str(installation.id),
            url=installation.url,
        )
        return False, HttpResponse(
            '{"error": "Server is disabled"}',
            content_type="application/json",
            status=403,
        )

    sensitive = installation.sensitive_configuration or {}

    if sensitive.get("needs_reauth"):
        logger.warning(
            "Proxy auth failed: needs re-authentication", installation_id=str(installation.id), url=installation.url
        )
        return False, HttpResponse(
            '{"error": "Installation needs re-authentication"}',
            content_type="application/json",
            status=401,
        )

    if installation.auth_type == "oauth":
        if not sensitive.get("access_token"):
            logger.warning(
                "Proxy auth failed: no OAuth credentials", installation_id=str(installation.id), url=installation.url
            )
            return False, HttpResponse(
                '{"error": "No credentials configured"}',
                content_type="application/json",
                status=401,
            )
        try:
            ensure_valid_token(installation)
        except TokenRefreshError:
            logger.warning("OAuth token refresh failed", installation_id=str(installation.id))
            return False, HttpResponse(
                '{"error": "Authentication failed"}',
                content_type="application/json",
                status=401,
            )

    if installation.auth_type == "api_key" and not sensitive.get("api_key"):
        logger.warning(
            "Proxy auth failed: no API key configured", installation_id=str(installation.id), url=installation.url
        )
        return False, HttpResponse(
            '{"error": "No credentials configured"}',
            content_type="application/json",
            status=401,
        )

    return True, None


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _is_tools_call(item: Any) -> bool:
    return isinstance(item, dict) and item.get("method") == "tools/call"


def _evaluate_tool_call(
    tools_by_name: dict[str, MCPServerInstallationTool], item: dict[str, Any]
) -> dict[str, Any] | None:
    """Check a single JSON-RPC item against the installation's tool approval state.

    Returns a JSON-RPC error object to send back (short-circuiting the upstream
    call), or ``None`` to let the call pass through.
    """
    if not _is_tools_call(item):
        return None

    params = item.get("params") or {}
    tool_name = params.get("name") if isinstance(params, dict) else None
    request_id = item.get("id")

    if not tool_name or not isinstance(tool_name, str):
        return _jsonrpc_error(request_id, METHOD_NOT_FOUND_CODE, "tools/call missing 'name' parameter")

    tool = tools_by_name.get(tool_name)
    if tool is None:
        return _jsonrpc_error(
            request_id,
            METHOD_NOT_FOUND_CODE,
            f"Tool '{tool_name}' is not registered for this installation",
        )

    if tool.removed_at is not None:
        return _jsonrpc_error(
            request_id,
            METHOD_NOT_FOUND_CODE,
            f"Tool '{tool_name}' is no longer available on the upstream server",
        )

    if tool.approval_state == "approved":
        return None
    if tool.approval_state == "needs_approval":
        return _jsonrpc_error(
            request_id,
            TOOL_NEEDS_APPROVAL_CODE,
            f"Tool '{tool_name}' requires approval before it can be called",
        )
    if tool.approval_state == "do_not_use":
        return _jsonrpc_error(
            request_id,
            TOOL_DISABLED_CODE,
            f"Tool '{tool_name}' has been disabled by the user",
        )
    return None


def enforce_tool_approval(
    installation: MCPServerInstallation,
    data: dict[str, Any] | list[Any],
) -> HttpResponse | None:
    """Inspect a JSON-RPC body and short-circuit tools/call that isn't approved.

    Returns an HttpResponse when at least one tool call is blocked, or None to
    pass the request through unchanged. Non-tools/call methods are always
    passed through; unknown tool names return a JSON-RPC method-not-found error
    without hitting the upstream server.
    """
    if isinstance(data, list):
        if not any(_is_tools_call(item) for item in data):
            return None
        # Pre-fetch the installation's tools once to avoid N queries on batched tools/call.
        tools_by_name = {t.tool_name: t for t in installation.tools.all()}
        responses: list[dict[str, Any]] = []
        any_blocked = False
        any_passthrough = False
        for item in data:
            blocked = _evaluate_tool_call(tools_by_name, item)
            if blocked is not None:
                responses.append(blocked)
                any_blocked = True
            else:
                any_passthrough = True
        # Mixed batches (some blocked, some passthrough) can't be safely split
        # without reshuffling responses. Reject the whole batch so clients retry
        # individual calls — this matches the spec's guidance to keep batches atomic.
        # Use a batch-level code rather than TOOL_NEEDS_APPROVAL_CODE: passthrough
        # items like tools/list have no per-item approval concept, so signaling
        # "approval needed" on them would mislead client retry logic.
        if any_blocked and any_passthrough:
            return HttpResponse(
                json.dumps(
                    [
                        _jsonrpc_error(
                            (item.get("id") if isinstance(item, dict) else None),
                            BATCH_REJECTED_CODE,
                            "Batch rejected: it contains a tool call that requires approval or is disabled; "
                            "send items individually",
                        )
                        for item in data
                    ]
                ),
                content_type="application/json",
                status=200,
            )
        if any_blocked:
            return HttpResponse(json.dumps(responses), content_type="application/json", status=200)
        return None

    if not _is_tools_call(data):
        return None
    tools_by_name = {t.tool_name: t for t in installation.tools.all()}
    blocked = _evaluate_tool_call(tools_by_name, data)
    if blocked is None:
        return None
    return HttpResponse(json.dumps(blocked), content_type="application/json", status=200)


def proxy_mcp_request(request: Any, installation: MCPServerInstallation) -> HttpResponse | StreamingHttpResponse:
    allowed, error = is_url_allowed(installation.url)
    if not allowed:
        logger.warning("SSRF: blocked proxy request", url=installation.url, reason=error)
        return HttpResponse(
            json.dumps({"error": f"URL not allowed: {error}"}),
            content_type="application/json",
            status=400,
        )

    data = request.data
    if not data or not isinstance(data, (dict, list)):
        logger.warning("Proxy request rejected: invalid request body", url=installation.url)
        return HttpResponse(
            '{"error": "Request body must be valid JSON"}',
            content_type="application/json",
            status=400,
        )

    if enforcement_response := enforce_tool_approval(installation, data):
        return enforcement_response

    body = json.dumps(data).encode()

    if len(body) > MAX_PROXY_BODY_SIZE:
        logger.warning("Proxy request rejected: body too large", url=installation.url, body_size=len(body))
        return HttpResponse(
            '{"error": "Request body too large"}',
            content_type="application/json",
            status=413,
        )

    auth_headers = build_upstream_auth_headers(installation)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **auth_headers,
    }

    mcp_session_id = request.headers.get("mcp-session-id")
    if mcp_session_id:
        headers["Mcp-Session-Id"] = mcp_session_id

    client = httpx.Client(timeout=UPSTREAM_TIMEOUT)
    try:
        upstream_request = client.build_request(
            "POST",
            installation.url,
            content=body,
            headers=headers,
        )
        upstream_response = client.send(upstream_request, stream=True)
    except httpx.ConnectError:
        client.close()
        logger.warning("Upstream MCP server unreachable", url=installation.url)
        return HttpResponse(
            '{"error": "Upstream MCP server unreachable"}',
            content_type="application/json",
            status=502,
        )
    except httpx.TimeoutException:
        client.close()
        logger.warning("Upstream MCP server timed out", url=installation.url)
        return HttpResponse(
            '{"error": "Upstream MCP server timed out"}',
            content_type="application/json",
            status=502,
        )
    except Exception:
        client.close()
        raise

    content_type = upstream_response.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        return _build_sse_response(upstream_response, client)

    # Read body then close to avoid memory leaks from buffered responses
    try:
        upstream_response.read()
    finally:
        client.close()

    if upstream_response.status_code >= 400:
        logger.warning(
            "Upstream MCP server returned error",
            url=installation.url,
            status_code=upstream_response.status_code,
            response_body=upstream_response.text[:500] if upstream_response.text else "",
        )

    response = HttpResponse(
        upstream_response.content,
        content_type=upstream_response.headers.get("content-type", "application/json"),
        status=upstream_response.status_code,
    )

    upstream_session_id = upstream_response.headers.get("mcp-session-id")
    if upstream_session_id:
        response["Mcp-Session-Id"] = upstream_session_id

    return response


def _stream_upstream(upstream_response: httpx.Response, client: httpx.Client) -> Iterator[bytes]:
    try:
        yield from upstream_response.iter_bytes(4096)
    finally:
        upstream_response.close()
        client.close()


def _build_sse_response(upstream_response: httpx.Response, client: httpx.Client) -> StreamingHttpResponse:
    stream = _stream_upstream(upstream_response, client)

    if SERVER_GATEWAY_INTERFACE == "ASGI":
        astream = SyncIterableToAsync(stream)
        response = StreamingHttpResponse(
            streaming_content=astream,
            content_type="text/event-stream",
        )
    else:
        response = StreamingHttpResponse(
            streaming_content=stream,
            content_type="text/event-stream",
        )

    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    upstream_session_id = upstream_response.headers.get("mcp-session-id")
    if upstream_session_id:
        response["Mcp-Session-Id"] = upstream_session_id

    return response
