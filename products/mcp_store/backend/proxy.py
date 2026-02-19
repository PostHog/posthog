import json
import time
from typing import Any

from django.http import HttpResponse, StreamingHttpResponse

import httpx
import structlog

from posthog.security.url_validation import is_url_allowed
from posthog.settings import SERVER_GATEWAY_INTERFACE

from ee.hogai.utils.asgi import SyncIterableToAsync

from .models import MCPServerInstallation
from .oauth import TokenRefreshError, refresh_oauth_token

logger = structlog.get_logger(__name__)

UPSTREAM_TIMEOUT = 60
MAX_PROXY_BODY_SIZE = 1_048_576  # 1 MB


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


def is_token_expired(installation: MCPServerInstallation) -> bool:
    sensitive = installation.sensitive_configuration or {}
    retrieved_at = sensitive.get("token_retrieved_at")
    expires_in = sensitive.get("expires_in")
    if not retrieved_at or not expires_in:
        return False
    return time.time() > (int(retrieved_at) + int(expires_in) - 60)


def ensure_valid_token(installation: MCPServerInstallation) -> None:
    if not is_token_expired(installation):
        return

    sensitive = installation.sensitive_configuration or {}
    refresh_token = sensitive.get("refresh_token")
    if not refresh_token:
        raise TokenRefreshError("No refresh token available")

    server = installation.server
    if not server or not server.oauth_metadata or not server.oauth_client_id:
        raise TokenRefreshError("Missing OAuth server configuration")

    token_url = server.oauth_metadata.get("token_endpoint")
    if not token_url:
        raise TokenRefreshError("Missing token endpoint")

    token_data = refresh_oauth_token(
        token_url=token_url,
        refresh_token=refresh_token,
        client_id=server.oauth_client_id,
    )

    new_sensitive = dict(sensitive)
    new_sensitive["access_token"] = token_data["access_token"]
    new_sensitive["token_retrieved_at"] = int(time.time())
    if "refresh_token" in token_data:
        new_sensitive["refresh_token"] = token_data["refresh_token"]
    if "expires_in" in token_data:
        new_sensitive["expires_in"] = token_data["expires_in"]
    new_sensitive.pop("needs_reauth", None)

    installation.sensitive_configuration = new_sensitive
    installation.save(update_fields=["sensitive_configuration", "updated_at"])


def validate_installation_auth(installation: MCPServerInstallation) -> tuple[bool, HttpResponse | None]:
    """Validate that the installation has valid auth credentials.

    Returns (True, None) if auth is valid, or (False, error_response) if not.
    """
    sensitive = installation.sensitive_configuration or {}

    if sensitive.get("needs_reauth"):
        return False, HttpResponse(
            '{"error": "Installation needs re-authentication"}',
            content_type="application/json",
            status=401,
        )

    if installation.auth_type == "oauth":
        if not sensitive.get("access_token"):
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
        return False, HttpResponse(
            '{"error": "No credentials configured"}',
            content_type="application/json",
            status=401,
        )

    return True, None


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
        return HttpResponse(
            '{"error": "Request body must be valid JSON"}',
            content_type="application/json",
            status=400,
        )

    body = json.dumps(data).encode()

    if len(body) > MAX_PROXY_BODY_SIZE:
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

    mcp_session_id = request.META.get("HTTP_MCP_SESSION_ID")
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

    # Buffered JSON response — read body then close
    upstream_response.read()
    client.close()

    response = HttpResponse(
        upstream_response.content,
        content_type=upstream_response.headers.get("content-type", "application/json"),
        status=upstream_response.status_code,
    )

    upstream_session_id = upstream_response.headers.get("mcp-session-id")
    if upstream_session_id:
        response["Mcp-Session-Id"] = upstream_session_id

    return response


def _stream_upstream(upstream_response: httpx.Response, client: httpx.Client):
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
