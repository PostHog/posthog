from typing import cast

from django.db import transaction
from django.db.models import F, Q

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.exceptions_capture import capture_exception
from posthog.models.user import User

from products.web_analytics.backend.achievements.definitions import (
    STREAK_ARM_CONTROL,
    TRACKS,
    AchievementScope,
    TrackKey,
    serialize_definitions,
)
from products.web_analytics.backend.achievements.evaluators import EvalContext
from products.web_analytics.backend.achievements.tasks import (
    enqueue_recompute_web_analytics_achievements_debounced,
    get_or_create_progress,
    is_due,
    recompute_web_analytics_achievements_sync,
    streak_arm_for_user,
    team_local_today,
)
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsInteraction,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)


class AchievementStageSerializer(serializers.Serializer):
    stage = serializers.IntegerField(help_text="Stage number within the track, 1-5.")
    name = serializers.CharField(help_text="Stage name within the track, e.g. 'On a roll'.")
    threshold = serializers.IntegerField(
        help_text="Progress value needed to unlock this stage, resolved for the user's streak arm."
    )


class AchievementDefinitionSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable track identifier, e.g. 'streak'.")
    display_name = serializers.CharField(help_text="Human-readable track name.")
    description = serializers.CharField(help_text="One-line description of what the track rewards.")
    scope = serializers.ChoiceField(
        choices=["user", "team"], help_text="Whether the track is tracked per user or per team."
    )
    is_experiment_track = serializers.BooleanField(
        help_text="True for the streak track, whose thresholds vary by the streak-cadence experiment arm."
    )
    stages = AchievementStageSerializer(
        many=True, help_text="The five stages of this track, in ascending threshold order."
    )


class AchievementProgressSerializer(serializers.Serializer):
    track_key = serializers.CharField(help_text="Track this progress row belongs to.")
    current_stage = serializers.IntegerField(help_text="Highest stage unlocked so far, 0-5.")
    progress_value = serializers.IntegerField(help_text="Most recently computed progress value for the track.")
    last_computed_at = serializers.DateTimeField(
        allow_null=True, help_text="When the track was last recomputed, or null if it never has been."
    )
    unlocked_at = serializers.DictField(
        child=serializers.DateTimeField(),
        help_text="Map of unlocked stage number (as a string, '1'-'5') to the ISO timestamp it was unlocked.",
    )


class PendingCelebrationSerializer(serializers.Serializer):
    track_key = serializers.CharField(help_text="Track whose stage was newly unlocked.")
    stage = serializers.IntegerField(help_text="Newly unlocked stage number, 1-5.")
    stage_name = serializers.CharField(help_text="Name of the unlocked stage, shown in the celebration UI.")


class AchievementsListResponseSerializer(serializers.Serializer):
    definitions = AchievementDefinitionSerializer(
        many=True, help_text="All Wave-1 track definitions, thresholds resolved for the user's streak arm."
    )
    user_progress = AchievementProgressSerializer(
        many=True, help_text="The requesting user's progress on per-user tracks."
    )
    team_progress = AchievementProgressSerializer(many=True, help_text="The team's progress on per-team tracks.")
    pending_celebrations = PendingCelebrationSerializer(
        many=True, help_text="Newly unlocked stages awaiting an in-session celebration; acknowledge each to clear it."
    )


class RecordVisitResponseSerializer(serializers.Serializer):
    recorded = serializers.BooleanField(help_text="True once today's visit row exists for the user.")


class AcknowledgeCelebrationRequestSerializer(serializers.Serializer):
    track_key = serializers.CharField(help_text="Track of the celebration being acknowledged.")
    stage = serializers.IntegerField(min_value=1, max_value=5, help_text="Stage number being acknowledged, 1-5.")


class AcknowledgeCelebrationResponseSerializer(serializers.Serializer):
    acknowledged = serializers.BooleanField(
        help_text="True if a matching pending celebration was cleared (idempotent)."
    )


class RecordInteractionRequestSerializer(serializers.Serializer):
    interaction_kind = serializers.ChoiceField(
        choices=[WebAnalyticsInteraction.DATA, WebAnalyticsInteraction.RECORDING],
        help_text="Which interaction counter to increment: 'data' (slicing/filtering the dashboard) or 'recording' (opening a session recording).",
    )


class RecordInteractionResponseSerializer(serializers.Serializer):
    recorded = serializers.BooleanField(help_text="True once the interaction has been counted for the user.")


class WebAnalyticsUserPreferencesSerializer(serializers.Serializer):
    achievements_opt_out = serializers.BooleanField(
        help_text=(
            "When true, the requesting user has hidden the Web analytics achievements gamification UI and "
            "suppressed achievement-unlocked notifications for this project. Scoped per (project, user)."
        )
    )


def _serialize_progress(progress: WebAnalyticsAchievementProgress) -> dict[str, object]:
    return {
        "track_key": progress.track_key,
        "current_stage": progress.current_stage,
        "progress_value": progress.progress_value,
        "last_computed_at": progress.last_computed_at,
        "unlocked_at": (progress.state or {}).get("unlocked_stages", {}),
    }


def _stage_name(track_key: str, stage: int) -> str:
    try:
        track = TRACKS[TrackKey(track_key)]
    except (ValueError, KeyError):
        return ""
    return track.stages[stage - 1].name if 1 <= stage <= len(track.stages) else ""


def _collect_pending(rows: list[WebAnalyticsAchievementProgress], user_id: int) -> list[dict[str, object]]:
    pending: list[dict[str, object]] = []
    for progress in rows:
        state = progress.state or {}
        celebration_acks = state.get("celebration_acks", {})
        for stage in state.get("pending_celebrations", []):
            # Team rows are shared across members; only surface a stage to a user who hasn't acked it
            # yet, so a team unlock is celebrated once per member rather than first-acker-wins.
            if progress.user_id is None and user_id in celebration_acks.get(str(stage), []):
                continue
            pending.append(
                {
                    "track_key": progress.track_key,
                    "stage": stage,
                    "stage_name": _stage_name(progress.track_key, stage),
                }
            )
    return pending


class WebAnalyticsAchievementsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    serializer_class = AchievementsListResponseSerializer

    @extend_schema(
        operation_id="web_analytics_achievements_overview",
        summary="Get Web analytics achievements overview",
        description=(
            "Returns the achievement track definitions (thresholds resolved for the requesting user's "
            "streak-cadence arm), the user's and team's progress, and any newly unlocked stages awaiting "
            "an in-session celebration."
        ),
        responses={200: AchievementsListResponseSerializer},
    )
    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request: Request, **kwargs: object) -> Response:
        user = cast(User, request.user)
        arm = streak_arm_for_user(user)
        canonical_team_id = self.team.parent_team_id or self.team.id
        today = team_local_today(self.team)
        team_ctx = EvalContext(team=self.team, user=None, today=today, arm=None)
        is_control = arm == STREAK_ARM_CONTROL

        if not is_control:
            for track in TRACKS.values():
                if track.scope == AchievementScope.TEAM:
                    get_or_create_progress(team_ctx, track)

        user_rows = list(WebAnalyticsAchievementProgress.objects.filter(team_id=canonical_team_id, user=user))
        team_rows = list(WebAnalyticsAchievementProgress.objects.filter(team_id=canonical_team_id, user__isnull=True))

        if not is_control and any(is_due(team_ctx, row) for row in team_rows):
            enqueue_recompute_web_analytics_achievements_debounced(canonical_team_id, None, today)

        payload = {
            "definitions": serialize_definitions(arm),
            "user_progress": [_serialize_progress(row) for row in user_rows],
            "team_progress": [_serialize_progress(row) for row in team_rows],
            "pending_celebrations": _collect_pending(user_rows + team_rows, user.id),
        }
        return Response(AchievementsListResponseSerializer(payload).data)

    @extend_schema(
        operation_id="web_analytics_achievements_record_visit",
        summary="Record a Web analytics visit",
        description=(
            "Idempotently records that the requesting user opened Web analytics today (team-local date) and "
            "schedules a debounced achievement recompute. Intended to be called once per session."
        ),
        request=None,
        responses={200: RecordVisitResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def record_visit(self, request: Request, **kwargs: object) -> Response:
        user = cast(User, request.user)
        canonical_team_id = self.team.parent_team_id or self.team.id
        today = team_local_today(self.team)
        WebAnalyticsVisit.objects.get_or_create(
            team_id=canonical_team_id,
            user_id=user.id,
            visit_date=today,
        )
        try:
            recompute_web_analytics_achievements_sync(canonical_team_id, user_id=user.id, cheap_only=True)
        except Exception as e:
            capture_exception(e)
        enqueue_recompute_web_analytics_achievements_debounced(canonical_team_id, None, today)
        return Response({"recorded": True})

    @extend_schema(
        operation_id="web_analytics_achievements_acknowledge_celebration",
        summary="Acknowledge an achievement celebration",
        description=(
            "Clears a pending celebration for the given track and stage once the client has shown it, so it "
            "isn't celebrated again. Idempotent."
        ),
        request=AcknowledgeCelebrationRequestSerializer,
        responses={200: AcknowledgeCelebrationResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def acknowledge_celebration(self, request: Request, **kwargs: object) -> Response:
        user = cast(User, request.user)
        request_serializer = AcknowledgeCelebrationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        track_key = request_serializer.validated_data["track_key"]
        stage = request_serializer.validated_data["stage"]
        acknowledged = False
        canonical_team_id = self.team.parent_team_id or self.team.id
        # Lock the rows so this serializes with a concurrent recompute on the same row — neither can
        # clobber the other's state, and an acked celebration can't be resurrected.
        with transaction.atomic():
            rows = (
                WebAnalyticsAchievementProgress.objects.filter(team_id=canonical_team_id, track_key=track_key)
                .filter(Q(user=user) | Q(user__isnull=True))
                .select_for_update()
            )
            for progress in rows:
                state = dict(progress.state or {})
                pending = list(state.get("pending_celebrations", []))
                if stage not in pending:
                    continue
                if progress.user_id is None:
                    # Team celebration: record this user's ack without clearing it for other members.
                    celebration_acks = dict(state.get("celebration_acks", {}))
                    acked_user_ids = list(celebration_acks.get(str(stage), []))
                    if user.id not in acked_user_ids:
                        acked_user_ids.append(user.id)
                        celebration_acks[str(stage)] = acked_user_ids
                        state["celebration_acks"] = celebration_acks
                        progress.state = state
                        progress.save(update_fields=["state", "updated_at"])
                else:
                    # User celebration: the pending list is already per-user, so drop the stage.
                    state["pending_celebrations"] = [entry for entry in pending if entry != stage]
                    progress.state = state
                    progress.save(update_fields=["state", "updated_at"])
                acknowledged = True
        return Response({"acknowledged": acknowledged})

    @extend_schema(
        operation_id="web_analytics_achievements_record_interaction",
        summary="Record a Web analytics interaction",
        description=(
            "Idempotently increments the requesting user's first-party counter for an in-product Web "
            "analytics interaction (slicing data, or opening a session recording), which drives the "
            "Explorer and Detective achievement tracks."
        ),
        request=RecordInteractionRequestSerializer,
        responses={200: RecordInteractionResponseSerializer},
    )
    @action(detail=False, methods=["post"])
    def record_interaction(self, request: Request, **kwargs: object) -> Response:
        user = cast(User, request.user)
        request_serializer = RecordInteractionRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        kind = request_serializer.validated_data["interaction_kind"]
        canonical_team_id = self.team.parent_team_id or self.team.id
        interaction, _ = WebAnalyticsInteraction.objects.get_or_create(
            team_id=canonical_team_id,
            user_id=user.id,
            kind=kind,
        )
        # Atomic increment — no read-modify-write, so concurrent interactions can't lose a count.
        WebAnalyticsInteraction.objects.filter(pk=interaction.pk).update(count=F("count") + 1)
        try:
            recompute_web_analytics_achievements_sync(canonical_team_id, user_id=user.id, cheap_only=True)
        except Exception as e:
            capture_exception(e)
        return Response({"recorded": True})

    @extend_schema(
        methods=["GET"],
        operation_id="web_analytics_achievements_preferences",
        summary="Get Web analytics achievements preferences",
        description="Returns the requesting user's per-project Web analytics achievements preferences.",
        responses={200: WebAnalyticsUserPreferencesSerializer},
    )
    @extend_schema(
        methods=["POST"],
        operation_id="web_analytics_achievements_update_preferences",
        summary="Update Web analytics achievements preferences",
        description="Sets the requesting user's per-project Web analytics achievements preferences.",
        request=WebAnalyticsUserPreferencesSerializer,
        responses={200: WebAnalyticsUserPreferencesSerializer},
    )
    @action(detail=False, methods=["get", "post"], url_path="preferences")
    def preferences(self, request: Request, **kwargs: object) -> Response:
        user = cast(User, request.user)
        canonical_team_id = self.team.parent_team_id or self.team.id
        if request.method == "POST":
            request_serializer = WebAnalyticsUserPreferencesSerializer(data=request.data)
            request_serializer.is_valid(raise_exception=True)
            opted_out = request_serializer.validated_data["achievements_opt_out"]
            WebAnalyticsUserConfig.objects.update_or_create(
                team_id=canonical_team_id,
                user_id=user.id,
                defaults={"achievements_opt_out": opted_out},
            )
        else:
            config = WebAnalyticsUserConfig.objects.filter(team_id=canonical_team_id, user_id=user.id).first()
            opted_out = config.achievements_opt_out if config else False
        return Response(WebAnalyticsUserPreferencesSerializer({"achievements_opt_out": opted_out}).data)
