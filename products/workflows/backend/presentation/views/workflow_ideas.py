from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.workflows.backend.facade.contracts import (
    WorkflowIdeaAlreadyResolved,
    WorkflowIdeaNotFound,
    WorkflowIdeaWorkflowMismatch,
)
from products.workflows.backend.facade.enums import WorkflowIdeaStatus, WorkflowIdeaValueTier
from products.workflows.backend.facade.workflow_ideas import accept_idea, dismiss_idea, list_open_ideas, mark_viewed


@extend_schema_field(OpenApiTypes.OBJECT)
class WorkflowDefinitionField(serializers.JSONField):
    pass


class WorkflowIdeaEvidenceSerializer(serializers.Serializer):
    trigger_event = serializers.CharField(help_text="The project event that starts the workflow.")
    goal_events = serializers.ListField(
        child=serializers.CharField(), help_text="Events that count as the workflow's goal. Reaching one exits it."
    )
    baseline_rate = serializers.FloatField(
        allow_null=True,
        help_text="Share of people who reach the goal within 7 days with no message, from 0 to 1. Null when unmeasured.",
    )
    reachable_people = serializers.IntegerField(
        help_text="People a month with an email address who hit the trigger and did not reach the goal."
    )
    measured_at = serializers.CharField(help_text="ISO date the numbers were measured.")


class WorkflowIdeaSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="The idea's id.")
    key = serializers.CharField(help_text="Stable name of the idea within the project.")
    title = serializers.CharField(help_text="Short name of the suggested workflow.")
    rationale = serializers.CharField(help_text="Why this workflow is worth running.")
    value_tier = serializers.ChoiceField(
        choices=WorkflowIdeaValueTier.choices, help_text="How close the workflow's goal is to revenue."
    )
    status = serializers.ChoiceField(choices=WorkflowIdeaStatus.choices, help_text="Where the idea stands.")
    evidence = WorkflowIdeaEvidenceSerializer(help_text="The numbers behind the idea.")
    definition = WorkflowDefinitionField(
        help_text="The workflow to create, in the shape the workflow create endpoint takes. Nothing is saved until "
        "the caller creates it there and then calls accept."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When PostHog made the idea.")
    hog_flow_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="The draft workflow made from this idea, once it is used."
    )


# many=False: the `list` action returns one {"results": [...]} body, not an array of them.
@extend_schema_serializer(many=False)
class WorkflowIdeaListSerializer(serializers.Serializer):
    results = WorkflowIdeaSerializer(
        many=True, help_text="Ideas still waiting for a decision, the one to try first at the top."
    )


class WorkflowIdeaAcceptSerializer(serializers.Serializer):
    hog_flow_id = serializers.UUIDField(
        help_text="The draft workflow created from this idea's definition, with origin_product 'ideas'."
    )


class WorkflowIdeaDismissSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, help_text="Optional reason the person gave."
    )


class WorkflowIdeaViewedSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), help_text="Ideas that were shown on screen.")


class WorkflowIdeaViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Whole workflows PostHog suggests to the project. Accepting one records the draft made from it."""

    scope_object = "hog_flow"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["accept", "dismiss", "viewed"]

    @extend_schema(operation_id="workflow_ideas_list", responses={200: WorkflowIdeaListSerializer})
    def list(self, request: Request, **kwargs: Any) -> Response:
        rows = list_open_ideas(team_id=self.team_id)
        return Response({"results": WorkflowIdeaSerializer(rows, many=True).data})

    @extend_schema(
        operation_id="workflow_ideas_accept",
        request=WorkflowIdeaAcceptSerializer,
        responses={200: WorkflowIdeaSerializer},
    )
    @action(detail=True, methods=["post"])
    def accept(self, request: Request, pk: str, **kwargs: Any) -> Response:
        payload = WorkflowIdeaAcceptSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            row = accept_idea(
                team_id=self.team_id,
                idea_id=pk,
                hog_flow_id=str(payload.validated_data["hog_flow_id"]),
                user_id=cast(User, request.user).id,
            )
        except WorkflowIdeaNotFound:
            raise NotFound()
        except WorkflowIdeaWorkflowMismatch:
            raise ValidationError({"hog_flow_id": "That workflow was not created from an idea in this project."})
        except WorkflowIdeaAlreadyResolved:
            return Response({"detail": "This idea was already resolved."}, status=status.HTTP_409_CONFLICT)
        return Response(WorkflowIdeaSerializer(row).data)

    @extend_schema(
        operation_id="workflow_ideas_dismiss",
        request=WorkflowIdeaDismissSerializer,
        responses={200: WorkflowIdeaSerializer},
    )
    @action(detail=True, methods=["post"])
    def dismiss(self, request: Request, pk: str, **kwargs: Any) -> Response:
        payload = WorkflowIdeaDismissSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            row = dismiss_idea(
                team_id=self.team_id,
                idea_id=pk,
                user_id=cast(User, request.user).id,
                reason=payload.validated_data.get("reason", ""),
            )
        except WorkflowIdeaNotFound:
            raise NotFound()
        except WorkflowIdeaAlreadyResolved:
            return Response({"detail": "This idea was already resolved."}, status=status.HTTP_409_CONFLICT)
        return Response(WorkflowIdeaSerializer(row).data)

    @extend_schema(operation_id="workflow_ideas_viewed", request=WorkflowIdeaViewedSerializer, responses={204: None})
    @action(detail=False, methods=["post"])
    def viewed(self, request: Request, **kwargs: Any) -> Response:
        payload = WorkflowIdeaViewedSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        mark_viewed(team_id=self.team_id, idea_ids=[str(i) for i in payload.validated_data["ids"]])
        return Response(status=status.HTTP_204_NO_CONTENT)
