import base64
import hashlib
import secrets
from urllib.parse import urlparse

import requests
import structlog

from posthog.security.url_validation import is_url_allowed

logger = structlog.get_logger(__name__)

TIMEOUT = 10


class SSRFBlockedError(Exception):
    pass


def _validate_url(url: str) -> None:
    allowed, reason = is_url_allowed(url)
    if not allowed:
        raise SSRFBlockedError(f"URL blocked by SSRF protection: {reason} ({url})")


def _fetch_auth_server_metadata(auth_server_url: str) -> dict:
    parsed = urlparse(auth_server_url)
    metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"
    if parsed.path and parsed.path != "/":
        metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"

    _validate_url(metadata_url)
    metadata_resp = requests.get(metadata_url, timeout=TIMEOUT)
    metadata_resp.raise_for_status()
    metadata = metadata_resp.json()

    for field in ("authorization_endpoint", "token_endpoint"):
        if field not in metadata:
            raise ValueError(f"Missing required field '{field}' in authorization server metadata")

    return metadata


# When the origin declares a cross-origin issuer (e.g. Atlassian → Cloudflare),
# cross-validate by fetching from the declared issuer's own well-known URL.
def _cross_validate_issuer(declared_issuer: str) -> dict:
    metadata = _fetch_auth_server_metadata(declared_issuer)
    if metadata.get("issuer", "").rstrip("/") != declared_issuer.rstrip("/"):
        raise ValueError("Issuer mismatch in authorization server metadata")
    return metadata


def discover_oauth_metadata(server_url: str) -> dict:
    parsed_server = urlparse(server_url)
    origin = f"{parsed_server.scheme}://{parsed_server.netloc}"
    path = parsed_server.path.rstrip("/")

    # Step 1: Try RFC 9728 Protected Resource Metadata to find the authorization server
    resource_url = f"{origin}/.well-known/oauth-protected-resource{path}"
    _validate_url(resource_url)
    resource_resp = requests.get(resource_url, timeout=TIMEOUT)
    if resource_resp.status_code == 404 and path:
        fallback_url = f"{origin}/.well-known/oauth-protected-resource"
        _validate_url(fallback_url)
        resource_resp = requests.get(fallback_url, timeout=TIMEOUT)

    if resource_resp.ok:
        resource_data = resource_resp.json()
        auth_servers = resource_data.get("authorization_servers", [])
        if auth_servers:
            auth_server_url = auth_servers[0]
            metadata = _fetch_auth_server_metadata(auth_server_url)
            declared_issuer = metadata.get("issuer", "").rstrip("/")
            if declared_issuer and declared_issuer != auth_server_url.rstrip("/"):
                metadata = _cross_validate_issuer(declared_issuer)
            else:
                metadata.setdefault("issuer", auth_server_url)
            # Carry scopes from the protected resource metadata when the auth
            # server metadata doesn't declare them (e.g. Asana).
            if "scopes_supported" not in metadata and "scopes_supported" in resource_data:
                metadata["scopes_supported"] = resource_data["scopes_supported"]
            return metadata

    # Step 2: Fall back to fetching authorization server metadata directly from the origin.
    # Many MCP servers (e.g. Linear) serve /.well-known/oauth-authorization-server
    # without implementing the protected resource metadata endpoint.
    metadata = _fetch_auth_server_metadata(origin)
    declared_issuer = metadata.get("issuer", "").rstrip("/")
    if declared_issuer and declared_issuer != origin.rstrip("/"):
        return _cross_validate_issuer(declared_issuer)
    metadata.setdefault("issuer", origin)
    return metadata


def register_dcr_client(metadata: dict, redirect_uri: str) -> str:
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise ValueError("Authorization server does not support Dynamic Client Registration")

    payload: dict[str, object] = {
        "client_name": "MCP Store (PostHog)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scope := metadata.get("scopes_supported"):
        payload["scope"] = " ".join(scope)

    _validate_url(registration_endpoint)
    resp = requests.post(registration_endpoint, json=payload, timeout=TIMEOUT)
    if not resp.ok:
        logger.error(
            "DCR registration request rejected",
            status=resp.status_code,
            body=resp.text[:500],
            registration_endpoint=registration_endpoint,
        )
        resp.raise_for_status()
    data = resp.json()
    data.pop("client_secret", None)  # Not used for public clients; don't store in plaintext

    client_id = data.get("client_id")
    if not client_id:
        raise ValueError("No client_id in DCR response")

    return client_id


def generate_pkce() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class TokenRefreshError(Exception):
    pass


def refresh_oauth_token(
    *,
    token_url: str,
    refresh_token: str,
    client_id: str,
    client_secret: str | None = None,
) -> dict:
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        _validate_url(token_url)
        resp = requests.post(token_url, data=data, timeout=TIMEOUT)
        resp.raise_for_status()
    except SSRFBlockedError:
        raise TokenRefreshError(f"Token refresh URL blocked by SSRF protection: {token_url}")
    except requests.RequestException:
        raise TokenRefreshError("Token refresh request failed")

    token_data = resp.json()
    if "access_token" not in token_data:
        raise TokenRefreshError("Token refresh response missing access_token")

    return token_data
