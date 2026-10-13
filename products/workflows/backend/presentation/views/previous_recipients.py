from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers, viewsets
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.workflows.backend.facade.previous_recipients import (
    TooManyPreviousRecipients,
    build_previous_recipients_cohort,
)


class PreviousRecipientsRequestSerializer(serializers.Serializer):
    source_record = serializers.RegexField(
        r"^[a-z_]+:[A-Za-z0-9_-]+$",
        max_length=255,
        help_text="The record the new email is about, as '<kind>:<id>', for example 'early_access:<uuid>' or 'cohort:42'.",
    )
    cohort_name = serializers.CharField(
        max_length=400,
        help_text="Name for the cohort of people already emailed, shown in the broadcast's recipients.",
    )


class PreviousRecipientsSerializer(serializers.Serializer):
    cohort_id = serializers.IntegerField(
        allow_null=True,
        help_text="Static cohort of the people already emailed from this record. Null when nobody was emailed yet.",
    )
    people = serializers.IntegerField(help_text="How many people the cohort holds.")


class WorkflowPreviousRecipientsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    serializer_class = PreviousRecipientsRequestSerializer

    def dangerously_get_required_scopes(self, request: Any, view: Any) -> list[str] | None:
        # The answer names people and writes a cohort, so a token needs both on top of workflow write.
        if self.action == "create":
            return ["hog_flow:write", "person:read", "cohort:write"]
        return None

    @validated_request(
        PreviousRecipientsRequestSerializer,
        responses={200: OpenApiResponse(response=PreviousRecipientsSerializer)},
        summary="Save the people already emailed about a record as a cohort",
        description=(
            "Find everyone that earlier workflows started from the same record already emailed, and save them "
            "as a static cohort, so a new broadcast about that record can leave them out. Reads the sent-email "
            "log, which keeps 30 days. Returns a null cohort when nobody was emailed yet."
        ),
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        if not self.user_access_control.check_access_level_for_resource("cohort", "editor"):
            raise exceptions.PermissionDenied("You need editor access to cohorts to skip people who got this email.")
        try:
            result = build_previous_recipients_cohort(
                team=self.team,
                user=cast(User, request.user),
                source_record=request.validated_data["source_record"],
                cohort_name=request.validated_data["cohort_name"],
            )
        except TooManyPreviousRecipients as error:
            raise exceptions.ValidationError(
                f"More than {error.limit:,} people already got this email, which is too many to skip here."
            )
        return Response(PreviousRecipientsSerializer(result).data)
