from datetime import UTC, datetime
from typing import Any

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

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
from posthog.utils import decompress
from posthog.utils_cors import cors_response

VALID_PLATFORMS = ("android", "ios")

# A device registration payload is a handful of short string fields (distinct_id, device_token,
# platform, app_id, api_key) — well under 1 KiB. Cap the raw request body far above that but far below
# Django's global limit, so a compressed body can't inflate into a memory-exhaustion payload when
# load_data_from_request decompresses it.
MAX_BODY_BYTES = 16 * 1024

# Shared instance: deriving the encryption keys runs PBKDF2 (100k iterations per key) and is
# cached on the instance, so a module-level singleton avoids re-deriving on every request.
_encrypted_fields = EncryptedFieldMixin()


# Resolve the integration from the app_id alone, not the device platform. An app_id is either a
# Firebase project_id or an APNs bundle_id, so a device can register with either provider regardless
# of its OS — e.g. an iOS device delivering through Firebase registers with the Firebase project_id.
# (The client still sends its platform, but it's metadata, not what selects the provider.)
def _find_integration(team_id: int, app_id: str) -> Integration | None:
    return (
        Integration.objects.filter(team_id=team_id)
        .filter(Q(kind="firebase", config__project_id=app_id) | Q(kind="apns", config__bundle_id=app_id))
        .only("id")
        .first()
    )


# load_data_from_request reads the request body only for POST (other methods read the ?data= query
# param), but both register (POST) and unregister (DELETE) send a JSON body — so read and decompress
# the body directly for either method, mirroring that helper's POST branch.
def _load_json_body(request: Request) -> Any:
    compression = (
        request.GET.get("compression") or request.POST.get("compression") or request.headers.get("content-encoding", "")
    ).lower()
    return decompress(request.body, compression)


@csrf_exempt
def push_subscriptions(request: Request):
    if request.method == "OPTIONS":
        # cors_response advertises GET, POST, OPTIONS by default; also allow DELETE so a browser
        # preflight for the unregister call isn't rejected before reaching the DELETE branch.
        preflight = cors_response(request, HttpResponse(""))
        preflight["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return preflight

    if request.method not in ("POST", "DELETE"):
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Only POST and DELETE requests are supported.",
                type="validation_error",
                code="method_not_allowed",
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            ),
        )

    # POST registers a device (stores the token); DELETE unregisters it (unsets the property) so a
    # logged-out user stops receiving another user's notifications on a shared device.
    is_register = request.method == "POST"

    if len(request.body) > MAX_BODY_BYTES:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Request body too large.",
                type="validation_error",
                code="request_too_large",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ),
        )

    try:
        data = _load_json_body(request)
    except (RequestParsingError, UnspecifiedCompressionFallbackParsingError):
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Invalid JSON body.",
                type="validation_error",
                code="invalid_json",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    if not isinstance(data, dict):
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Invalid JSON body.",
                type="validation_error",
                code="invalid_json",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    api_key = get_token(data, request)
    if not api_key:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Project token not provided. You can find your project token in your PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    team = Team.objects.get_team_from_cache_or_token(api_key)
    if not team:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Invalid project token.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    distinct_id = data.get("distinct_id")
    device_token = data.get("device_token")
    platform = data.get("platform")
    app_id = data.get("app_id")

    # distinct_id + app_id identify which person property to set or unset, so both methods need them.
    # device_token + platform describe the device being stored, so they're required only to register.
    required_fields = [("distinct_id", distinct_id), ("app_id", app_id)]
    if is_register:
        required_fields += [("device_token", device_token), ("platform", platform)]
    missing_fields = [field_name for field_name, value in required_fields if not value or not isinstance(value, str)]
    if missing_fields:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                f"Missing required fields: {', '.join(missing_fields)}.",
                type="validation_error",
                code="missing_fields",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    assert isinstance(distinct_id, str)
    assert isinstance(app_id, str)

    if is_register:
        assert isinstance(platform, str)
        if platform not in VALID_PLATFORMS:
            return cors_response(
                request,
                generate_exception_response(
                    "push_subscriptions",
                    f"Invalid platform. Must be one of: {', '.join(VALID_PLATFORMS)}.",
                    type="validation_error",
                    code="invalid_platform",
                    status_code=status.HTTP_400_BAD_REQUEST,
                ),
            )

    integration = _find_integration(team.id, app_id)
    if not integration:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                f"No push integration found for app_id '{app_id}'. "
                "Please configure the integration in your PostHog project settings.",
                type="validation_error",
                code="integration_not_found",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    property_key = f"$device_push_subscription_{app_id}"
    if is_register:
        assert isinstance(device_token, str)
        # Store the token encrypted; the send path rejects any value that fails to decrypt.
        person_properties: dict = {"$set": {property_key: _encrypted_fields.encrypt(device_token)}}
    else:
        # Unregister mirrors the send path's dead-token pruning: unset the person property so the
        # device stops matching. There is one subscription per app per person, so app_id is enough.
        person_properties = {"$unset": [property_key]}

    try:
        capture_internal(
            token=team.api_token,
            event_name="$set",
            event_source="push_subscriptions",
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties=person_properties,
            process_person_profile=True,
        )
    except Exception:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Failed to store push subscription." if is_register else "Failed to remove push subscription.",
                type="server_error",
                code="capture_failed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        )

    if is_register:
        return cors_response(
            request,
            JsonResponse({"distinct_id": distinct_id, "platform": platform}, status=status.HTTP_200_OK),
        )
    return cors_response(request, JsonResponse({"distinct_id": distinct_id}, status=status.HTTP_200_OK))
