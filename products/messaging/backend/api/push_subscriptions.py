import json
from datetime import UTC, datetime

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from rest_framework.request import Request

from posthog.api.capture import capture_internal
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.utils_cors import cors_response

VALID_PLATFORMS = ("android", "ios")

PLATFORM_TO_INTEGRATION_KIND: dict[str, str] = {
    "android": "firebase",
    "ios": "apns",
}

APP_ID_CONFIG_KEY: dict[str, str] = {
    "firebase": "project_id",
    "apns": "bundle_id",
}


# We lookup integrations based on the app_id provided by the client, which corresponds to
# the `project_id` for Firebase and `bundle_id` for APNS. This allows us to support multiple
# push integrations per project, and also provides a more intuitive way for the SDKs to set up
# push subscriptions without needing to reference internal integration IDs.
def _find_integration(team_id: int, platform: str, app_id: str) -> Integration | None:
    kind = PLATFORM_TO_INTEGRATION_KIND.get(platform)
    if not kind:
        return None

    config_key = APP_ID_CONFIG_KEY[kind]

    return (
        Integration.objects.filter(
            team_id=team_id,
            kind=kind,
            **{f"config__{config_key}": app_id},
        )
        .only("id")
        .first()
    )


@csrf_exempt
def push_subscriptions(request: Request):
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    if request.method != "POST":
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Only POST requests are supported.",
                type="validation_error",
                code="method_not_allowed",
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            ),
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
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

    missing_fields = [
        field_name
        for field_name, value in [
            ("distinct_id", distinct_id),
            ("device_token", device_token),
            ("platform", platform),
            ("app_id", app_id),
        ]
        if not value
    ]
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

    integration = _find_integration(team.id, platform, app_id)
    if not integration:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                f"No push integration found for app_id '{app_id}' on platform '{platform}'. "
                "Please configure the integration in your PostHog project settings.",
                type="validation_error",
                code="integration_not_found",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    encrypted_token = EncryptedFieldMixin().encrypt(device_token)
    property_key = f"$device_push_subscription_{app_id}"

    try:
        capture_internal(
            token=team.api_token,
            event_name="$set",
            event_source="push_subscriptions",
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties={"$set": {property_key: encrypted_token}},
            process_person_profile=True,
        )
    except Exception:
        return cors_response(
            request,
            generate_exception_response(
                "push_subscriptions",
                "Failed to store push subscription.",
                type="server_error",
                code="capture_failed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
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
