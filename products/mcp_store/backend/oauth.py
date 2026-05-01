import time
import base64
import hashlib
import secrets
from collections.abc import Callable
from urllib.parse import urlparse

import requests
import structlog

from posthog.security.url_validation import is_url_allowed

from .models import MCPServerInstallation

logger = structlog.get_logger(__name__)

TIMEOUT = 10


class SSRFBlockedError(Exception):
    pass


class OAuthTokenExchangeError(Exception):
    pass


class OAuthAuthorizeURLError(Exception):
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
        logger.warning(
            "OAuth issuer mismatch during cross-validation",
            declared_issuer=declared_issuer,
            metadata_issuer=metadata.get("issuer", ""),
        )
        raise ValueError("Issuer mismatch in authorization server metadata")
    return metadata


def _resolve_issuer(metadata: dict, expected_issuer: str) -> dict:
    """Cross-validate if the metadata declares a different issuer, otherwise default it."""
    declared_issuer = metadata.get("issuer", "").rstrip("/")
    if declared_issuer and declared_issuer != expected_issuer.rstrip("/"):
        return _cross_validate_issuer(declared_issuer)
    metadata.setdefault("issuer", expected_issuer)
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
            metadata = _resolve_issuer(_fetch_auth_server_metadata(auth_server_url), auth_server_url)
            # Carry scopes from the protected resource metadata when the auth
            # server metadata doesn't declare them (e.g. Asana).
            if "scopes_supported" not in metadata and "scopes_supported" in resource_data:
                metadata["scopes_supported"] = resource_data["scopes_supported"]
            return metadata

    # Step 2: Fall back to fetching authorization server metadata directly from the origin.
    # Many MCP servers (e.g. Linear) serve /.well-known/oauth-authorization-server
    # without implementing the protected resource metadata endpoint.
    logger.info(
        "RFC 9728 protected resource metadata not available, falling back to direct discovery", server_url=server_url
    )
    return _resolve_issuer(_fetch_auth_server_metadata(origin), origin)


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


def is_token_expiring(sensitive: dict) -> bool:
    try:
        retrieved_at = float((sensitive or {}).get("token_retrieved_at", 0))
        expires_in = float((sensitive or {}).get("expires_in", 0))
    except (TypeError, ValueError):
        return False
    if not retrieved_at or not expires_in:
        return False
    return time.time() > retrieved_at + (expires_in / 2)


class TokenRefreshError(Exception):
    pass


def resolve_installation_oauth_context(installation: MCPServerInstallation) -> tuple[dict, str, str | None]:
    """Resolve the OAuth metadata + client credentials for an installation.

    Returns ``(metadata, client_id, client_secret)``. Secrets come from the
    shared template when set, or from the installation's encrypted
    ``sensitive_configuration`` for user-added servers.

    Raises ``ValueError`` if the installation is missing required OAuth state.
    """
    sensitive = installation.sensitive_configuration or {}

    template = installation.template
    if template is not None:
        credentials = template.oauth_credentials or {}
        shared_client_id = credentials.get("client_id", "")
        if shared_client_id:
            # Shared-creds template: every installation of this template
            # authenticates with the same client against the admin-seeded
            # metadata on the template.
            metadata = dict(template.oauth_metadata or {})
            if not metadata:
                raise ValueError("Template missing OAuth metadata")
            client_secret = credentials.get("client_secret") or None
            return metadata, shared_client_id, client_secret
        # DCR template: each installation ran discovery + DCR at install
        # time. Both the metadata and the minted client live on the
        # installation — the template is never written back to, so a
        # first-installer can't poison state for other users of the template.
        metadata = dict(installation.oauth_metadata or {})
        client_id = sensitive.get("dcr_client_id", "")
        client_secret = sensitive.get("dcr_client_secret") or None
        if not metadata or not client_id:
            raise ValueError("DCR template installation missing OAuth metadata or dcr_client_id")
        return metadata, client_id, client_secret

    metadata = dict(installation.oauth_metadata or {})
    client_id = sensitive.get("dcr_client_id", "")
    client_secret = sensitive.get("dcr_client_secret") or None
    if not metadata or not client_id:
        raise ValueError("Installation missing OAuth metadata or client_id")
    return metadata, client_id, client_secret


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
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "OAuth token refresh request failed",
            token_url=token_url,
            status_code=status_code,
        )
        raise TokenRefreshError("Token refresh request failed")

    token_data = resp.json()
    if "access_token" not in token_data:
        logger.warning("OAuth token refresh response missing access_token", token_url=token_url)
        raise TokenRefreshError("Token refresh response missing access_token")

    return token_data


def refresh_installation_token(installation: MCPServerInstallation) -> dict:
    sensitive = installation.sensitive_configuration or {}
    refresh_token_value = sensitive.get("refresh_token")
    if not refresh_token_value:
        logger.warning("No refresh token available for installation", installation_id=str(installation.id))
        raise TokenRefreshError("No refresh token available")

    try:
        metadata, client_id, client_secret = resolve_installation_oauth_context(installation)
    except ValueError as exc:
        raise TokenRefreshError(str(exc))

    token_url = metadata.get("token_endpoint", "")
    if not token_url:
        raise TokenRefreshError("Missing OAuth metadata for token refresh")

    token_data = refresh_oauth_token(
        token_url=token_url,
        refresh_token=refresh_token_value,
        client_id=client_id,
        client_secret=client_secret,
    )

    # Preserve non-token keys (needs_reauth, dcr_client_id, dcr_client_secret, etc.) across refresh.
    updated: dict = dict(sensitive)
    updated["access_token"] = token_data["access_token"]
    updated["token_retrieved_at"] = int(time.time())
    updated["refresh_token"] = token_data.get("refresh_token", refresh_token_value)
    if "expires_in" in token_data:
        updated["expires_in"] = token_data["expires_in"]

    installation.sensitive_configuration = updated
    installation.save(update_fields=["sensitive_configuration", "updated_at"])

    logger.info("OAuth token refreshed successfully", installation_id=str(installation.id))
    return updated


def exchange_oauth_token(
    *,
    installation: MCPServerInstallation,
    code: str,
    pkce_verifier: str,
    redirect_uri: str,
    is_https: Callable[[str], bool],
) -> dict:
    """Exchange an authorization code for tokens using the installation's resolved client creds.

    Works for both template-backed installs (shared client creds from
    ``MCPServerTemplate.oauth_credentials``) and user-added installs (per-user
    DCR creds stored in ``sensitive_configuration``).
    """
    if not pkce_verifier:
        raise OAuthTokenExchangeError("Missing PKCE verifier")

    try:
        metadata, client_id, client_secret = resolve_installation_oauth_context(installation)
    except ValueError as exc:
        raise OAuthTokenExchangeError(str(exc))

    token_endpoint = metadata.get("token_endpoint", "")
    if not token_endpoint:
        raise OAuthTokenExchangeError("Missing token_endpoint in OAuth metadata")

    allowed, reason = is_url_allowed(token_endpoint)
    if not allowed:
        logger.warning("SSRF blocked token endpoint", url=token_endpoint, reason=reason)
        raise OAuthTokenExchangeError("Token endpoint blocked by security policy")

    if not is_https(token_endpoint):
        raise OAuthTokenExchangeError("Token endpoint must use HTTPS")

    form: dict[str, str] = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": pkce_verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret

    token_response = requests.post(token_endpoint, data=form, timeout=TIMEOUT)

    if token_response.status_code != 200:
        logger.error(
            "OAuth token exchange failed",
            status_code=token_response.status_code,
            error=token_response.text,
        )
        raise OAuthTokenExchangeError("Failed to exchange authorization code")

    return token_response.json()
