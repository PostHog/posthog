from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from django.db import models

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.surveys.backend.facade.api import DesktopFeedbackUnavailable, submit_desktop_feedback

MAX_FEEDBACK_IMAGE_BYTES = 512 * 1024


class DesktopFeedbackSource(models.TextChoices):
    LEAVE_FEEDBACK = "Generic (Leave feedback button)"
    POSTHOG_WEB = "Visiting PostHog web"


class DesktopFeedbackServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Could not send feedback. Please try again."


class DesktopFeedbackThrottle(UserRateThrottle):
    rate = "10/minute"


class DesktopFeedbackRequestSerializer(serializers.Serializer):
    response = serializers.CharField(
        max_length=4000,
        trim_whitespace=True,
        help_text="Feedback text entered by the user.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # Field name shadows DRF Field.source.
        choices=DesktopFeedbackSource.choices,
        help_text="Desktop surface that opened the feedback form.",
    )
    feedback_view = serializers.CharField(
        max_length=100,
        help_text="Desktop view that was active when the feedback form opened.",
    )
    feedback_task_id = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Task that was active when the feedback form opened.",
    )
    feedback_folder_id = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Folder that was active when the feedback form opened.",
    )
    feedback_app_logs = serializers.CharField(
        required=False,
        max_length=20_000,
        help_text="Recent Desktop logs that the user chose to include.",
    )
    app_version = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Version of PostHog Desktop that submitted the feedback.",
    )
    session_id = serializers.UUIDField(
        required=False,
        help_text="PostHog session recording identifier for the Desktop session.",
    )
    screenshot = serializers.ImageField(
        required=False,
        max_length=1000,
        help_text="Screenshot that the user chose to include.",
    )
    image_1 = serializers.ImageField(
        required=False,
        max_length=1000,
        help_text="First image that the user attached.",
    )
    image_2 = serializers.ImageField(
        required=False,
        max_length=1000,
        help_text="Second image that the user attached.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for field_name in ("screenshot", "image_1", "image_2"):
            file = attrs.get(field_name)
            if file is not None and file.size > MAX_FEEDBACK_IMAGE_BYTES:
                raise serializers.ValidationError({field_name: "Feedback images must be smaller than 512 KB."})
        return attrs


class DesktopFeedbackResponseSerializer(serializers.Serializer):
    accepted = serializers.BooleanField(help_text="Whether the feedback response was accepted.")
    response_id = serializers.UUIDField(help_text="Identifier of the survey response event.")


class DesktopFeedbackViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "survey"
    permission_classes = [IsAuthenticated]
    throttle_classes = [DesktopFeedbackThrottle]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = DesktopFeedbackRequestSerializer
    pagination_class = None

    @validated_request(
        request_serializer=DesktopFeedbackRequestSerializer,
        responses={
            201: OpenApiResponse(response=DesktopFeedbackResponseSerializer),
            400: OpenApiResponse(description="The feedback or an attachment is invalid."),
            503: OpenApiResponse(description="The feedback could not be stored or accepted."),
        },
        summary="Submit Desktop feedback",
        description="Stores selected attachments and submits one response to the PostHog Desktop feedback survey.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        files: dict[str, UploadedFile] = {
            property_name: data[property_name]
            for property_name in ("screenshot", "image_1", "image_2")
            if property_name in data
        }
        try:
            response_id = submit_desktop_feedback(user=cast(User, request.user), data=data, files=files)
        except DesktopFeedbackUnavailable as error:
            raise DesktopFeedbackServiceUnavailable from error
        except Exception as error:
            raise DesktopFeedbackServiceUnavailable from error

        return Response(
            DesktopFeedbackResponseSerializer({"accepted": True, "response_id": response_id}).data,
            status=status.HTTP_201_CREATED,
        )
