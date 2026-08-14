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

logger = structlog.get_logger(__name__)

# Identity verification is opt-in per integration via config["push_identity_verification"]:
#   "disabled" (default) — no token required; anyone with the public project token can register.
#   "optional"           — a token is verified and recorded when present, but never required.
#   "required"           — registration/unregistration is rejected without a valid identity token.
PUSH_IDENTITY_VERIFICATION_COUNTER = Counter(
    "push_subscription_identity_verification",
    "Outcome of push subscription identity token verification.",
    labelnames=["mode", "operation", "outcome"],
)

# The only signal a rejected registration leaves is Django's own `Bad Request: <path>` line, which
# names the path and nothing else. Break the rejections down by the code the client received, so a
# flood is attributable to one cause without querying.
PUSH_SUBSCRIPTION_REJECTED_COUNTER = Counter(
    "push_subscription_rejected",
    "Push subscription requests answered with an error, by the code returned to the client.",
    labelnames=["code"],
)

# A device re-sends its pending registration on every process start until one succeeds, because both
# mobile SDKs treat 4xx as terminal without persisting that decision across launches. So a project that
# ships the SDK without a push integration produces one rejection per app launch per device
# indefinitely, a floor that grows with installs rather than with traffic.
#
# Throttling the rejection keeps the first few per window visible, so a genuine app_id typo still
# surfaces, and serves 429 beyond that, which the SDKs treat as retryable and back off on. The 400 stays
# the default because it is what makes a device eventually register once the project is configured;
# answering 2xx instead would mark the registration delivered and strand every installed device.
_UNCONFIGURED_THROTTLE_LIMIT = 10
_UNCONFIGURED_THROTTLE_WINDOW_SECONDS = 60

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


def _unconfigured_rejection_count(team_id: int) -> int:
    """Fixed-window counter per team, keyed on the window so a missed expiry can never wedge the throttle
    shut. Returns 0 on a cache outage, which both fails the throttle open and suppresses the log."""
    window = int(time.time()) // _UNCONFIGURED_THROTTLE_WINDOW_SECONDS
    key = f"push_subscriptions_unconfigured:{team_id}:{window}"
    try:
        cache.add(key, 0, timeout=_UNCONFIGURED_THROTTLE_WINDOW_SECONDS)
        return cache.incr(key)
    except ValueError:
        # The key expired between add and incr; this request is the window's first.
        return 1
    except Exception:
        return 0


def _rejection(request: Request, message: str, *, type: str, code: str, status_code: int) -> HttpResponse:
    PUSH_SUBSCRIPTION_REJECTED_COUNTER.labels(code=code).inc()
    return cors_response(
        request,
        generate_exception_response("push_subscriptions", message, type=type, code=code, status_code=status_code),
    )


def _strictest_verification_mode(integrations: list[Integration]) -> str:
    return max(
        (integration.config.get("push_identity_verification", "disabled") for integration in integrations),
        key=lambda mode: _VERIFICATION_MODE_PRECEDENCE.get(mode, 0),
        default="disabled",
    )


@csrf_exempt
def push_subscriptions(request: Request):
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    if request.method not in ("POST", "DELETE"):
        return _rejection(
            request,
            "Only POST and DELETE requests are supported.",
            type="validation_error",
            code="method_not_allowed",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    if len(request.body) > MAX_BODY_BYTES:
        return _rejection(
            request,
            "Request body too large.",
            type="validation_error",
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
        return _rejection(
            request,
            "Invalid JSON body.",
            type="validation_error",
            code="invalid_json",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(data, dict):
        return _rejection(
            request,
            "Invalid JSON body.",
            type="validation_error",
            code="invalid_json",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    api_key = get_token(data, request)
    if not api_key:
        return _rejection(
            request,
            "Project token not provided. You can find your project token in your PostHog project settings.",
            type="authentication_error",
            code="missing_api_key",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    team = Team.objects.get_team_from_cache_or_token(api_key)
    if not team:
        return _rejection(
            request,
            "Invalid project token.",
            type="authentication_error",
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
        return _rejection(
            request,
            f"Missing required fields: {', '.join(missing_fields)}.",
            type="validation_error",
            code="missing_fields",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    assert isinstance(distinct_id, str)
    assert isinstance(device_token, str)
    assert isinstance(platform, str)
    assert isinstance(app_id, str)

    if platform not in VALID_PLATFORMS:
        return _rejection(
            request,
            f"Invalid platform. Must be one of: {', '.join(VALID_PLATFORMS)}.",
            type="validation_error",
            code="invalid_platform",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    integrations = _find_integrations(team.id, app_id)
    if not integrations:
        unconfigured_message = (
            f"No push integration found for app_id '{app_id}'. "
            "Please configure the integration in your PostHog project settings."
        )
        rejections_this_window = _unconfigured_rejection_count(team.id)
        if rejections_this_window == 1:
            # Once per team per window, so the log names the project and app_id behind a flood without
            # emitting a line per device launch. The counter above carries the volume.
            logger.warning("push_subscription_unconfigured", team_id=team.id, app_id=app_id, platform=platform)
        if rejections_this_window > _UNCONFIGURED_THROTTLE_LIMIT:
            throttled = _rejection(
                request,
                unconfigured_message,
                type="throttled_error",
                code="throttled",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            throttled["Retry-After"] = str(_UNCONFIGURED_THROTTLE_WINDOW_SECONDS)
            return throttled
        return _rejection(
            request,
            unconfigured_message,
            type="validation_error",
            code="integration_not_found",
            status_code=status.HTTP_400_BAD_REQUEST,
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
            return _rejection(
                request,
                "A valid identity token is required for this device. Your backend must sign a "
                "short-lived token for the signed-in user with the key configured for this "
                "channel's identity verification.",
                type="authentication_error",
                code="identity_verification_failed",
                status_code=status.HTTP_401_UNAUTHORIZED,
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
        logger.exception("push_subscription_capture_failed", team_id=team.id, app_id=app_id, operation=operation)
        return _rejection(
            request,
            failure_message,
            type="server_error",
            code="capture_failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
