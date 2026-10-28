from typing import Any, cast

from django.db import models

import structlog
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import EventSource, get_event_source, report_user_action
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.workflows.backend.facade.contracts import (
    BuiltSuggestion,
    DataSuggestionNotFound,
    DataSuggestionsResult,
    WorkflowIdeaAlreadyResolved,
)
from products.workflows.backend.facade.data_suggestions import (
    build_caller,
    email_sender_ready,
    get_data_suggestions,
    get_premade_workflow,
    needs_new_build,
    needs_new_generation,
    save_premade_draft,
    start_build,
    start_data_suggestions,
)
from products.workflows.backend.presentation.views.data_suggestion_drafts import save_draft, validated_draft

logger = structlog.get_logger(__name__)


class DataSuggestionStepKind(models.TextChoices):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    SLACK = "slack"
    WEBHOOK = "webhook"
    DELAY = "delay"
    WAIT_UNTIL = "wait_until"
    BRANCH = "branch"
    SPLIT = "split"
    ACTION = "action"


class DataSuggestionStage(models.TextChoices):
    SIGNUP = "signup"
    ONBOARDING = "onboarding"
    TRIAL = "trial"
    PURCHASE = "purchase"
    CHURN_RISK = "churn_risk"
    FAILURE = "failure"
    SUPPORT = "support"
    OTHER = "other"


class DataSuggestionsStatus(models.TextChoices):
    READY = "ready"
    GENERATING = "generating"
    AI_NOT_APPROVED = "ai_not_approved"
    UNAVAILABLE = "unavailable"


class DataSuggestionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Opaque id of this suggestion, valid while the suggestions stay cached.")
    name = serializers.CharField(help_text="Suggested workflow name, written by AI from the project's events.")
    description = serializers.CharField(help_text="One sentence on what the workflow does.")
    reason = serializers.CharField(help_text="One sentence on why the workflow fits this project.")
    trigger_event = serializers.CharField(help_text="The project event that starts the workflow.")
    weekly_count = serializers.IntegerField(help_text="How often the trigger event fired in the last 7 days.")
    stage = serializers.ChoiceField(
        choices=DataSuggestionStage.choices,
        help_text="The customer lifecycle stage the trigger event marks. Suggestions are ranked by stage first, "
        "so welcome and onboarding flows come before busier events.",
    )
    step_outline = serializers.ListField(
        child=serializers.ChoiceField(choices=DataSuggestionStepKind.choices),
        help_text="The main planned step kinds after the trigger, in order.",
    )
    premade = serializers.BooleanField(
        help_text="Whether PostHog prepared this suggestion ahead of time with its workflow already built. Build it "
        "with save_draft to save the draft and stop offering the suggestion."
    )


class DataSuggestionsResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DataSuggestionsStatus.choices,
        help_text="ready when suggestions were made (the list can still be empty), generating while a background "
        "run makes them (poll current until it ends), ai_not_approved when the organization has not approved AI "
        "data processing, unavailable when nothing was made or the run failed.",
    )
    suggestions = DataSuggestionSerializer(
        many=True, help_text="Up to 3 suggested workflows, ranked by lifecycle stage and then by weekly volume."
    )
    email_sender_ready = serializers.SerializerMethodField(
        help_text="Whether the project has a verified email sender. Without one, an email workflow can be saved as a "
        "draft but cannot send until a sending domain is added and verified."
    )

    @extend_schema_field(serializers.BooleanField())
    def get_email_sender_ready(self, _result: object) -> bool:
        return bool(self.context.get("email_sender_ready"))


class DataSuggestionGenerateRequestSerializer(serializers.Serializer):
    refresh = serializers.BooleanField(
        default=False, help_text="Make new suggestions even when the cached ones are still valid."
    )


class DataSuggestionBuildRequestSerializer(serializers.Serializer):
    suggestion_id = serializers.CharField(help_text="The id of a suggestion from the list endpoint.")
    retry = serializers.BooleanField(
        default=False,
        help_text="Start a new build when the last one failed. Leave it false when asking for a running build's status.",
    )
    save_draft = serializers.BooleanField(
        default=False,
        help_text="Save the built draft in the project and return its workflow_id. Blank settings, like a webhook "
        "URL, stay blank and are listed in missing_inputs. Leave it false to get the workflow back without saving.",
    )


class DataSuggestionBuildStatus(models.TextChoices):
    READY = "ready"
    BUILDING = "building"
    FAILED = "failed"


class DataSuggestionMissingInputSerializer(serializers.Serializer):
    step_id = serializers.CharField(help_text="The id of the workflow step (action) the setting belongs to.")
    step_name = serializers.CharField(help_text="The step's name, as the editor shows it.")
    field = serializers.CharField(
        help_text="The setting to fill, like 'Webhook URL', 'Email sender' or 'Condition: Is on a paid plan'."
    )


class DataSuggestionBuildResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DataSuggestionBuildStatus.choices,
        help_text="ready when the draft is built, building while a background build runs (call build again to "
        "check), failed when the plan did not produce a valid workflow. A failed result stays until a call sends "
        "retry.",
    )
    workflow = serializers.JSONField(
        allow_null=True,
        help_text="With status ready: a validated draft workflow (name, description, trigger, actions, edges, "
        "conversion, exit_condition) that the workflow create endpoint accepts from this caller. Saved only with "
        "save_draft. Null otherwise.",
    )
    uses_saved_template = serializers.BooleanField(help_text="Whether an email step reuses a saved email template.")
    workflow_id = serializers.CharField(
        allow_null=True,
        help_text="With status ready and save_draft: the id of the saved draft workflow. Null otherwise.",
    )
    missing_inputs = DataSuggestionMissingInputSerializer(
        many=True,
        help_text="With status ready: the settings the draft leaves blank, which must be filled before it is enabled.",
    )


class WorkflowDataSuggestionsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Workflow ideas written by AI from the project's own events. Both calls are free for the customer."""

    scope_object = "hog_flow"
    # These actions read the whole project and create drafts, so access to a single workflow is not enough.
    requires_resource_level_access = True
    scope_object_read_actions = ["current"]
    # Both calls can run ClickHouse and the models, so a read-only key cannot cause that spend.
    scope_object_write_actions = ["generate", "build"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # The cards carry the project's event names and weekly counts, so a key also needs the scope that reads them.
        access = "read" if self.action in self.scope_object_read_actions else "write"
        return [f"hog_flow:{access}", "query:read"]

    def get_throttles(self):
        # The AI budget is per user and shared with other AI features, so only a call that can run the LLM counts
        # against it. A generate call answered from the cache does not.
        if (self.action == "build" and self._starts_build()) or (
            self.action == "generate" and self._starts_generation()
        ):
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def _starts_build(self) -> bool:
        # Asking again while a build runs, or for a finished build, costs no model time, so only a new build counts.
        payload = DataSuggestionBuildRequestSerializer(data=self.request.data)
        return not payload.is_valid() or needs_new_build(
            team=self.team,
            suggestion_id=payload.validated_data["suggestion_id"],
            caller=build_caller(
                get_event_source(self.request).value,
                save=payload.validated_data["save_draft"],
                user_id=cast(User, self.request.user).id,
            ),
            retry=payload.validated_data["retry"],
        )

    def _starts_generation(self) -> bool:
        # Joining a run that is already going costs no model time, so it is not throttled. Invalid input is throttled.
        payload = DataSuggestionGenerateRequestSerializer(data=self.request.data)
        return not payload.is_valid() or needs_new_generation(team=self.team, refresh=payload.validated_data["refresh"])

    @extend_schema(operation_id="workflow_data_suggestions_current", responses={200: DataSuggestionsResponseSerializer})
    @action(detail=False, methods=["get"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        self._user(request)
        return self._suggestions_response(get_data_suggestions(team=self.team))

    @extend_schema(
        operation_id="workflow_data_suggestions_generate",
        request=DataSuggestionGenerateRequestSerializer,
        responses={200: DataSuggestionsResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def generate(self, request: Request, **kwargs: Any) -> Response:
        user = self._user(request)
        payload = DataSuggestionGenerateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = start_data_suggestions(team=self.team, user=user, refresh=payload.validated_data["refresh"])
        return self._suggestions_response(result)

    def _suggestions_response(self, result: DataSuggestionsResult) -> Response:
        # Read on every call rather than cached with the cards, so it changes as soon as a domain verifies.
        ready = email_sender_ready(team=self.team)
        return Response(DataSuggestionsResponseSerializer(result, context={"email_sender_ready": ready}).data)

    @extend_schema(
        operation_id="workflow_data_suggestions_build",
        request=DataSuggestionBuildRequestSerializer,
        responses={200: DataSuggestionBuildResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def build(self, request: Request, **kwargs: Any) -> Response:
        user = self._user(request)
        payload = DataSuggestionBuildRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        suggestion_id = payload.validated_data["suggestion_id"]
        save = payload.validated_data["save_draft"]
        event_source = get_event_source(request)
        try:
            built = self._premade_build(user, suggestion_id, save=save, event_source=event_source)
            if built is None:
                built = start_build(
                    team=self.team,
                    user=user,
                    suggestion_id=suggestion_id,
                    retry=payload.validated_data["retry"],
                    save=save,
                    event_source=event_source,
                )
        except WorkflowIdeaAlreadyResolved:
            return Response({"detail": "This suggestion was already used."}, status=status.HTTP_409_CONFLICT)
        except DataSuggestionNotFound:
            raise NotFound("This suggestion has expired. Refresh the page to get new ones.")
        return Response(DataSuggestionBuildResponseSerializer(built).data)

    def _premade_build(
        self, user: User, suggestion_id: str, *, save: bool, event_source: EventSource
    ) -> BuiltSuggestion | None:
        if not save:
            return get_premade_workflow(
                team=self.team,
                idea_id=suggestion_id,
                validate_draft=lambda team, workflow: validated_draft(team, workflow, event_source),
            )
        saved = save_premade_draft(
            team=self.team,
            user=user,
            idea_id=suggestion_id,
            caller=build_caller(event_source.value, save=True, user_id=user.id),
            # A saved draft uses the editor's draft rules for every caller, like a saved generated build, so blank
            # settings stay blank and are listed in missing_inputs. An unsaved draft uses the caller's own rules.
            validate_draft=lambda team, workflow: validated_draft(team, workflow, EventSource.WEB),
            save_draft=save_draft,
        )
        if saved is not None and saved.workflow_id is not None and saved.workflow is not None:
            self._report_created(saved.workflow_id, saved.workflow)
        return saved

    def _report_created(self, workflow_id: str, workflow: dict[str, Any]) -> None:
        # The hog_flows create endpoint sends this for every other new workflow, and a premade save skips that
        # endpoint. The properties match it, so creation metrics count both paths the same way.
        try:
            report_user_action(
                self.request.user,
                "hog_flow_created",
                {
                    "workflow_id": workflow_id,
                    "workflow_name": workflow.get("name"),
                    "origin_product": workflow.get("origin_product"),
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization.id),
                    "edges_count": len(workflow.get("edges") or []),
                    "actions_count": len(workflow.get("actions") or []),
                },
                team=self.team,
                request=self.request,
            )
        except Exception as e:
            logger.warning("workflows.data_suggestions.created_event_failed", team_id=self.team_id, error=str(e))

    def _user(self, request: Request) -> User:
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("This feature is not available.")
        return user
