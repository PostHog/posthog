"""Imports automations from other messaging tools as draft workflows, and reads back what each import left out."""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User

from products.workflows.backend.facade.contracts import ImportOptions
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel, WorkflowImportSource, WorkflowImportStatus
from products.workflows.backend.facade.workflow_imports import import_for_workflow
from products.workflows.backend.presentation.views.workflow_import_drafts import import_campaign

MAX_CAMPAIGNS_PER_IMPORT = 50


class CustomerioCampaignSerializer(serializers.Serializer):
    campaign = serializers.DictField(
        help_text=(
            "The `campaign` object from Customer.io's `GET /v1/environments/{environment_id}/campaigns/{campaign_id}` "
            "(Journeys UI API, what the Customer.io CLI and MCP read). Must include `id`, `type`, `edges` and the "
            "trigger fields."
        )
    )
    actions = serializers.ListField(
        child=serializers.DictField(),
        help_text="The top-level `actions` array from the same response, every step of the automation.",
    )
    templates = serializers.JSONField(
        required=False,
        help_text=(
            "The message templates the actions point at, from `GET /v1/environments/{environment_id}/templates/"
            "{template_id}`: a list of template objects, or an object keyed by template id. Without them, messages "
            "import with empty content."
        ),
    )

    def validate_campaign(self, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("id") is None:
            raise serializers.ValidationError("The campaign needs its Customer.io `id`.")
        return value


class WorkflowImportRequestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=WorkflowImportSource.choices,
        help_text="The tool the automations come from.",
    )
    campaigns = CustomerioCampaignSerializer(
        many=True,
        help_text=f"The automations to import, at most {MAX_CAMPAIGNS_PER_IMPORT}. People are never read from these objects.",
    )
    snippets = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        default=dict,
        help_text='Customer.io snippet name to its content, inlined where a message uses `{% snippet "name" %}`.',
    )
    segment_cohorts = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        default=dict,
        help_text=(
            "Customer.io segment id to the PostHog cohort that replaces it. Segment triggers and segment "
            "conditions with no cohort here are left for the team to set."
        ),
    )

    def validate_campaigns(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not value:
            raise serializers.ValidationError("Pass at least one automation.")
        if len(value) > MAX_CAMPAIGNS_PER_IMPORT:
            raise serializers.ValidationError(f"Import at most {MAX_CAMPAIGNS_PER_IMPORT} automations at a time.")
        return value

    dry_run = serializers.BooleanField(
        default=False,
        help_text="When true, translate and check the automations but save nothing, to preview the import.",
    )


class WorkflowImportNoteSerializer(serializers.Serializer):
    level = serializers.ChoiceField(
        choices=WorkflowImportNoteLevel.choices,
        help_text=(
            "`approximated`: the step behaves differently in PostHog. `unsupported`: the setting was left out. "
            "`needs_input`: the team must set something before enabling."
        ),
    )
    message = serializers.CharField(help_text="What changed or was left out, and what to do about it.")
    step_id = serializers.CharField(allow_null=True, help_text="The workflow step the note is about, or null.")
    step_name = serializers.CharField(allow_null=True, help_text="That step's name, or null.")


class WorkflowImportResultSerializer(serializers.Serializer):
    source_id = serializers.CharField(help_text="The automation's id in Customer.io.")
    name = serializers.CharField(help_text="The automation's name.")
    status = serializers.ChoiceField(
        choices=WorkflowImportStatus.choices,
        help_text=(
            "`preview` when dry_run is set, `created` or `updated` for a saved draft, `skipped` when an earlier "
            "import of it is no longer a draft, `failed` when the draft does not pass the workflow checks."
        ),
    )
    workflow_id = serializers.CharField(allow_null=True, help_text="The draft workflow's id, when one was saved.")
    notes = WorkflowImportNoteSerializer(many=True, help_text="What the import changed or left out.")
    validation_errors = serializers.ListField(
        child=serializers.CharField(), help_text="Why the draft failed the workflow checks, for `failed`."
    )


class WorkflowImportResponseSerializer(serializers.Serializer):
    results = WorkflowImportResultSerializer(many=True, help_text="One result per automation, in request order.")


class WorkflowImportRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="The import record's id.")
    source = serializers.CharField(read_only=True, help_text="The tool the workflow was imported from.")  # type: ignore[assignment]
    source_id = serializers.CharField(read_only=True, help_text="The automation's id in that tool.")
    source_name = serializers.CharField(read_only=True, help_text="The automation's name in that tool.")
    hog_flow = serializers.UUIDField(source="hog_flow_id", read_only=True, allow_null=True, help_text="The workflow.")
    notes = WorkflowImportNoteSerializer(many=True, read_only=True, help_text="What the import changed or left out.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the workflow was last imported.")


class WorkflowImportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "hog_flow"
    serializer_class = WorkflowImportRequestSerializer
    scope_object_read_actions = ["for_workflow"]

    @validated_request(
        WorkflowImportRequestSerializer,
        responses={200: OpenApiResponse(response=WorkflowImportResponseSerializer)},
        summary="Import Customer.io automations as draft workflows",
        description=(
            "Turns Customer.io automations into draft workflows. Pass each automation as Customer.io's Journeys UI "
            "API returns it, with the templates its messages use. Each result lists what the import changed or "
            "left out. Importing an automation again updates its draft, unless that workflow is no longer a draft. "
            "Set dry_run to preview without saving."
        ),
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        user = cast(User, request.user)
        options = ImportOptions(
            snippets=dict(data["snippets"]),
            segment_cohorts={str(key): int(value) for key, value in data["segment_cohorts"].items()},
        )
        results = [import_campaign(self.team, user, payload, options, data["dry_run"]) for payload in data["campaigns"]]
        report_user_action(
            user,
            "workflows import run",
            {
                "source": data["source"],
                "dry_run": data["dry_run"],
                "campaign_count": len(results),
                "statuses": [result["status"] for result in results],
                "note_count": sum(len(result["notes"]) for result in results),
            },
            team=self.team,
            request=request,
        )
        return Response(WorkflowImportResponseSerializer({"results": results}).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("hog_flow_id", type=str, required=True, description="The workflow to read the import of.")
        ],
        responses={
            200: OpenApiResponse(response=WorkflowImportRecordSerializer),
            404: OpenApiResponse(description="The workflow was not imported."),
        },
        summary="Read what importing a workflow changed or left out",
    )
    @action(detail=False, methods=["get"], url_path="for_workflow")
    def for_workflow(self, request: Request, **kwargs: Any) -> Response:
        try:
            hog_flow_id = UUID(str(request.query_params.get("hog_flow_id")))
        except ValueError:
            raise ValidationError({"hog_flow_id": "Pass the workflow's id."})
        record = import_for_workflow(self.team, hog_flow_id)
        if record is None:
            raise NotFound("This workflow was not imported.")
        return Response(WorkflowImportRecordSerializer(record).data)
