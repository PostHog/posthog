import time
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers, viewsets
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.scopes import APIScopeObject

from products.workflows.backend.facade.email_drafts import (
    EmailDraftFallbackReason,
    EmailDraftOrigin,
    EmailDraftSource,
    EmailDraftSourceNotFound,
    write_email_draft,
)

# The draft is written from the source entity, so reading it needs the same access as opening it.
_SOURCE_RESOURCE: dict[EmailDraftSource, APIScopeObject] = {
    EmailDraftSource.ERROR_TRACKING: "error_tracking",
    EmailDraftSource.EARLY_ACCESS: "early_access_feature",
    EmailDraftSource.SURVEY: "survey",
    EmailDraftSource.FEATURE_FLAG: "feature_flag",
    EmailDraftSource.COHORT: "cohort",
}


class EmailDraftRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=EmailDraftSource.choices,
        help_text="The kind of entity the email is about.",
    )
    source_id = serializers.CharField(
        max_length=200,
        help_text="ID of that entity: an issue, early access feature or survey UUID, or a feature flag or cohort ID.",
    )


class EmailDraftSerializer(serializers.Serializer):
    subject = serializers.CharField(help_text="Email subject line. Empty when there is nothing to draft from.")
    preheader = serializers.CharField(help_text="Preview text shown after the subject in most inboxes.")
    html = serializers.CharField(help_text="Email body as HTML paragraphs.")
    text = serializers.CharField(help_text="Plain-text version of the body.")
    generated_by = serializers.ChoiceField(
        choices=EmailDraftOrigin.choices,
        help_text="Whether a model wrote the draft or it came from the fixed template for this source.",
    )
    template_reason = serializers.ChoiceField(
        source="fallback_reason",
        choices=EmailDraftFallbackReason.choices,
        allow_null=True,
        help_text="Why the template was used instead of a model draft. Null for a model draft.",
    )


class WorkflowEmailDraftViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    serializer_class = EmailDraftRequestSerializer

    @validated_request(
        EmailDraftRequestSerializer,
        responses={200: OpenApiResponse(response=EmailDraftSerializer)},
        summary="Draft an email about an error, feature, survey, flag or cohort",
        description=(
            "Write a first draft of an email to the people an entity points at. A model writes it when the "
            "project has AI drafts on and the organization approved AI data processing; otherwise, or when the "
            "model fails, the fixed template for the source is returned. Nothing is saved."
        ),
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        source = EmailDraftSource(request.validated_data["source"])
        if not self.user_access_control.check_access_level_for_resource(_SOURCE_RESOURCE[source], "viewer"):
            raise exceptions.PermissionDenied("You don't have access to this item.")
        started = time.monotonic()
        try:
            draft = write_email_draft(self.team, source, request.validated_data["source_id"])
        except EmailDraftSourceNotFound:
            raise exceptions.NotFound("We couldn't find that item in this project.")
        report_user_action(
            cast(User, request.user),
            "workflows email draft generated",
            {
                "source": source.value,
                "generated_by": draft.generated_by.value,
                "template_reason": draft.fallback_reason.value if draft.fallback_reason else None,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
            team=self.team,
            request=request,
        )
        return Response(EmailDraftSerializer(draft).data)
