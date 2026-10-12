import base64
import binascii
from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models import Team, User
from posthog.slack.formatting import channel_id_from_target

from products.workflows.backend.facade.contracts import WorkflowRef
from products.workflows.backend.facade.slack_preview import (
    EmailPreviewImage,
    SlackDestination,
    WorkflowPreview,
    WorkflowPreviewShareError,
    find_team_slack_integration,
    image_extension,
    parse_slack_thread_link,
    share_workflow_preview_to_slack,
)

MAX_EMAIL_PREVIEW_BYTES = 1024 * 1024
MAX_EMAIL_PREVIEWS = 10
MAX_EMAIL_PREVIEW_BASE64_LENGTH = 4 * ((MAX_EMAIL_PREVIEW_BYTES + 2) // 3)


class EmailPreviewImageSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300, help_text="Caption shown under the image in Slack.")
    image_base64 = serializers.CharField(
        help_text="The rendered email as a base64-encoded PNG or JPEG, at most 1 MB once decoded.",
    )

    def validate_image_base64(self, value: str) -> bytes:
        if len(value) > MAX_EMAIL_PREVIEW_BASE64_LENGTH:
            raise serializers.ValidationError("The image is larger than 1 MB.")
        try:
            image = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise serializers.ValidationError("The image is not valid base64.")
        if image_extension(image) is None:
            raise serializers.ValidationError("The image must be a PNG or JPEG.")
        return image


class SharePreviewToSlackRequestSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the project's Slack integration to post with.")
    channel = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Slack channel to post in: a channel ID, or the channel picker's `ID|#name` value. "
        "Ignored when `thread_link` is set.",
    )
    thread_link = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=1000,
        help_text="Link to a Slack message. The preview is posted as a reply in that message's thread.",
    )
    note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=3000, help_text="Message to the team."
    )
    outline = serializers.ListField(
        child=serializers.CharField(max_length=500, trim_whitespace=False),
        max_length=200,
        default=list,
        help_text="The workflow's steps, one line each, in the order they run.",
    )
    emails = serializers.ListField(
        child=EmailPreviewImageSerializer(),
        max_length=MAX_EMAIL_PREVIEWS,
        default=list,
        help_text="Rendered previews of the workflow's emails, attached to the Slack message in order.",
    )

    def validate_thread_link(self, value: str | None) -> SlackDestination | None:
        if not value:
            return None
        destination = parse_slack_thread_link(value)
        if destination is None:
            raise serializers.ValidationError("Paste a link to a Slack message, copied with 'Copy link'.")
        return destination

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        destination = attrs.get("thread_link") or (
            SlackDestination(channel=channel_id_from_target(attrs["channel"])) if attrs.get("channel") else None
        )
        if destination is None:
            raise serializers.ValidationError("Pick a Slack channel or paste a link to a Slack thread.")
        attrs["destination"] = destination
        return attrs


class SharePreviewToSlackResponseSerializer(serializers.Serializer):
    channel = serializers.CharField(help_text="ID of the Slack channel the preview was posted in.")
    thread_ts = serializers.CharField(
        allow_null=True, help_text="Timestamp of the thread the preview was posted in, or null for a new message."
    )


class HogFlowSlackPreviewMixin:
    team: Team

    def _workflow_ref(self) -> WorkflowRef:
        raise NotImplementedError

    @extend_schema(
        operation_id="hog_flows_share_preview_to_slack",
        request=SharePreviewToSlackRequestSerializer,
        responses={200: SharePreviewToSlackResponseSerializer},
    )
    @action(detail=True, methods=["POST"], pagination_class=None, filter_backends=[], url_path="share_preview_to_slack")
    def share_preview_to_slack(self, request: Request, **kwargs: Any) -> Response:
        """Post a preview of this workflow, its steps and rendered emails, to a Slack channel or thread."""
        workflow = self._workflow_ref()
        params = SharePreviewToSlackRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        integration = find_team_slack_integration(self.team, data["integration_id"])
        if integration is None:
            raise exceptions.ValidationError("Slack integration not found.")

        destination: SlackDestination = data["destination"]
        try:
            share_workflow_preview_to_slack(
                integration=integration,
                workflow=workflow,
                shared_by=cast(User, request.user),
                destination=destination,
                preview=WorkflowPreview(
                    note=data["note"],
                    outline=data["outline"],
                    emails=[
                        EmailPreviewImage(title=email["title"], content=email["image_base64"])
                        for email in data["emails"]
                    ],
                ),
            )
        except WorkflowPreviewShareError as error:
            raise exceptions.ValidationError(str(error))

        return Response(
            SharePreviewToSlackResponseSerializer(
                {"channel": destination.channel, "thread_ts": destination.thread_ts}
            ).data
        )
