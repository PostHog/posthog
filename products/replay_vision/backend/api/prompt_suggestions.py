import uuid
from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.replay_vision.backend.feature_flag import (
    ReplayVisionEnabledPermission,
    ReplayVisionQualityEnabledPermission,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import (
    ReplayScannerPromptSuggestion,
    SuggestionStatus,
)
from products.replay_vision.backend.prompt_suggestions import (
    PromptSuggestionError,
    generate_prompt_suggestion,
    labels_fingerprint,
)

logger = structlog.get_logger(__name__)


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

    def get_throttles(self) -> list[BaseThrottle]:
        # generate holds a web worker for a synchronous LLM call and burns provider quota,
        # so it gets the AI throttles other LLM endpoints use.
        if self.action == "generate":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

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
    @action(detail=False, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def generate(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        self._require_editor()
        user = cast(User, request.user)
        try:
            suggestion = generate_prompt_suggestion(scanner, user)
        except PromptSuggestionError as e:
            if str(e) == "no rated observations":
                raise ValidationError("Rate some results first, then generate a suggestion from them.")
            if str(e) == "not configured":
                raise ValidationError("Prompt suggestions require a Gemini API key to be configured on this instance.")
            raise ValidationError("Couldn't generate a suggestion right now. Try again in a moment.")
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)

    @extend_schema(
        request=None,
        responses={200: ReplayScannerPromptSuggestionSerializer},
        description=(
            "Apply this suggestion: write its prompt to the scanner (bumping the scanner version) and mark "
            "the suggestion applied. Requires session recording edit access."
        ),
    )
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def apply(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._scanner_for_url()
        self._require_editor()
        suggestion = self.get_object()
        # One transaction, both rows locked: the guards must still hold at write time, and the scanner
        # can't end up changed while the suggestion stays pending.
        with transaction.atomic():
            scanner = ReplayScanner.objects.select_for_update().get(pk=scanner.pk)
            suggestion = ReplayScannerPromptSuggestion.objects.select_for_update().get(pk=suggestion.pk)
            # A stale tab can submit an old suggestion id, silently rolling the prompt back.
            if suggestion.status not in (SuggestionStatus.PENDING, SuggestionStatus.DISMISSED):
                raise ValidationError("Only the current recommendation can be applied.")
            if suggestion.scanner_version != scanner.scanner_version:
                raise ValidationError("The scanner prompt changed since this was generated. Generate a fresh one.")
            config = dict(scanner.scanner_config or {})
            config["prompt"] = suggestion.suggested_prompt
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
        description="Dismiss this suggestion without applying it. Requires session recording edit access.",
    )
    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def dismiss(self, request: Request, **kwargs: Any) -> Response:
        self._scanner_for_url()
        self._require_editor()
        suggestion = self.get_object()
        with transaction.atomic():
            suggestion = ReplayScannerPromptSuggestion.objects.select_for_update().get(pk=suggestion.pk)
            # Dismissed prompts feed the "do not propose again" examples, so an applied or superseded
            # suggestion (e.g. from a stale tab) must not land there.
            if suggestion.status != SuggestionStatus.PENDING:
                raise ValidationError("Only the current recommendation can be dismissed.")
            suggestion.status = SuggestionStatus.DISMISSED
            suggestion.save(update_fields=["status"])
        return Response(ReplayScannerPromptSuggestionSerializer(suggestion).data)
