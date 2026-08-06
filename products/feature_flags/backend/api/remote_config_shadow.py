"""Temporary Django↔Rust shadow comparison for the remote_config port (phase 2).

For each Django remote_config response, replays the same request against the Rust flags
service and records whether status + body match, to prove parity before the cutover.
Inline (every request, no background thread) and fully guarded — any failure is counted
and swallowed, never affecting the real response. Delete with the cutover (phase 3); Rust
bills nothing for remote_config until then, so this can't double-count usage.
"""

from typing import Any

from django.conf import settings

import structlog
from prometheus_client import Counter
from requests.adapters import HTTPAdapter
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication, TeamSecretTokenAuthentication
from posthog.security.outbound_proxy import internal_requests_session

logger = structlog.get_logger(__name__)

# Internal call: trust_env=False so it skips the outbound proxy, like the live flags proxy.
_SHADOW_SESSION = internal_requests_session()
# Shared module-level session across workers: size the pool and disable retries so a slow Rust
# never silently multiplies the work behind one shadow call.
_SHADOW_SESSION.mount("http://", HTTPAdapter(pool_connections=1, pool_maxsize=20, max_retries=0))
_SHADOW_SESSION.mount("https://", HTTPAdapter(pool_connections=1, pool_maxsize=20, max_retries=0))

# (connect, read) seconds — deliberately tighter than the live proxy's 3s so a slow Rust lands in
# `except` as `error` instead of adding latency to the user's response.
_SHADOW_TIMEOUT = (0.3, 0.5)

REMOTE_CONFIG_SHADOW_COMPARISONS = Counter(
    "posthog_remote_config_shadow_comparisons",
    "remote_config Django-vs-Rust shadow comparisons by outcome",
    ["result"],  # match | mismatch | error | skipped
)

# Rust implements these SDK credential types. Session-cookie and OAuth requests (Django's
# own preview/decrypt UI) 401 on Rust by design, so shadowing them would log false mismatches.
_RUST_SUPPORTED_AUTH = (
    TeamSecretTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
)


def shadow_compare_remote_config(request: Request, django_response: Response, *, project_id: int, key: str) -> None:
    # Off by default — flip REMOTE_CONFIG_SHADOW_ENABLED per environment to start (or stop) shadowing
    # without a deploy. Returns silently so a disabled shadow emits no metrics at all.
    if not getattr(settings, "REMOTE_CONFIG_SHADOW_ENABLED", False):
        return

    if not isinstance(request.successful_authenticator, _RUST_SUPPORTED_AUTH):
        REMOTE_CONFIG_SHADOW_COMPARISONS.labels(result="skipped").inc()
        return

    # Rust authenticates only the Bearer Authorization header, but Django also accepts the credential
    # from the query string and request body. Replaying those reaches Rust with no usable credential
    # (401), a false mismatch — so only compare header-authenticated requests.
    authorization = request.headers.get("Authorization")
    if not authorization:
        REMOTE_CONFIG_SHADOW_COMPARISONS.labels(result="skipped").inc()
        return

    try:
        # Rebuild the canonical /api/projects path Rust serves (not request.get_full_path(), which can
        # be an /api/environments or legacy alias). Rust resolves the project from ?token= when present,
        # else from this segment — both give the same flag.
        url = f"{settings.FEATURE_FLAGS_DEFINITIONS_SERVICE_URL}/api/projects/{project_id}/feature_flags/{key}/remote_config"
        rust = _SHADOW_SESSION.get(
            url,
            params=request.query_params.dict(),
            headers={"Authorization": authorization},
            timeout=_SHADOW_TIMEOUT,
        )
        if _responses_match(django_response, rust):
            REMOTE_CONFIG_SHADOW_COMPARISONS.labels(result="match").inc()
        else:
            REMOTE_CONFIG_SHADOW_COMPARISONS.labels(result="mismatch").inc()
            # Never log the bodies — decrypted remote config payloads are secrets.
            logger.warning(
                "remote_config_shadow_mismatch",
                flag=key,
                project_id=project_id,
                django_status=django_response.status_code,
                rust_status=rust.status_code,
            )
    except Exception:
        REMOTE_CONFIG_SHADOW_COMPARISONS.labels(result="error").inc()
        logger.warning("remote_config_shadow_error", flag=key, project_id=project_id, exc_info=True)


def _responses_match(django_response: Response, rust_response: Any) -> bool:
    if django_response.status_code != rust_response.status_code:
        return False
    return django_response.data == _rust_body(rust_response)


# Sentinel for a non-empty body that isn't valid JSON. Distinct from None so a garbage Rust body
# can't compare equal to Django's empty Response(None).data and get miscounted as a match.
_UNPARSEABLE = object()


def _rust_body(rust_response: Any) -> Any:
    # Both sides render a falsy/null payload as an empty 200 body; treat empty as None so it
    # equals Django's Response(None).data.
    if not rust_response.content:
        return None
    try:
        return rust_response.json()
    except ValueError:
        return _UNPARSEABLE
