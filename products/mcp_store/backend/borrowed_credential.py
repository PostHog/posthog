from urllib.parse import urlparse

from django.conf import settings

import jwt

from posthog.auth import IDJagAccessTokenAuthentication
from posthog.models.personal_api_key import find_personal_api_key, looks_like_legacy_personal_api_key
from posthog.models.utils import OAUTH_ACCESS_TOKEN_PREFIX, PERSONAL_API_KEY_PREFIX

BORROWED_POSTHOG_CREDENTIAL_DETAIL = (
    "This connection uses a PostHog credential, so only the person who connected it can use it."
)


class BorrowedCredentialRefused(Exception):
    pass


def refuse_borrowed_posthog_credential(url: str, token: str | None) -> None:
    """Raise when a caller other than the connection's owner would act with a PostHog credential.

    A PostHog credential reaches every project its owner can, and account-level routes ignore a project limit,
    so there is no narrowed copy that is safe to hand to someone else.
    """
    if is_posthog_connection(url, token):
        raise BorrowedCredentialRefused(BORROWED_POSTHOG_CREDENTIAL_DETAIL)


def is_posthog_connection(url: str, token: str | None) -> bool:
    return _is_posthog_mcp_url(url) or (token is not None and _is_posthog_credential(token))


def _is_posthog_mcp_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname == "posthog.com" or hostname.endswith(".posthog.com"):
        return True
    own_urls = [settings.MCP_SERVER_URL, settings.SITE_URL, *settings.ID_JAG_ALLOWED_RESOURCES]
    return parsed.netloc.lower() in {urlparse(own).netloc.lower() for own in own_urls if own}


def _is_posthog_credential(token: str) -> bool:
    if token.startswith((OAUTH_ACCESS_TOKEN_PREFIX, PERSONAL_API_KEY_PREFIX)):
        return True
    if IDJagAccessTokenAuthentication.is_id_jag_token(token):
        return _is_issued_here(token)
    # A bare 43-character secret may just as well be a third-party token, so only a key found here counts.
    return looks_like_legacy_personal_api_key(token) and find_personal_api_key(token) is not None


def _is_issued_here(token: str) -> bool:
    try:
        # The claim only classifies the token, and a match makes the caller lose access, so a forged issuer
        # gains nothing. Third-party servers issue the same `at+jwt` type, which is why the type alone is not enough.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return (claims.get("iss") or "").rstrip("/") == (settings.SITE_URL or "").rstrip("/")
