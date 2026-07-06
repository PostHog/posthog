import uuid
from typing import Any, cast

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.exceptions import QuotaLimitExceeded
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY

from products.replay_vision.backend.api.scanners import _scanner_config_error_message
from products.replay_vision.backend.feature_flag import (
    ReplayVisionEnabledPermission,
    ReplayVisionQualityEnabledPermission,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_evaluation import evaluation_supported
from products.replay_vision.backend.prompt_suggestions import (
    PromptSuggestionError,
    generate_prompt_suggestion,
    labels_fingerprint,
)
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.temporal.constants import (
    EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT,
    EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME,
    build_evaluate_prompt_suggestion_workflow_id,
)
from products.replay_vision.backend.temporal.evaluation_types import EvaluatePromptSuggestionInputs

logger = structlog.get_logger(__name__)


class PromptEvaluationResultSerializer(serializers.Serializer):
    session_id = serializers.CharField(help_text="The rated session that was re-run with the suggested prompt.")
    observation_id = serializers.CharField(help_text="The original rated observation the comparison is against.")
    rated_correct = serializers.BooleanField(help_text="The team's rating of the original output (thumbs up = true).")
    before = serializers.CharField(allow_null=True, help_text="The original output's primary outcome.")
    after = serializers.CharField(
        allow_null=True, help_text="The suggested prompt's outcome for the same session; null when the run errored."
    )
    outcome = serializers.CharField(
        help_text="kept (up, unchanged), regressed (up, changed), fixed (down, changed), "
        "still_wrong (down, unchanged), or error."
    )
    error = serializers.CharField(allow_null=True, help_text="Why this session's re-run failed, when it did.")


class PromptEvaluationSummarySerializer(serializers.Serializer):
    kept = serializers.IntegerField(help_text="Thumbs-up sessions whose output is unchanged.")
    regressed = serializers.IntegerField(help_text="Thumbs-up sessions whose output changed.")
    fixed = serializers.IntegerField(help_text="Thumbs-down sessions whose output changed.")
    still_wrong = serializers.IntegerField(help_text="Thumbs-down sessions whose output is unchanged.")
    # DRF's metaclass pops declared fields off the class, so this only shadows Serializer.errors for mypy.
    errors = serializers.IntegerField(help_text="Sessions whose re-run failed.")  # type: ignore[assignment]


class PromptSuggestionEvaluationSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="running, succeeded, or failed.")
    started_at = serializers.DateTimeField(help_text="When the evaluation started.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the evaluation finished, if it has.")
    total = serializers.IntegerField(help_text="How many rated sessions are being re-run.")
    labels_fingerprint = serializers.CharField(help_text="The rated set the evaluation ran against.")
    results = PromptEvaluationResultSerializer(many=True, help_text="Per-session outcomes, in completion order.")
    summary = PromptEvaluationSummarySerializer(
        allow_null=True, help_text="Outcome counts; null while the evaluation is running."
    )


class ReplayScannerPromptSuggestionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who requested this suggestion; null for automatic refreshes.",
    )
    applied_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who applied this suggestion to the scanner; null unless applied.",
    )
    evaluation = serializers.SerializerMethodField(
        help_text="Test-before-apply results: the suggested prompt re-run against rated sessions."
    )

    @extend_schema_field(PromptSuggestionEvaluationSerializer(allow_null=True))
    def get_evaluation(self, suggestion: ReplayScannerPromptSuggestion) -> dict[str, Any] | None:
        return suggestion.evaluation

    class Meta:
        model = ReplayScannerPromptSuggestion
        fields = [
            "id",
            "status",
            "suggested_prompt",
            "base_prompt",
            "rationale",
            "based_on_up",
            "based_on_down",
            "scanner_version",
            "created_at",
            "created_by",
            "applied_at",
            "applied_by",
            "evaluation",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "status": {"help_text": "pending (current), applied, dismissed, or superseded by a newer suggestion."},
            "suggested_prompt": {"help_text": "The full rewritten prompt, ready to apply to the scanner."},
            "base_prompt": {"help_text": "The scanner prompt this suggestion was generated against, for diffing."},
            "rationale": {"help_text": "What the rewrite changed and why, grounded in the ratings."},
            "based_on_up": {"help_text": "Thumbs-up ratings the suggestion was based on."},
            "based_on_down": {"help_text": "Thumbs-down ratings the suggestion was based on."},
            "scanner_version": {"help_text": "The scanner version whose prompt this suggestion was generated against."},
        }


class CurrentPromptSuggestionSerializer(serializers.Serializer):
    suggestion = ReplayScannerPromptSuggestionSerializer(
        allow_null=True,
        help_text="The newest suggestion for this scanner, or null when none has been generated yet.",
    )
    stale = serializers.BooleanField(
        help_text="True when the team's ratings changed since the newest suggestion was generated."
    )
    rated_count = serializers.IntegerField(
        help_text="Number of rated (thumbs up or down) succeeded observations available to generate from."
    )


class ReplayScannerPromptSuggestionViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """AI prompt-rewrite suggestions for a scanner, generated from the team's thumbs up/down ratings."""

    scope_object = "replay_scanner"
    required_scopes = ["replay_scanner:read", "session_recording:read"]
    permission_classes = [ReplayVisionEnabledPermission, ReplayVisionQualityEnabledPermission]
    serializer_class = ReplayScannerPromptSuggestionSerializer
    queryset = ReplayScannerPromptSuggestion.objects.all()

    def _scanner_for_url(self) -> ReplayScanner:
        cached = getattr(self, "_scanner_for_url_cache", None)
        if cached is not None:
            return cached
        try:
            scanner_id = uuid.UUID(self.kwargs["parent_lookup_scanner_id"])
        except (KeyError, ValueError):
            raise NotFound()
        scanner = ReplayScanner.objects.filter(team_id=self.team_id, id=scanner_id).first()
        if scanner is None:
            raise NotFound()
        # Suggestions embed recording-derived outputs and feedback, so they inherit the scanner's RBAC
        # and also require session_recording read.
        self.check_object_permissions(self.request, scanner)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading prompt suggestions requires session_recording read access.")
        self._scanner_for_url_cache = scanner
        return scanner

    def _require_editor(self) -> None:
        # Generating and acting on suggestions mutates team-wide scanner state, matching the "Edit scanner" gate.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="editor"):
            raise PermissionDenied("Managing prompt suggestions requires session_recording edit access.")

    def safely_get_queryset(
        self, queryset: QuerySet[ReplayScannerPromptSuggestion]
    ) -> QuerySet[ReplayScannerPromptSuggestion]:
        scanner = self._scanner_for_url()
        return (
            queryset.filter(team_id=self.team_id, scanner_id=scanner.id)
            .select_related("created_by", "applied_by")
            .order_by("-created_at")
        )

    def _rated_count(self, scanner: ReplayScanner) -> int:
        return ReplayObservation.objects.filter(
            team_id=self.team_id,
            scanner_id=scanner.id,
            status=ObservationStatus.SUCCEEDED,
            label__isnull=False,
        ).count()

    @extend_schema(
        responses={200: CurrentPromptSuggestionSerializer},
        description=(
            "The scanner's newest prompt suggestion plus whether it is stale (the ratings changed since it "
            "was generated) and how many rated observations are available."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def current(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        suggestion = self.get_queryset().first()
        stale = suggestion is not None and suggestion.labels_fingerprint != labels_fingerprint(scanner)
        payload = {
            "suggestion": ReplayScannerPromptSuggestionSerializer(suggestion).data if suggestion else None,
            "stale": stale,
            "rated_count": self._rated_count(scanner),
        }
        return Response(payload)

    @extend_schema(
        request=None,
        responses={200: ReplayScannerPromptSuggestionSerializer},
        description=(
            "Generate a fresh prompt suggestion from the team's current ratings. The previous pending "
            "suggestion becomes history (superseded). Requires at least one rated observation and session "
            "recording edit access."
        ),
    )
    # Each call is an inline LLM request, so it gets the shared AI rate limits on top of the editor gate.
    @action(
        detail=False,
        methods=["post"],
        required_scopes=["replay_scanner:write", "session_recording:read"],
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def generate(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        self._require_editor()
        user = cast(User, request.user)
        try:
            suggestion = generate_prompt_suggestion(scanner, user)
        except PromptSuggestionError as e:
            if str(e) == "no rated observations":
                raise ValidationError("Rate some results first, then generate a suggestion from them.")
            raise ValidationError("Couldn't generate a suggestion right now. Try again in a moment.")
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)

    @extend_schema(
        request=None,
        responses={200: ReplayScannerPromptSuggestionSerializer},
        description=(
            "Apply this suggestion: write its prompt to the scanner (bumping the scanner version) and mark "
            "the suggestion applied. Only the current pending suggestion can be applied. Requires session "
            "recording edit access."
        ),
    )
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def apply(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        self._require_editor()
        suggestion = self.get_object()
        # Guards must run on locked rows: unlocked reads let two concurrent applies both pass,
        # and the second silently overwrites the first.
        with transaction.atomic():
            scanner = ReplayScanner.objects.select_for_update().get(team_id=self.team_id, id=scanner.id)
            suggestion = ReplayScannerPromptSuggestion.objects.select_for_update().get(
                team_id=self.team_id, id=suggestion.id
            )
            # A stale tab can submit an old or dismissed suggestion id, silently rolling the prompt back.
            if suggestion.status != SuggestionStatus.PENDING:
                raise ValidationError("Only the current recommendation can be applied.")
            if suggestion.scanner_version != scanner.scanner_version:
                raise ValidationError("The scanner prompt changed since this was generated. Generate a fresh one.")
            config = dict(scanner.scanner_config or {})
            config["prompt"] = suggestion.suggested_prompt
            # Same validation as the scanner edit endpoint: an oversized or malformed LLM rewrite
            # must not land in the config that every future observation snapshots.
            message = _scanner_config_error_message(ScannerType(scanner.scanner_type), config)
            if message:
                raise ValidationError(f"This recommendation can't be applied: {message}")
            scanner.scanner_config = config
            scanner.save(update_fields=["scanner_config"])
            suggestion.status = SuggestionStatus.APPLIED
            suggestion.applied_at = timezone.now()
            suggestion.applied_by = cast(User, request.user)
            suggestion.save(update_fields=["status", "applied_at", "applied_by"])
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)

    @extend_schema(
        request=None,
        responses={200: ReplayScannerPromptSuggestionSerializer},
        description=(
            "Test this suggestion before applying it: re-run the scanner with the suggested prompt against "
            "already-rated sessions in the background and compare each fresh output with the stored one. "
            "Results land on the suggestion's `evaluation` field; poll `current` while status is running. "
            "Only monitor and classifier scanners are supported. Requires session recording edit access."
        ),
    )
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def evaluate(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        self._require_editor()
        suggestion = self.get_object()
        if suggestion.status != SuggestionStatus.PENDING:
            raise ValidationError("Only the current pending suggestion can be tested.")
        if not evaluation_supported(scanner):
            raise ValidationError("Testing is available for monitor and classifier scanners.")
        if self._rated_count(scanner) == 0:
            raise ValidationError("Rate some results first; they are what the suggestion is tested against.")
        # Test runs create no observations, so they bypass quota accounting. Still refuse when the
        # org is out of quota: they cost the same to serve.
        quota = compute_quota_snapshot(organization_id=self.team.organization_id)
        if quota.exhausted:
            raise QuotaLimitExceeded(
                detail=(
                    f"Monthly Replay Vision quota of {quota.monthly_quota:,} observations reached. "
                    f"Resets {quota.period_end.strftime('%b')} {quota.period_end.day}."
                )
            )
        if isinstance(suggestion.evaluation, dict) and suggestion.evaluation.get("status") == "running":
            return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)

        # Stamp running before starting the workflow so the UI never sees a gap. The select activity
        # replaces this stub with the real total and fingerprint.
        suggestion.evaluation = {
            "status": "running",
            "started_at": timezone.now().isoformat(),
            "finished_at": None,
            "total": 0,
            "labels_fingerprint": "",
            "results": [],
            "summary": None,
        }
        suggestion.save(update_fields=["evaluation"])
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME,  # type: ignore[arg-type]
                EvaluatePromptSuggestionInputs(suggestion_id=suggestion.id, team_id=scanner.team_id),  # type: ignore[arg-type]
                id=build_evaluate_prompt_suggestion_workflow_id(suggestion.id),
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                execution_timeout=EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT,
                search_attributes=TypedSearchAttributes(
                    search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=scanner.team_id)]
                ),
            )
        except WorkflowAlreadyStartedError:
            pass  # An evaluation is already in flight, return its state.
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)

    @extend_schema(
        request=None,
        responses={200: ReplayScannerPromptSuggestionSerializer},
        description=(
            "Dismiss this suggestion without applying it. Only the current pending suggestion can be "
            "dismissed. Requires session recording edit access."
        ),
    )
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def dismiss(self, request: Request, **kwargs: Any) -> Response:
        self._scanner_for_url()
        self._require_editor()
        suggestion = self.get_object()
        with transaction.atomic():
            suggestion = ReplayScannerPromptSuggestion.objects.select_for_update().get(
                team_id=self.team_id, id=suggestion.id
            )
            # Dismissing an applied suggestion would mark the scanner's live prompt as rejected.
            if suggestion.status != SuggestionStatus.PENDING:
                raise ValidationError("Only the current recommendation can be dismissed.")
            suggestion.status = SuggestionStatus.DISMISSED
            suggestion.save(update_fields=["status"])
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)
