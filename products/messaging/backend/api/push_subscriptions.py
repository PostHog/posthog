import time
from datetime import UTC, datetime

from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from prometheus_client import Counter
from rest_framework import status
from rest_framework.request import Request

from posthog.api.capture import capture_internal
from posthog.api.utils import get_token
from posthog.exceptions import (
    RequestParsingError,
    UnspecifiedCompressionFallbackParsingError,
    generate_exception_response,
)
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.utils import decompress, load_data_from_request
from posthog.utils_cors import cors_response

from products.messaging.backend.api.push_identity_tokens import verify_push_identity_token

# Identity verification is opt-in per integration via config["push_identity_verification"]:
#   "disabled" (default) — no token required; anyone with the public project token can register.
#   "optional"           — a token is verified and recorded when present, but never required.
#   "required"           — registration/unregistration is rejected without a valid identity token.
PUSH_IDENTITY_VERIFICATION_COUNTER = Counter(
    "push_subscription_identity_verification",
    "Outcome of push subscription identity token verification.",
    labelnames=["mode", "operation", "outcome"],
)

PUSH_SUBSCRIPTION_REJECTION_COUNTER = Counter(
    "push_subscription_rejection",
    "Push subscription requests rejected, by rejection code.",
    labelnames=["code", "method"],
)

PUSH_SUBSCRIPTION_DISCARD_COUNTER = Counter(
    "push_subscription_discarded",
    "Push subscription registrations acknowledged without storing, by reason.",
    labelnames=["reason"],
)

logger = structlog.get_logger(__name__)

# Discarding a registration is this endpoint's normal case: a device registers on app open whether or
# not its project has a push integration, and most don't. The counter above carries that volume. The
# log line exists to name the project behind it, and that is the same team and app_id every time, so
# emitting it per request restates one fact indefinitely. One line per team per window keeps the
# identification and drops the repetition.
_DISCARD_LOG_WINDOW_SECONDS = 60

# That same path runs _find_integrations, a JSONB filter, on every request. Cache the team's
# configured app_ids so a registration for an app_id the team has never configured — the common case
# — answers from cache instead. Keyed on the team alone: the value is a small bounded list, whereas
# keying on the request's app_id would let one public project token mint unbounded entries.
#
# Staleness costs at most one window: a team that configures push keeps discarding for up to a minute,
# and the device re-posts on its next launch anyway.
_CONFIGURED_APP_IDS_CACHE_SECONDS = 60
_PUSH_INTEGRATION_KINDS = ("firebase", "apns")

VALID_PLATFORMS = ("android", "ios")

# A device registration payload is a handful of short string fields (distinct_id, device_token,
# platform, app_id, api_key) — well under 1 KiB. Cap the raw request body far above that but far below
# Django's global limit, so a compressed body can't inflate into a memory-exhaustion payload when
# load_data_from_request decompresses it.
MAX_BODY_BYTES = 16 * 1024

# Shared instance: deriving the encryption keys runs PBKDF2 (100k iterations per key) and is
# cached on the instance, so a module-level singleton avoids re-deriving on every request.
_encrypted_fields = EncryptedFieldMixin()


# Verification-mode precedence. An app_id can match more than one integration — config identifiers
# (project_id / bundle_id) aren't covered by a uniqueness constraint — so mode resolution must fail
# closed: take the strictest mode across every match so a lax duplicate can't downgrade a sibling's
# `required` policy. Unknown/garbage values sort to 0 (treated as disabled).
_VERIFICATION_MODE_PRECEDENCE = {"disabled": 0, "optional": 1, "required": 2}


def _is_first_discard_in_window(team_id: int) -> bool:
    """Keyed on the team and the window only. app_id is request-controlled and can fill most of the
    16 KiB body, and the project token that reaches this endpoint ships inside every copy of the app,
    so keying on it would let anyone mint unbounded cache entries. Keyed on the window so a missed
    expiry can never wedge the log shut, and fails open: losing the cache must not lose the only line
    that names the project."""
    window = int(time.time()) // _DISCARD_LOG_WINDOW_SECONDS
    try:
        return cache.add(f"push_subscriptions:discarded:{team_id}:{window}", 1, _DISCARD_LOG_WINDOW_SECONDS)
    except Exception:
        return True


def _configurable_app_ids(team_id: int) -> list[str] | None:
    """The app_ids this team has a push integration for, or None when the cache is unavailable.
    None means "don't know", so the caller falls through to the real lookup rather than discarding a
    registration a team is entitled to."""
    key = f"push_subscriptions:app_ids:{team_id}"
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
        app_ids = [
            app_id
            for integration in Integration.objects.filter(team_id=team_id, kind__in=_PUSH_INTEGRATION_KINDS).only(
                "kind", "config"
            )
            if isinstance(
                app_id := integration.config.get("project_id" if integration.kind == "firebase" else "bundle_id"), str
            )
        ]
        cache.set(key, app_ids, _CONFIGURED_APP_IDS_CACHE_SECONDS)
        return app_ids
    except Exception:
        return None


# Resolve integrations from the app_id alone, not the device platform. An app_id is either a
# Firebase project_id or an APNs bundle_id, so a device can register with either provider regardless
# of its OS — e.g. an iOS device delivering through Firebase registers with the Firebase project_id.
# (The client still sends its platform, but it's metadata, not what selects the provider.)
def _find_integrations(team_id: int, app_id: str) -> list[Integration]:
    return list(
        Integration.objects.filter(team_id=team_id)
        .filter(Q(kind="firebase", config__project_id=app_id) | Q(kind="apns", config__bundle_id=app_id))
        .only("id", "config")
    )


def _strictest_verification_mode(integrations: list[Integration]) -> str:
    return max(
        (integration.config.get("push_identity_verification", "disabled") for integration in integrations),
        key=lambda mode: _VERIFICATION_MODE_PRECEDENCE.get(mode, 0),
        default="disabled",
    )


# The error body goes back to the client only, and Django's own request log records just
# "Bad Request: /api/push_subscriptions/", so without this counter and log line the rejection
# reason is unrecoverable from production telemetry.
def _rejection_response(
    request: Request,
    message: str,
    *,
    error_type: str,
    code: str,
    status_code: int,
    team_id: int | None = None,
    app_id: str | None = None,
    detail: str | None = None,
    exc_info: bool = False,
) -> HttpResponse:
    # request.method is an arbitrary attacker-controlled token on the method_not_allowed path (any
    # HTTP verb reaches this view), so bound the counter label to the supported verbs to keep
    # Prometheus cardinality fixed. The log below keeps the raw method — structured log fields aren't
    # a time-series cardinality risk and the real verb helps diagnose who is hitting the endpoint.
    method_label = request.method if request.method in ("POST", "DELETE") else "other"
    PUSH_SUBSCRIPTION_REJECTION_COUNTER.labels(code=code, method=method_label).inc()
    # exc_info attaches the active exception's traceback for paths that swallow one (capture_failed),
    # so a 500 is diagnosable from this single labeled event rather than just the counter.
    logger.warning(
        "push_subscription_rejected",
        code=code,
        status_code=status_code,
        method=request.method,
        team_id=team_id,
        app_id=app_id,
        detail=detail,
        exc_info=exc_info,
    )
    return cors_response(
        request,
        generate_exception_response(
            "push_subscriptions",
            message,
            type=error_type,
            code=code,
            status_code=status_code,
        ),
    )


@csrf_exempt
def push_subscriptions(request: Request):
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    if request.method not in ("POST", "DELETE"):
        return _rejection_response(
            request,
            "Only POST and DELETE requests are supported.",
            error_type="validation_error",
            code="method_not_allowed",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    if len(request.body) > MAX_BODY_BYTES:
        return _rejection_response(
            request,
            "Request body too large.",
            error_type="validation_error",
            code="request_too_large",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        if request.method == "POST":
            data = load_data_from_request(request)
        else:
            # load_data_from_request only reads the body for POST (other methods read a `data` query
            # param). DELETE carries the same gzipped JSON body as POST, so decompress it directly.
            data = decompress(request.body, request.headers.get("content-encoding", "").lower())
    except (RequestParsingError, UnspecifiedCompressionFallbackParsingError):
        return _rejection_response(
            request,
            "Invalid JSON body.",
            error_type="validation_error",
            code="invalid_json",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(data, dict):
        return _rejection_response(
            request,
            "Invalid JSON body.",
            error_type="validation_error",
            code="invalid_json",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    api_key = get_token(data, request)
    if not api_key:
        return _rejection_response(
            request,
            "Project token not provided. You can find your project token in your PostHog project settings.",
            error_type="authentication_error",
            code="missing_api_key",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    team = Team.objects.get_team_from_cache_or_token(api_key)
    if not team:
        return _rejection_response(
            request,
            "Invalid project token.",
            error_type="authentication_error",
            code="invalid_api_key",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    distinct_id = data.get("distinct_id")
    device_token = data.get("device_token")
    platform = data.get("platform")
    app_id = data.get("app_id")

    missing_fields = [
        field_name
        for field_name, value in [
            ("distinct_id", distinct_id),
            ("device_token", device_token),
            ("platform", platform),
            ("app_id", app_id),
        ]
        if not value or not isinstance(value, str)
    ]
    if missing_fields:
        # absent vs empty vs invalid separates an SDK that never sends the field (contract drift)
        # from a client bridge passing an empty or mistyped value: they need different fixes.
        field_detail = ",".join(
            f"{field_name}:{'absent' if field_name not in data else 'empty' if data[field_name] == '' else 'invalid'}"
            for field_name in missing_fields
        )
        return _rejection_response(
            request,
            f"Missing required fields: {', '.join(missing_fields)}.",
            error_type="validation_error",
            code="missing_fields",
            status_code=status.HTTP_400_BAD_REQUEST,
            team_id=team.id,
            detail=field_detail,
        )

    assert isinstance(distinct_id, str)
    assert isinstance(device_token, str)
    assert isinstance(platform, str)
    assert isinstance(app_id, str)

    if platform not in VALID_PLATFORMS:
        return _rejection_response(
            request,
            f"Invalid platform. Must be one of: {', '.join(VALID_PLATFORMS)}.",
            error_type="validation_error",
            code="invalid_platform",
            status_code=status.HTTP_400_BAD_REQUEST,
            team_id=team.id,
            app_id=app_id,
        )

    # Skip the JSONB lookup when the team has no integration for this app_id, which is the endpoint's
    # normal case. A cache miss or outage returns None and falls through to the real query.
    known_app_ids = _configurable_app_ids(team.id)
    integrations = (
        [] if known_app_ids is not None and app_id not in known_app_ids else _find_integrations(team.id, app_id)
    )
    # A missing integration is an account state, not a request error: SDKs auto-register on every
    # app open, so for most teams this is the endpoint's normal case, and a 4xx here turns the
    # whole fleet into an error firehose. Acknowledge registration with a 200 and skip the store,
    # so unconsumable tokens don't become person properties and capture events; devices re-register
    # on every app open, so a team that later configures an integration is covered within a day.
    # DELETE falls through: logout must clear any subscription stored while an integration existed.
    if not integrations and request.method == "POST":
        PUSH_SUBSCRIPTION_DISCARD_COUNTER.labels(reason="no_integration").inc()
        if _is_first_discard_in_window(team.id):
            logger.info("push_subscription_discarded", reason="no_integration", team_id=team.id, app_id=app_id)
        return cors_response(
            request,
            JsonResponse(
                {
                    "distinct_id": distinct_id,
                    "platform": platform,
                    "stored": False,
                    "push_enabled": False,
                },
                status=status.HTTP_200_OK,
            ),
        )

    operation = "register" if request.method == "POST" else "unregister"
    verification_mode = _strictest_verification_mode(integrations)
    if verification_mode in ("optional", "required"):
        identity_token = data.get("identity_token")
        # Public keys can live on more than one matching integration; try them all (verify picks the
        # one that validates, then falls back to the legacy shared secret).
        public_keys = [
            key for integration in integrations for key in (integration.config.get("push_identity_public_keys") or [])
        ]
        verified = isinstance(identity_token, str) and verify_push_identity_token(
            identity_token, team, distinct_id, app_id, public_keys=public_keys
        )
        PUSH_IDENTITY_VERIFICATION_COUNTER.labels(
            mode=verification_mode,
            operation=operation,
            outcome="verified" if verified else "unverified",
        ).inc()
        if not verified and verification_mode == "required":
            return _rejection_response(
                request,
                "A valid identity token is required for this device. Your backend must sign a "
                "short-lived token for the signed-in user with the key configured for this "
                "channel's identity verification.",
                error_type="authentication_error",
                code="identity_verification_failed",
                status_code=status.HTTP_401_UNAUTHORIZED,
                team_id=team.id,
                app_id=app_id,
            )

    property_key = f"$device_push_subscription_{app_id}"

    # $unset of an absent property is a no-op, so DELETE (logout) is idempotent. device_token is
    # required for a symmetric contract but isn't matched against the stored value: logout clears
    # this app_id's subscription regardless of which token the client last held.
    properties: dict[str, dict[str, str] | list[str]]
    if request.method == "POST":
        properties = {"$set": {property_key: _encrypted_fields.encrypt(device_token)}}
        failure_message = "Failed to store push subscription."
    else:
        properties = {"$unset": [property_key]}
        failure_message = "Failed to remove push subscription."

    try:
        capture_internal(
            token=team.api_token,
            event_name="$set",
            event_source="push_subscriptions",
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties=properties,
            process_person_profile=True,
        )
    except Exception:
        return _rejection_response(
            request,
            failure_message,
            error_type="server_error",
            code="capture_failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            team_id=team.id,
            app_id=app_id,
            exc_info=True,
        )

    return cors_response(
        request,
        JsonResponse(
            {
                "distinct_id": distinct_id,
                "platform": platform,
            },
            status=status.HTTP_200_OK,
        ),
    )
