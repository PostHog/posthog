import time
import base64
import hashlib
import secrets
from collections.abc import Callable
from contextlib import suppress
from urllib.parse import urlparse

import requests
import structlog
import tldextract
from redis.exceptions import LockError

from posthog.redis import get_client
from posthog.security.url_validation import is_url_allowed

from .models import MCPServerInstallation

logger = structlog.get_logger(__name__)

TIMEOUT = 10
SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
DEFAULT_CONFIDENTIAL_TOKEN_ENDPOINT_AUTH_METHOD = "client_secret_basic"


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


def _canonical_origin(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None

    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        return None

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    return f"{scheme}://{netloc}"


def _validate_resource_bound_to_server(resource: object, server_url: str) -> str:
    if not isinstance(resource, str) or not resource:
        raise ValueError("OAuth protected resource metadata resource must be a non-empty string")

    parsed_resource = urlparse(resource)
    if not parsed_resource.scheme or not parsed_resource.netloc:
        raise ValueError("OAuth protected resource metadata resource is not an absolute URL")
    if parsed_resource.fragment:
        raise ValueError("OAuth protected resource metadata resource must not include a fragment")

    resource_origin = _canonical_origin(resource)
    server_origin = _canonical_origin(server_url)
    if not resource_origin or not server_origin or resource_origin != server_origin:
        logger.warning(
            "OAuth protected resource metadata resource is not bound to MCP server",
            server_url=server_url,
            resource=resource,
        )
        raise ValueError("OAuth protected resource metadata resource is not bound to MCP server")

    return resource


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def requested_oauth_scopes(metadata: dict) -> list[str]:
    """Return the exact scopes we should request from this provider."""
    resource_scopes = _as_string_list(metadata.get("resource_scopes_supported"))
    if resource_scopes:
        return resource_scopes
    return _as_string_list(metadata.get("scopes_supported"))


def requested_oauth_grant_types(metadata: dict) -> list[str]:
    grant_types = ["authorization_code"]
    supported_grants = _as_string_list(metadata.get("grant_types_supported"))
    if "refresh_token" in supported_grants:
        grant_types.append("refresh_token")
    return grant_types


def select_token_endpoint_auth_method(metadata: dict, *, has_client_secret: bool = False) -> str:
    """Pick the token endpoint auth method we can actually use.

    Prefer public PKCE clients when the provider allows them. Otherwise use a
    client-secret method we support, keeping the registered method with the
    per-installation DCR credentials for token exchange and refresh.
    """
    supported_methods = _as_string_list(metadata.get("token_endpoint_auth_methods_supported"))
    preferred_methods = (
        ("client_secret_post", "client_secret_basic", "none")
        if has_client_secret
        else SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS
    )
    if not supported_methods:
        return DEFAULT_CONFIDENTIAL_TOKEN_ENDPOINT_AUTH_METHOD if has_client_secret else "none"
    for method in preferred_methods:
        if method in supported_methods:
            return method

    raise ValueError(f"Unsupported token_endpoint_auth_methods_supported: {', '.join(supported_methods)}")


def oauth_resource(metadata: dict) -> str:
    resource = metadata.get("resource")
    return resource if isinstance(resource, str) else ""


def _fetch_auth_server_metadata(auth_server_url: str) -> dict:
    # MCP Authorization §2.3 mandates this exact ordered chain of well-known URLs.
    # https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#authorization-server-metadata-discovery
    parsed = urlparse(auth_server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    has_path = parsed.path and parsed.path != "/"
    path = parsed.path.rstrip("/") if has_path else ""

    if path:
        candidates = [
            f"{origin}/.well-known/oauth-authorization-server{path}",
            f"{origin}/.well-known/openid-configuration{path}",
            f"{origin}{path}/.well-known/openid-configuration",
        ]
    else:
        candidates = [
            f"{origin}/.well-known/oauth-authorization-server",
            f"{origin}/.well-known/openid-configuration",
        ]

    # Only fall back on "endpoint not implemented" — transient errors must surface as-is.
    FALLBACK_STATUSES = {404, 405}
    last_exc: Exception = RuntimeError("no discovery candidates were attempted")
    for metadata_url in candidates:
        _validate_url(metadata_url)
        metadata_resp = requests.get(metadata_url, timeout=TIMEOUT)
        if metadata_resp.status_code in FALLBACK_STATUSES:
            last_exc = requests.HTTPError(response=metadata_resp)
            continue
        metadata_resp.raise_for_status()
        metadata = metadata_resp.json()
        for field in ("authorization_endpoint", "token_endpoint"):
            if field not in metadata:
                raise ValueError(f"Missing required field '{field}' in authorization server metadata")
        if metadata_url != candidates[0]:
            logger.info(
                "OAuth auth-server metadata discovered via fallback URL",
                auth_server_url=auth_server_url,
                tried_url=metadata_url,
            )
        return metadata

    raise last_exc


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


def _registrable_domain(hostname: str) -> str | None:
    """Return the eTLD+1 (registrable domain) for a hostname, e.g. `auth.example.co.uk` -> `example.co.uk`."""
    extracted = tldextract.extract(hostname)
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}".lower()


def _validate_endpoints_bound_to_issuer(metadata: dict) -> None:
    """Reject metadata where OAuth endpoints live on an unrelated registrable domain from the issuer.

    Without this, a malicious metadata source can mix endpoints from a real
    provider with an attacker-controlled token_endpoint, exfiltrating
    authorization codes, PKCE verifiers, and DCR-minted client_secrets while
    the user authorizes against the legitimate provider.

    Many auth setups (Keycloak, Auth0, Okta, and apps that delegate auth
    to a dedicated subdomain) publish the issuer on one subdomain and the
    actual OAuth endpoints on a sibling subdomain — e.g. issuer at
    `mcp.example.com/oauth` with endpoints on `auth.example.com`.
    """
    issuer = (metadata.get("issuer") or "").rstrip("/")
    if not issuer:
        raise ValueError("OAuth metadata is missing issuer")

    parsed_issuer = urlparse(issuer)
    if not parsed_issuer.scheme or not parsed_issuer.netloc:
        raise ValueError("OAuth metadata issuer is not an absolute URL")

    issuer_domain = _registrable_domain(parsed_issuer.hostname or "")
    if issuer_domain is None:
        raise ValueError("OAuth metadata issuer has no registrable domain")

    for field in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        url = metadata.get(field)
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme != parsed_issuer.scheme:
            logger.warning(
                "OAuth endpoint scheme does not match issuer",
                issuer=issuer,
                field=field,
                endpoint=url,
            )
            raise ValueError(f"OAuth endpoint '{field}' scheme does not match issuer")
        endpoint_domain = _registrable_domain(parsed.hostname or "")
        if endpoint_domain != issuer_domain:
            logger.warning(
                "OAuth endpoint registrable domain does not match issuer",
                issuer=issuer,
                field=field,
                endpoint=url,
                issuer_domain=issuer_domain,
                endpoint_domain=endpoint_domain,
            )
            raise ValueError(f"OAuth endpoint '{field}' is on an unrelated domain from issuer")


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
        bound_resource = None
        if "resource" in resource_data:
            bound_resource = _validate_resource_bound_to_server(resource_data["resource"], server_url)
        auth_servers = resource_data.get("authorization_servers", [])
        if auth_servers:
            auth_server_url = auth_servers[0]
            metadata = _resolve_issuer(_fetch_auth_server_metadata(auth_server_url), auth_server_url)
            if bound_resource:
                metadata["resource"] = bound_resource
            if "scopes_supported" in resource_data:
                metadata["resource_scopes_supported"] = resource_data["scopes_supported"]
            # Carry scopes from the protected resource metadata when the auth
            # server metadata doesn't declare them (e.g. Asana).
            if "scopes_supported" not in metadata and "scopes_supported" in resource_data:
                metadata["scopes_supported"] = resource_data["scopes_supported"]
            _validate_endpoints_bound_to_issuer(metadata)
            return metadata

    # Step 2: Fall back to fetching authorization server metadata directly from the origin.
    # Many MCP servers (e.g. Linear) serve /.well-known/oauth-authorization-server
    # without implementing the protected resource metadata endpoint.
    logger.info(
        "RFC 9728 protected resource metadata not available, falling back to direct discovery", server_url=server_url
    )
    metadata = _resolve_issuer(_fetch_auth_server_metadata(origin), origin)
    _validate_endpoints_bound_to_issuer(metadata)
    return metadata


def register_dcr_client(metadata: dict, redirect_uri: str) -> tuple[str, str | None, str]:
    """Run RFC 7591 Dynamic Client Registration.

    Returns ``(client_id, client_secret, token_endpoint_auth_method)``. Some
    servers (e.g. Supabase) register a confidential client even when we ask for
    a public one, so the auth method is persisted with the minted client.
    """
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise ValueError("Authorization server does not support Dynamic Client Registration")

    token_endpoint_auth_method = select_token_endpoint_auth_method(metadata)
    payload: dict[str, object] = {
        "client_name": "MCP Store (PostHog)",
        "redirect_uris": [redirect_uri],
        "grant_types": requested_oauth_grant_types(metadata),
        "response_types": ["code"],
        "token_endpoint_auth_method": token_endpoint_auth_method,
    }
    if scopes := requested_oauth_scopes(metadata):
        payload["scope"] = " ".join(scopes)

    _validate_url(registration_endpoint)
    resp = requests.post(registration_endpoint, json=payload, timeout=TIMEOUT, allow_redirects=False)
    if 300 <= resp.status_code < 400:
        raise ValueError("Dynamic Client Registration endpoint redirected")
    if not resp.ok:
        logger.error(
            "DCR registration request rejected",
            status=resp.status_code,
            body=resp.text[:500],
            registration_endpoint=registration_endpoint,
        )
        resp.raise_for_status()
    data = resp.json()

    client_id = data.get("client_id")
    if not client_id:
        raise ValueError("No client_id in DCR response")

    returned_secret = data.get("client_secret") or ""
    returned_auth_method_value = data.get("token_endpoint_auth_method")
    if isinstance(returned_auth_method_value, str) and returned_auth_method_value:
        returned_auth_method = returned_auth_method_value
    elif returned_secret and token_endpoint_auth_method == "none":
        returned_auth_method = DEFAULT_CONFIDENTIAL_TOKEN_ENDPOINT_AUTH_METHOD
    else:
        returned_auth_method = token_endpoint_auth_method
    if returned_auth_method not in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
        raise ValueError(f"Unsupported token_endpoint_auth_method from DCR response: {returned_auth_method}")
    if returned_auth_method != "none" and not returned_secret:
        raise ValueError("DCR response registered a confidential client without client_secret")
    client_secret = returned_secret if returned_secret and returned_auth_method != "none" else None

    return client_id, client_secret, returned_auth_method


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


def _credential_auth_method(credentials: dict, auth_method_key: str, client_secret: str | None) -> str:
    method = credentials.get(auth_method_key)
    if isinstance(method, str) and method in SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS:
        return method
    return DEFAULT_CONFIDENTIAL_TOKEN_ENDPOINT_AUTH_METHOD if client_secret else "none"


def resolve_installation_oauth_context(installation: MCPServerInstallation) -> tuple[dict, str, str | None, str]:
    """Resolve the OAuth metadata + client credentials for an installation.

    Returns ``(metadata, client_id, client_secret, token_endpoint_auth_method)``.
    Secrets come from the shared template when set, or from the installation's
    encrypted ``sensitive_configuration`` for user-added servers.

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
            auth_method = _credential_auth_method(credentials, "token_endpoint_auth_method", client_secret)
            return metadata, shared_client_id, client_secret, auth_method
        # DCR template: each installation ran discovery + DCR at install
        # time. Both the metadata and the minted client live on the
        # installation — the template is never written back to, so a
        # first-installer can't poison state for other users of the template.
        metadata = dict(installation.oauth_metadata or {})
        client_id = sensitive.get("dcr_client_id", "")
        client_secret = sensitive.get("dcr_client_secret") or None
        if not metadata or not client_id:
            raise ValueError("DCR template installation missing OAuth metadata or dcr_client_id")
        auth_method = _credential_auth_method(sensitive, "dcr_token_endpoint_auth_method", client_secret)
        return metadata, client_id, client_secret, auth_method

    metadata = dict(installation.oauth_metadata or {})
    client_id = sensitive.get("dcr_client_id", "")
    client_secret = sensitive.get("dcr_client_secret") or None
    if not metadata or not client_id:
        raise ValueError("Installation missing OAuth metadata or client_id")
    auth_method = _credential_auth_method(sensitive, "dcr_token_endpoint_auth_method", client_secret)
    return metadata, client_id, client_secret, auth_method


def _token_request_auth(
    form: dict[str, str],
    *,
    client_id: str,
    client_secret: str | None,
    token_endpoint_auth_method: str,
) -> tuple[dict[str, str], tuple[str, str] | None]:
    if token_endpoint_auth_method == "client_secret_basic":
        if not client_secret:
            raise ValueError("Missing client_secret for client_secret_basic token auth")
        return form, (client_id, client_secret)

    form["client_id"] = client_id
    if token_endpoint_auth_method == "client_secret_post":
        if not client_secret:
            raise ValueError("Missing client_secret for client_secret_post token auth")
        form["client_secret"] = client_secret
    return form, None


def refresh_oauth_token(
    *,
    token_url: str,
    refresh_token: str,
    client_id: str,
    client_secret: str | None = None,
    token_endpoint_auth_method: str | None = None,
    resource: str = "",
) -> dict:
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if resource:
        data["resource"] = resource

    try:
        data, auth = _token_request_auth(
            data,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method=token_endpoint_auth_method
            or (DEFAULT_CONFIDENTIAL_TOKEN_ENDPOINT_AUTH_METHOD if client_secret else "none"),
        )
    except ValueError as exc:
        raise TokenRefreshError(str(exc))

    try:
        _validate_url(token_url)
        resp = requests.post(token_url, data=data, auth=auth, timeout=TIMEOUT, allow_redirects=False)
        if 300 <= resp.status_code < 400:
            raise TokenRefreshError("Token refresh endpoint redirected")
        resp.raise_for_status()
    except SSRFBlockedError:
        raise TokenRefreshError(f"Token refresh URL blocked by SSRF protection: {token_url}")
    except requests.RequestException as exc:
        failed_status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "OAuth token refresh request failed",
            token_url=token_url,
            status_code=failed_status_code,
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
        metadata, client_id, client_secret, token_endpoint_auth_method = resolve_installation_oauth_context(
            installation
        )
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
        token_endpoint_auth_method=token_endpoint_auth_method,
        resource=oauth_resource(metadata),
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


# Refresh should finish in well under TIMEOUT (10s); the TTL only bounds a crashed holder.
TOKEN_REFRESH_LOCK_TTL_SECONDS = 30
TOKEN_REFRESH_LOCK_WAIT_SECONDS = 15


def _token_refresh_lock_key(installation_id: str) -> str:
    return f"mcp_store:token_refresh:{installation_id}"


def refresh_installation_token_single_flight(installation: MCPServerInstallation) -> dict:
    """Refresh with a per-installation Redis lock so concurrent callers mint once.

    Providers commonly rotate the refresh token on use, so parallel refreshes
    would revoke each other's tokens. Waiters re-read the row after the holder
    finishes; if it's fresh they skip the mint entirely.
    """
    lock = get_client().lock(
        _token_refresh_lock_key(str(installation.id)),
        timeout=TOKEN_REFRESH_LOCK_TTL_SECONDS,
        blocking_timeout=TOKEN_REFRESH_LOCK_WAIT_SECONDS,
    )
    if not lock.acquire():
        # Waited out the budget — trust the holder's result if it landed.
        installation.refresh_from_db(fields=["sensitive_configuration"])
        if is_token_expiring(installation.sensitive_configuration or {}):
            raise TokenRefreshError("Timed out waiting for a concurrent token refresh")
        return installation.sensitive_configuration

    try:
        # Another holder may have refreshed while we waited for the lock.
        installation.refresh_from_db(fields=["sensitive_configuration"])
        if not is_token_expiring(installation.sensitive_configuration or {}):
            return installation.sensitive_configuration
        return refresh_installation_token(installation)
    finally:
        # The lock may have expired mid-refresh; releasing someone else's lock raises.
        with suppress(LockError):
            lock.release()


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
        metadata, client_id, client_secret, token_endpoint_auth_method = resolve_installation_oauth_context(
            installation
        )
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
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": pkce_verifier,
    }
    if resource := oauth_resource(metadata):
        form["resource"] = resource

    try:
        form, auth = _token_request_auth(
            form,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method=token_endpoint_auth_method,
        )
    except ValueError as exc:
        raise OAuthTokenExchangeError(str(exc))

    token_response = requests.post(token_endpoint, data=form, auth=auth, timeout=TIMEOUT, allow_redirects=False)

    # RFC 6749 specifies 200, but some providers (e.g. Supabase) return 201.
    if 300 <= token_response.status_code < 400:
        raise OAuthTokenExchangeError("Token endpoint redirected")
    if not token_response.ok:
        logger.error(
            "OAuth token exchange failed",
            status_code=token_response.status_code,
            error=token_response.text,
        )
        raise OAuthTokenExchangeError("Failed to exchange authorization code")

    return token_response.json()
