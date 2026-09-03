"""HTTP surface for pre-computed scout suggestions.

Read the team's "Suggested for this project" batch, dismiss one, or ask for a refresh. The batch is
produced headlessly by `scout_harness/suggestions.py` (see that module's docstring); this viewset
only reads and flags the stored JSON, so the scouts tab can render the strip without a task.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.exceptions import Conflict
from posthog.models.user import User
from posthog.permissions import APIScopePermission
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutSuggestionSet
from products.signals.backend.scout_chat import consume_daily_attempt, refund_daily_attempt
from products.signals.backend.scout_harness.suggestions import (
    dismiss_suggestion,
    effective_status,
    enabled_skill_names,
    read_suggestion_settings,
    reserved_scout_names,
    suggestions_allowed_for_team,
    visible_items,
)
from products.signals.backend.scout_harness.views import ScoutCanonicalTeamAccessPermission, _canonical_team_id

logger = structlog.get_logger(__name__)

# Refreshes a team may request per day through the API. The headless scan costs real model spend,
# so the pull path is capped well below the chat button's daily budget; the scheduled producer is
# the normal refresh.
SUGGESTIONS_REFRESH_DAILY_CAP = 3


class ScoutSuggestionProposedConfigSerializer(serializers.Serializer):
    run_cron_schedule = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Suggested five-field cron schedule in the project timezone, or null for an interval.",
    )
    run_interval_minutes = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="Suggested minutes between runs when no cron is given; null means the daily default.",
    )
    emit = serializers.BooleanField(
        help_text="Whether the suggested scout should write to the inbox (false = dry run)."
    )


class ScoutSuggestionItemSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable id of this suggestion within the batch; use it to dismiss.")
    kind = serializers.ChoiceField(
        choices=["canonical", "custom"],
        help_text="`canonical`: enable a PostHog-authored scout that exists but is off. `custom`: create a drafted scout.",
    )
    skill_name = serializers.CharField(
        help_text="The scout's `signals-scout-*` skill name (existing for canonical, proposed for custom)."
    )
    title = serializers.CharField(help_text="Short sentence-case title: what the scout watches.")
    why_here = serializers.CharField(help_text="Project-specific evidence for this suggestion, in prose.")
    description = serializers.CharField(
        allow_blank=True, help_text="Custom only: the one-line description the scout would be created with."
    )
    draft_body = serializers.CharField(
        allow_blank=True, help_text="Custom only: the complete skill body the scout would be created with."
    )
    proposed_config = ScoutSuggestionProposedConfigSerializer(help_text="Suggested schedule and emit posture.")
    gap = serializers.BooleanField(help_text="True when nothing in the current fleet covers this.")
    confidence = serializers.ChoiceField(choices=["low", "medium", "high"], help_text="The producer's confidence.")


# The read is the viewset's `list` action but returns one object; without this drf-spectacular
# infers a list response and the generated client types it as an array.
@extend_schema_serializer(many=False)
class ScoutSuggestionSetSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=SignalScoutSuggestionSet.Status.choices,
        help_text=(
            "`fresh`: current batch. `stale`: the fleet changed since it was generated, or the batch aged past "
            "the refresh window. `failed`: the last refresh failed (items are the prior batch, if any). "
            "`empty`: nothing to suggest yet."
        ),
    )
    generated_at = serializers.DateTimeField(
        allow_null=True, help_text="When the current batch was generated; null before the first run."
    )
    model = serializers.CharField(allow_blank=True, help_text="The model that produced the batch, when pinned.")
    fleet_snapshot = serializers.ListField(
        child=serializers.CharField(),
        help_text="Skill names that were enabled when the batch was generated.",
    )
    items = ScoutSuggestionItemSerializer(
        many=True, help_text="Suggestions not yet dismissed or created, best first. Up to 5."
    )


class ScoutSuggestionRefreshSerializer(serializers.Serializer):
    workflow_id = serializers.CharField(help_text="The dispatched refresh workflow id.")


def _set_payload(row: SignalScoutSuggestionSet | None, *, team_id: int) -> dict[str, Any]:
    if row is None:
        return {
            "status": SignalScoutSuggestionSet.Status.EMPTY,
            "generated_at": None,
            "model": "",
            "fleet_snapshot": [],
            "items": [],
        }
    return {
        "status": effective_status(row, refresh_days=read_suggestion_settings().refresh_days),
        "generated_at": row.generated_at,
        "model": row.model,
        "fleet_snapshot": list(row.fleet_snapshot or []),
        "items": visible_items(
            row,
            enabled_skill_names=enabled_skill_names(team_id),
            reserved_names=reserved_scout_names(team_id),
        ),
    }


class SignalScoutSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The pre-computed "Suggested for this project" scout batch: read, dismiss, refresh."""

    serializer_class = ScoutSuggestionSetSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_scout"
    # An aggregate surface: suggestions are not `signal_scout` objects, so an object-specific
    # grant on one scout must not open the whole project's batch (or its paid refresh) to a
    # member whose project-level access is "none".
    requires_resource_level_access = True
    pagination_class = None
    lookup_field = "id"
    # A single row per team; `list` is the read and the row is resolved by team, never by pk.
    queryset = SignalScoutSuggestionSet.all_teams.all()

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        if getattr(view, "action", None) in ("dismiss", "refresh"):
            return ["signal_scout:write"]
        return None

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # `AccessControlPermission` reads its resource-level check from here. Anchor it to the
        # canonical team like the membership and token-scope legs: the batch belongs to the parent
        # project, so a child environment's own `signal_scout` grant must not read it or pay for
        # its refresh when the parent grants `none`.
        team = self.team.parent_team or self.team
        return UserAccessControl(user=cast(User, self.request.user), team=team, organization_id=self.organization_id)

    @extend_schema(
        responses={200: OpenApiResponse(response=ScoutSuggestionSetSerializer, description="The current batch.")},
        summary="Get suggested scouts for this project",
        description=(
            "Return the pre-computed scout suggestions for this project: up to five picks, best first, "
            "each either a PostHog-authored scout to turn on or a drafted custom scout. Dismissed and "
            "already-created suggestions are omitted. An empty `items` with status `empty` means no "
            "batch has been generated yet; the interactive `scout-chat-tasks` path still works."
        ),
        operation_id="signals_scout_suggestions_list",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        row = SignalScoutSuggestionSet.objects.for_team(team_id, canonical=True).first()
        return Response(ScoutSuggestionSetSerializer(_set_payload(row, team_id=team_id)).data)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=ScoutSuggestionItemSerializer, description="The dismissed suggestion."),
            404: OpenApiResponse(description="No suggestion with that id in this project's batch."),
        },
        summary="Dismiss a suggested scout",
        description=(
            "Hide one suggestion from this project's batch. Dismissal is remembered across refreshes by "
            "skill name, so the same suggestion is not shown again."
        ),
        operation_id="signals_scout_suggestions_dismiss",
    )
    @action(detail=True, methods=["post"], url_path="dismiss")
    def dismiss(self, request: Request, id: str, *args, **kwargs) -> Response:
        record = dismiss_suggestion(_canonical_team_id(self), id, user_id=request.user.pk)
        if record is None:
            raise exceptions.NotFound()
        return Response(ScoutSuggestionItemSerializer(record).data)

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(response=ScoutSuggestionRefreshSerializer, description="Refresh dispatched."),
            403: OpenApiResponse(
                description="Organization has not approved AI data processing, or suggestions are off for this project."
            ),
            409: OpenApiResponse(description="A refresh is already running for this project."),
            429: OpenApiResponse(description="Daily refresh cap reached."),
        },
        summary="Refresh suggested scouts",
        description=(
            "Re-run the suggestion scan for this project now instead of waiting for the scheduled "
            "refresh. Runs headlessly; poll the list endpoint for the new batch (`generated_at` "
            "advances). Capped per project per day."
        ),
        operation_id="signals_scout_suggestions_refresh",
    )
    @action(detail=False, methods=["post"], url_path="refresh")
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        team = self.team.parent_team or self.team
        if team.organization.is_ai_data_processing_approved is not True:
            raise exceptions.PermissionDenied(
                "Enable AI data processing for this organization to get scout suggestions."
            )
        # The same kill switch and blocklist the scheduled planner honors, so a caller with
        # `signal_scout:write` cannot pull a paid scan on a project an operator has turned off.
        if not suggestions_allowed_for_team(read_suggestion_settings(), team.id):
            raise exceptions.PermissionDenied("Scout suggestions are not enabled for this project.")

        if not consume_daily_attempt("signals_scout_suggestions_refresh", team.id, SUGGESTIONS_REFRESH_DAILY_CAP):
            raise exceptions.Throttled(
                detail="You've reached today's limit for suggestion refreshes. Try again tomorrow."
            )

        try:
            # Deferred for the same reason as the scout manual-run endpoint: keep the Signals
            # Temporal graph off the route-load path. Inside the try so an import error refunds
            # the attempt rather than spending one of the day's three on nothing.
            from products.signals.backend.temporal.agentic.scout_suggestions import (  # noqa: PLC0415
                start_manual_scout_suggestions_run,
            )

            workflow_id = start_manual_scout_suggestions_run(
                sync_connect(), team_id=team.id, acting_user_id=request.user.pk
            )
        except WorkflowAlreadyStartedError:
            # Nothing was dispatched, so the attempt goes back: retries against a running scan
            # must not spend the day's budget.
            refund_daily_attempt("signals_scout_suggestions_refresh", team.id)
            raise Conflict("A suggestion refresh is already running for this project.")
        except Exception:
            refund_daily_attempt("signals_scout_suggestions_refresh", team.id)
            raise
        logger.info("scout_suggestions: manual refresh dispatched", team_id=team.id, workflow_id=workflow_id)
        return Response(
            ScoutSuggestionRefreshSerializer({"workflow_id": workflow_id}).data,
            status=status.HTTP_202_ACCEPTED,
        )
