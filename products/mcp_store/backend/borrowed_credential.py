from urllib.parse import urlparse

from django.conf import settings

import jwt

from posthog.models.personal_api_key import find_personal_api_key, looks_like_legacy_personal_api_key
from posthog.models.utils import OAUTH_ACCESS_TOKEN_PREFIX, PERSONAL_API_KEY_PREFIX, SECRET_API_TOKEN_PREFIX
from posthog.security.url_validation import canonicalize_host

BORROWED_POSTHOG_CREDENTIAL_DETAIL = (
    "This connection uses a PostHog credential, so only the person who connected it can use it."
)


class BorrowedCredentialRefused(Exception):
    pass


def is_posthog_connection(url: str, token: str | None) -> bool:
    """Whether a connection acts with a PostHog credential, which only its owner may use.

    A PostHog credential reaches every project its owner can, and account-level routes ignore a project limit,
    so there is no narrowed copy that is safe to hand to someone else.
    """
    return _is_posthog_mcp_url(url) or (token is not None and _is_posthog_credential(token))


def _is_posthog_mcp_url(url: str) -> bool:
    # The request goes to the canonical host, so a Unicode or root-dot spelling of a PostHog host must match too.
    host, port = _canonical_host_and_port(url)
    if host == "posthog.com" or host.endswith(".posthog.com"):
        return True
    own_urls = [settings.MCP_SERVER_URL, settings.SITE_URL, *settings.ID_JAG_ALLOWED_RESOURCES]
    return (host, port) in {_canonical_host_and_port(own) for own in own_urls if own}


def _canonical_host_and_port(url: str) -> tuple[str, int | None]:
    try:
        parsed = urlparse(url)
        return canonicalize_host(parsed.hostname or "").lower(), parsed.port
    except ValueError:
        return "", None


def _is_posthog_credential(token: str) -> bool:
    if token.startswith((OAUTH_ACCESS_TOKEN_PREFIX, PERSONAL_API_KEY_PREFIX, SECRET_API_TOKEN_PREFIX)):
        return True
    if token.count(".") == 2:
        return _is_access_token_jwt_issued_here(token)
    # A bare 43-character secret may just as well be a third-party token, so only a key found here counts.
    return looks_like_legacy_personal_api_key(token) and find_personal_api_key(token) is not None


def _is_access_token_jwt_issued_here(token: str) -> bool:
    try:
        if jwt.get_unverified_header(token).get("typ") != "at+jwt":
            return False
        # The claim only classifies the token, and a match makes the caller lose access, so a forged issuer
        # gains nothing. Third-party servers issue the same `at+jwt` type, which is why the type alone is not enough.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return (claims.get("iss") or "").rstrip("/") == (settings.SITE_URL or "").rstrip("/")
