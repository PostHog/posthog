"""DRF viewsets exposing the Signals scout surface over HTTP for MCP consumption.

These wrap the sync Python tools in `scout_harness/tools/` so the headless scout
(and any other agent on the team's PostHog MCP) can call the `signals-scout-*`
tools — `runs-list`, `runs-retrieve`, `runs-findings-create`, `memory-list`,
`memory-create`, `memory-delete`, `project-profile-get`, and `members-list` — over
the standard PostHog MCP plumbing.

Auth uses two dedicated scope objects: `signal_scout:read` is user-grantable
via the personal-API-key picker (so a team can introspect runs/scratchpad from
their own clients), while `signal_scout_internal:write` is in
`INTERNAL_API_SCOPE_OBJECTS` and so can't be granted via PAK at all — the
sandbox gets it only via `INTERNAL_SCOPES` when its OAuth token is minted.
This blocks the prompt-injection vector where a user could mint a PAK,
write to the durable scratchpad, and have the scout read it back verbatim
on its next run. Every read filters on `team_id` first; the scout's MCP
token is already pinned to the team.
"""

from __future__ import annotations

import uuid
import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from django.db import transaction
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

# PostHog's `SessionAuthentication` (not DRF's) calls `enforce_two_factor()`.
# Authenticators are tried in order and a browser-session request authenticates on
# the first matching class, so DRF's plain `SessionAuthentication` would let a
# password-only user in a 2FA-enforced org read scout runs/scratchpad without
# completing 2FA.
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import AccessControlPermission, APIScopePermission
from posthog.rbac.user_access_control import UserAccessControl
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import (
    SignalProjectProfile,
    SignalReport,
    SignalScoutConfig,
    SignalScoutEmission,
    SignalScoutRun,
)
from products.signals.backend.quota import is_team_signals_quota_limited
from products.signals.backend.report_generation.resolve_reviewers import MAX_PROJECT_MEMBERS, list_project_members
from products.signals.backend.scout_harness.config_registry import (
    enabled_scout_count,
    ensure_scout_category,
    register_missing_configs,
)
from products.signals.backend.scout_harness.lazy_seed import scout_skill_origin, sync_canonical_skills
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM, STALE_RUN_CUTOFF_S
from products.signals.backend.scout_harness.serializers import (
    EditReportRequestSerializer,
    EditReportResponseSerializer,
    EmitFindingRequestSerializer,
    EmitFindingResponseSerializer,
    EmitReportRequestSerializer,
    EmitReportResponseSerializer,
    EvidenceEntrySerializer,
    FleetFindingsSummaryQuerySerializer,
    FleetFindingsSummarySerializer,
    ForgetRequestSerializer,
    ForgetResponseSerializer,
    ProjectProfileQuerySerializer,
    ProjectProfileSerializer,
    RecentEmissionsQuerySerializer,
    RememberRequestSerializer,
    ScoutEmissionReportLinkSerializer,
    ScoutMemberSerializer,
    ScoutMembersQuerySerializer,
    ScoutMetadataSerializer,
    ScoutNoteCreateRequestSerializer,
    ScoutNoteSerializer,
    ScoutNotesQuerySerializer,
    ScoutRunIdsBatchRequestSerializer,
    ScratchpadEntrySerializer,
    SearchMemoryQuerySerializer,
    SearchRecentRunsQuerySerializer,
    SignalScoutConfigCreateSerializer,
    SignalScoutConfigSerializer,
    SignalScoutConfigUpdateSerializer,
    SignalScoutCreateResponseSerializer,
    SignalScoutCreateSerializer,
    SignalScoutEmissionSerializer,
    SignalScoutManualRunSerializer,
    SignalScoutRunDetailSerializer,
    SignalScoutRunSummarySerializer,
)
from products.signals.backend.scout_harness.skill_loader import (
    REPORT_CHANNEL_TOOLS,
    SkillNotFoundError,
    load_skill_for_run,
)
from products.signals.backend.scout_harness.team_limits import (
    DAILY_BUDGET_WINDOW,
    _canonicalize_team_config_keys,
    _default_team_config,
    _parse_enrollment,
    _read_flag_payload,
    _resolve_enrolled,
    _resolve_max_runs_per_day,
    _runs_today_by_team,
    _team_configs,
    resolve_sync_seed_inputs,
    resolve_team_metadata,
    withheld_skills_for_team,
)
from products.signals.backend.scout_harness.tools.emit import EvidenceEntry, InvalidEmitError, emit_finding_sync
from products.signals.backend.scout_harness.tools.notes import (
    DEFAULT_NOTES_LIST_LIMIT,
    InvalidNoteError,
    delete_note,
    leave_note,
    list_notes,
)
from products.signals.backend.scout_harness.tools.profile import get_project_profile
from products.signals.backend.scout_harness.tools.report import (
    ReportEvidence,
    ReviewerInput,
    edit_report_sync,
    emit_report_sync,
)
from products.signals.backend.scout_harness.tools.runs import (
    DEFAULT_FINDINGS_WINDOW_HOURS,
    fleet_findings_summary,
    get_run,
    search_recent_runs,
)
from products.signals.backend.scout_harness.tools.scratchpad import (
    InvalidScratchpadError,
    forget,
    remember,
    search_scratchpad,
)
from products.signals.backend.scout_report import InvalidScoutReportError
from products.skills.backend.api.skill_services import LLMSkillDuplicateNameConflictError, create_skill
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# Hard cap on the per-run emissions response. Far above any realistic run (a scout emits a
# handful of findings), so it never truncates in practice — it just bounds a pathological
# retry-heavy run rather than leaving the payload unbounded.
MAX_EMISSIONS_PER_RUN = 1000

# Upper bound on rows returned by the batched emissions endpoints. A scout emits a handful of findings
# per run, so even the 120-run findings window stays in the low hundreds; this only bounds a pathological
# payload, mirroring `MAX_EMISSIONS_PER_RUN` for the single-run path.
MAX_EMISSIONS_PER_BATCH = 5000

# Page size for the cross-run `recent-emissions` action: the default when the caller omits `limit`,
# and the hard ceiling it's clamped to. Bounded so an agent asking "what has the fleet surfaced
# lately?" gets a useful window in one call without an unbounded scan; walk back via `date_to`.
DEFAULT_RECENT_EMISSIONS_LIMIT = 50
MAX_RECENT_EMISSIONS_LIMIT = 200

# `SignalScoutRunViewSet.lookup_field` is `run_id`, but the model's PK field is `id`, so
# drf-spectacular can't derive the path-param type from the model and warns (fatal under
# `--fail-on-warn`). Declare the param explicitly on every detail action instead.
_RUN_ID_PATH_PARAMETER = OpenApiParameter(
    name="run_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="UUID of the `SignalScoutRun` bridge row.",
)


def _caller_carries_scout_internal_scope(request: Request) -> bool:
    """True only when the request authenticates with the sandbox-internal scout scope.

    The profile build — whether a `force_refresh` rebuild or the lazy build on cache miss —
    runs per-section table scans plus the ClickHouse top-events aggregation and writes a
    row. Honoring either for any `signal_scout:read` PAK would let an attacker spam
    expensive recomputes, and honoring either on a session-authenticated GET makes the
    rebuild CSRF-triggerable (DRF exempts safe methods from CSRF). The headless scout's
    sandbox OAuth token is the only caller that legitimately builds inline, and it's minted
    with `signal_scout_internal:write` via `SCOUT_INTERNAL_SCOPES` — so gate the build on
    that scope. Session and other non-token auth carry no API scopes and never pass, which
    closes the CSRF path; untrusted read callers get the cached profile or a 404. `*`
    (full-access consent) deliberately does not match: internal scopes are not reachable
    via user-consented tokens.
    """
    authenticator = request.successful_authenticator
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        scopes = authenticator.personal_api_key.scopes or []
    elif isinstance(authenticator, OAuthAccessTokenAuthentication):
        scopes = (authenticator.access_token.scope or "").split()
    else:
        return False
    return "signal_scout_internal:write" in scopes


class Conflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A run for this scout is already in progress."
    default_code = "conflict"


def _scout_run_in_flight(team_id: int, skill_name: str) -> bool:
    """Whether a *live* run for this `(canonical team, skill)` is already QUEUED or IN_PROGRESS.

    Mirrors the runner's authoritative single-flight (`scout_harness/runner._has_running_run`)
    so the manual-trigger endpoint can fail fast with a 409 instead of dispatching a workflow
    that the runner would only skip. Status flows from the linked `TaskRun`; covers a run
    started by either the coordinator or a prior manual trigger.

    A run older than `STALE_RUN_CUTOFF_S` is an orphan left by a crashed worker (Temporal kills
    the activity at the hard ceiling, so it cannot still be executing) — it is deliberately NOT
    counted as in-flight here. Otherwise this fail-fast 409 would short-circuit before the
    workflow's runner reaches its `_self_heal_stale_runs` reap, wedging the lane until a
    scheduled tick happens to reap it — which never comes for a disabled scout, whose only run
    path is this endpoint. Treating the orphan as free lets the dispatched run reap it and proceed.
    """
    live_cutoff = timezone.now() - timedelta(seconds=STALE_RUN_CUTOFF_S)
    return (
        SignalScoutRun.objects.unscoped()
        .filter(
            team_id=team_id,
            skill_name=skill_name,
            task_run__status__in=(tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS),
            task_run__created_at__gte=live_cutoff,
        )
        .exists()
    )


def _reject_if_manual_run_suppressed(team_id: int) -> None:
    """Apply the fleet-level gates the scheduled coordinator enforces, so a manual trigger can't
    run a scout the scheduled path would deliberately suppress.

    Reads the `signals-scout` flag payload once (the same snapshot the coordinator plans off):

    - **Enrollment kill switch.** A project in `skip_team_ids`, or one not enrolled at all, never
      runs scheduled scouts — so its manual trigger is forbidden too (403). Without this, any
      caller with `signal_scout:write` could run a scout on a project an operator has explicitly
      drained or held back via the flag.
    - **Daily run budget.** `max_runs_per_day` (per-team override → fleet default → code constant)
      bounds dispatches per rolling 24h. Manual runs land the same `SignalScoutRun` rows the
      coordinator counts, so they share the tally: once the budget is spent the trigger is
      throttled (429) until the window rolls, instead of letting repeated manual runs blow past
      the per-team daily cap the scheduled path enforces.

    `team_id` is the canonical (parent) project id, matching how the coordinator plans; team
    config keys are canonicalized the same way so a child-env override still lines up.
    """
    payload = _read_flag_payload()
    if not _resolve_enrolled(team_id, _parse_enrollment(payload)):
        raise exceptions.PermissionDenied(detail="Signals scouts are not enabled for this project.")

    team_configs = _canonicalize_team_config_keys(_team_configs(payload))
    per_day = _resolve_max_runs_per_day(team_id, team_configs, _default_team_config(payload))
    if per_day is not None:
        runs_today = _runs_today_by_team({team_id}, timezone.now() - DAILY_BUDGET_WINDOW).get(team_id, 0)
        if runs_today >= per_day:
            raise exceptions.Throttled(detail="This project has reached its daily scout run budget. Try again later.")


def _parse_run_id_or_404(kwargs: dict) -> uuid.UUID:
    """Parse the run-id URL kwarg as a UUID; raise 404 on missing or malformed.

    Accepts either `run_id` (the canonical name across the scout surface, set via
    `SignalScoutRunViewSet.lookup_field`) or `id` (the legacy/config-viewset name) so
    the same helper backs both. DRF routes any string the default `lookup_value_regex`
    accepts (anything except `/` and `.`) into the action, so the action is responsible
    for rejecting non-UUID inputs cleanly rather than letting them surface as 500s from
    `UUIDField.to_python()` on the underlying ORM query.
    """
    raw = kwargs.get("run_id") or kwargs.get("id")
    if raw is None:
        raise exceptions.NotFound()
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise exceptions.NotFound()


def _canonical_team_id(view: TeamAndOrgViewSetMixin) -> int:
    """Canonical (parent/project) team id for scout queries.

    `view.team_id` is the raw URL team and may be a child environment, but scout
    models are `TeamScopedRootMixin` and persist under the canonical parent team
    (`RootTeamMixin.save` rewrites child writes). `TeamAndOrgViewSetMixin` already
    scopes the manager to this canonical id; passing the raw child id to the harness
    helpers adds a contradictory `team_id` predicate, so list/retrieve return
    empty/404 for legitimate rows in child-environment requests. `self.team` is a
    cached_property loaded by the permission checks, so reading `parent_team_id` is
    free. Mirrors the canonicalization in `TeamAndOrgViewSetMixin.initial`.
    """
    return view.team.parent_team_id or view.team_id


def _run_write_not_found(run_id: uuid.UUID) -> exceptions.NotFound:
    """Actionable 404 for a run-scoped *write* (emit-signal / emit-report / edit-report) whose `run_id`
    didn't resolve to a row for this project.

    A scout passes the `run_id` from its prompt identity block; if that value doesn't match a persisted
    `SignalScoutRun`, a bare 404 reads as terminal and a scout that stops there silently drops the finding
    it was mid-emit on. Steer it to the recovery path instead: its own in-progress run is always listed by
    `signals-scout-runs-list`, so it can read the authoritative `run_id` from there and retry. The message
    is the whole fix for a scout that would otherwise treat this as the end of the road.
    """
    return exceptions.NotFound(
        f"No run `{run_id}` for this project. If you have an active run, this run_id may not match the "
        "persisted run row: recover the authoritative run_id from `signals-scout-runs-list` (your own "
        "in-progress run, matched by skill_name/status) and retry with it. Do not treat this 404 as terminal."
    )


def _to_reviewer_inputs(entries: list[dict] | None) -> list[ReviewerInput] | None:
    """Map validated `suggested_reviewers` entries to `ReviewerInput`s for the report tools. `user_uuid`
    is a `UUID` (from `UUIDField`) — stringified here so the tool layer has no DRF dependency. Empty/None
    yields None so the tool treats it as "no reviewers supplied"."""
    if not entries:
        return None
    return [
        ReviewerInput(
            github_login=entry.get("github_login"),
            user_uuid=str(entry["user_uuid"]) if entry.get("user_uuid") else None,
            reason=entry.get("reason") or None,
        )
        for entry in entries
    ]


def _resolve_emission_report_links(
    team_id: int, canonical_team: Team, emissions: list[SignalScoutEmission], *, log_context: dict
) -> list[dict]:
    """Map each emitted finding to the inbox report (if any) its signal grouped into.

    One ClickHouse round-trip for the whole set: resolve every finding's `source_id` to the
    `report_id` its signal grouped into (best effort — unmatched/deleted findings drop out). Query
    with the canonical team so the injected `document_embeddings.team_id` guard matches where signals
    persist (child-environment requests would otherwise find none). CH/HogQL failures degrade to "no
    links" rather than 500-ing the whole page.

    Hydrate the resolved report ids into minimal projections. Exclude DELETED and SUPPRESSED reports —
    ClickHouse soft-delete and Postgres status can drift, and `SignalReportViewSet` hides both from its
    default retrieve/list flow, so a chip linking to either would deep-link to a page that can't load
    it. Treat that as "no link" rather than a dangling chip.

    Shared by the per-run and batched report endpoints so the link shape stays identical.
    """
    source_ids = [e.source_id for e in emissions if e.source_id]
    source_id_to_report_id: dict[str, str] = {}
    if source_ids:
        try:
            # Deferred: keeps the heavy Signals Temporal workflow/activity graph (dragged in by the
            # `products.signals.backend.temporal` package aggregator) off the route-load path — this
            # viewset is imported by routes.py just to register routes.
            from products.signals.backend.temporal.signal_queries import (
                fetch_report_ids_for_source_ids,  # noqa: PLC0415
            )

            source_id_to_report_id = fetch_report_ids_for_source_ids(canonical_team, source_ids)
        except Exception:
            logger.exception("scout_emission_reports_lookup_failed", team_id=team_id, **log_context)

    report_ids = {rid for rid in source_id_to_report_id.values() if rid}
    reports_by_id = {
        str(row["id"]): row
        for row in SignalReport.objects.filter(team_id=team_id, id__in=report_ids)
        .exclude(status__in=[SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED])
        .values("id", "title", "status")
    }

    links = []
    for emission in emissions:
        report_id = source_id_to_report_id.get(emission.source_id)
        links.append(
            {
                "finding_id": emission.finding_id,
                "source_id": emission.source_id,
                "report": reports_by_id.get(report_id) if report_id else None,
            }
        )
    return links


class SignalScoutRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Run history + finding emission for the headless agent."""

    serializer_class = SignalScoutRunSummarySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    # `.unscoped()` bypasses the fail-closed TeamScopedManager; this class-attribute queryset
    # evaluates at module-load time (before any request → no team context). All read paths
    # in this viewset filter by `team_id` explicitly via the harness helpers, so leaving
    # this unscoped is safe. Same shape `customer_analytics.AccountViewSet` uses.
    queryset = SignalScoutRun.objects.unscoped()
    # Lookup is the run's UUID PK, surfaced as `run_id` to match how the rest of the scout
    # surface (serializers, scratchpad lineage, emission `source_id`) names it — the legacy
    # `id` path param read inconsistently against `run_id` everywhere else. `_parse_run_id_or_404`
    # still accepts both. No `lookup_value_regex` — use DRF's default and let the view actions
    # parse the raw segment with `uuid.UUID()` so malformed IDs return a clean 404 rather than
    # hitting `.filter(id=…)` with a non-UUID and blowing up on Django's UUIDField conversion.
    lookup_field = "run_id"
    # `list` returns a raw newest-first array (capped at limit=100 by the query serializer),
    # not a paginated wrapper. Generated TS clients infer pagination from the global default
    # otherwise, and the runtime shape diverges from the OpenAPI schema. Per-action overrides
    # on POSTs (emit-signal, forget) already disable pagination at the @action level.
    pagination_class = None

    @validated_request(
        query_serializer=SearchRecentRunsQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=SignalScoutRunSummarySerializer(many=True),
                description="Recent run summaries newest-first.",
            ),
        },
        summary="Search recent agent runs",
        description=(
            "Return the most recent `SignalScoutRun` summaries for this project, newest first. "
            "Used by the headless scout to dedupe against work other runs already covered. ILIKE "
            "matches on `summary`. `date_from` / `date_to` are a half-open window on `created_at` "
            "(`>= date_from`, `< date_to`); pass `date_to` on subsequent calls to walk past the "
            "100-row cap. Pass `emitted=true` to see only runs that surfaced at least one finding. "
            "Pass `skill_name` (optionally with `skill_version`) to scope to a single scout. "
            "Results capped at 100."
        ),
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        date_from = validated.get("date_from")
        date_to = validated.get("date_to")
        text = validated.get("text") or None
        emitted = validated.get("emitted")
        skill_name = validated.get("skill_name") or None
        skill_version = validated.get("skill_version")
        limit = validated.get("limit") or 20
        rows = search_recent_runs(
            team_id=_canonical_team_id(self),
            date_from=date_from,
            date_to=date_to,
            text=text,
            emitted=emitted,
            skill_name=skill_name,
            skill_version=skill_version,
            limit=limit,
        )
        return Response(SignalScoutRunSummarySerializer([row.as_dict() for row in rows], many=True).data)

    @validated_request(
        query_serializer=FleetFindingsSummaryQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=FleetFindingsSummarySerializer,
                description="Fleet-wide tally of recent scout output — findings and report activity.",
            ),
        },
        summary="Summarise recent scout output across the fleet",
        description=(
            "Return a cheap fleet-wide tally of the output the scout troop produced in the recent window — "
            "the finding count, the distinct reports authored/edited via the report channel, the number of "
            "distinct scouts behind them, and the latest output time. Backs the 'Scout findings' callout so "
            "it renders from one query instead of the client paging through the whole runs window. Counts "
            "runs that emitted at least one finding (`emitted_count > 0`) or authored/edited an inbox report "
            "within the last `window_hours` (default 72), capped to the most recent 120 such runs so the "
            "count matches what the findings list renders. Strictly team-scoped."
        ),
        operation_id="signals_scout_runs_findings_summary",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="findings/summary",
        required_scopes=["signal_scout:read"],
        pagination_class=None,
    )
    def findings_summary(self, request: Request, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        window_hours = validated.get("window_hours") or DEFAULT_FINDINGS_WINDOW_HOURS
        summary = fleet_findings_summary(team_id=_canonical_team_id(self), window_hours=window_hours)
        return Response(FleetFindingsSummarySerializer(summary.as_dict()).data)

    @extend_schema(
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(response=SignalScoutRunDetailSerializer, description="Full run detail."),
            404: OpenApiResponse(description="Run not found or not visible to this project."),
        },
        summary="Get a run by ID",
        description=(
            "Return the full `SignalScoutRun` row. Status, timing, and error flow from the linked "
            "`tasks.TaskRun`. Strictly team-scoped — a UUID belonging to another team returns 404."
        ),
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        run_id = _parse_run_id_or_404(kwargs)
        detail = get_run(team_id=_canonical_team_id(self), run_id=str(run_id))
        if detail is None:
            raise exceptions.NotFound()
        return Response(SignalScoutRunDetailSerializer(detail.as_dict()).data)

    @extend_schema(
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=SignalScoutEmissionSerializer(many=True),
                description="Findings this run emitted to the inbox, newest first.",
            ),
            404: OpenApiResponse(description="Run not found or not visible to this project."),
        },
        summary="List a run's emitted findings",
        description=(
            "Return the findings a `SignalScoutRun` emitted to the inbox, newest first — one row per emit "
            "with its `description` (the finding text as surfaced), `weight`, `confidence`, `severity`, and "
            "the deterministic `source_id` that joins back to the underlying signal. Lets a team and its "
            "agents see *what* a run surfaced without parsing `emitted_finding_ids` or scanning the signal "
            "store. Strictly team-scoped — a run UUID belonging to another team returns 404."
        ),
        operation_id="signals_scout_runs_emissions",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="emissions",
        required_scopes=["signal_scout:read"],
        pagination_class=None,
    )
    def emissions(self, request: Request, **kwargs) -> Response:
        run_id = _parse_run_id_or_404(kwargs)
        team_id = _canonical_team_id(self)
        # Team-scope the run lookup first so a foreign-team UUID is a clean 404, not an empty list.
        if not SignalScoutRun.objects.filter(id=run_id, team_id=team_id).exists():
            raise exceptions.NotFound()
        # `-id` is the tie-breaker for rows sharing an `emitted_at` (the PK is a time-ordered
        # uuid7, so it sorts consistently with creation order). The hard cap bounds the response:
        # emissions per run are small in practice but nothing in the schema enforces that, so a
        # retry-heavy run shouldn't be able to produce an unbounded payload.
        emissions = SignalScoutEmission.objects.filter(scout_run_id=run_id, team_id=team_id).order_by(
            "-emitted_at", "-id"
        )[:MAX_EMISSIONS_PER_RUN]
        return Response(SignalScoutEmissionSerializer(emissions, many=True).data)

    @validated_request(
        query_serializer=RecentEmissionsQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=SignalScoutEmissionSerializer(many=True),
                description="Recent emitted findings across every run on the team, newest first.",
            ),
        },
        summary="List recent emitted findings across all runs",
        description=(
            "Return the team's recently emitted scout findings across *every* run, newest first — the "
            "cross-run counterpart to the per-run `emissions` action. Each row carries its `run_id`, so "
            "you can regroup by run without first listing runs and fanning out one `emissions` call each. "
            "Pass `skill_name` to scope to a single scout, and `date_from` / `date_to` (a half-open window "
            "on `emitted_at`) to bound or paginate — set `date_to` to the oldest emission's `emitted_at` to "
            "walk back past the limit. Pure Postgres, no ClickHouse round-trip. Capped at "
            f"{MAX_RECENT_EMISSIONS_LIMIT} rows (default {DEFAULT_RECENT_EMISSIONS_LIMIT})."
        ),
        operation_id="signals_scout_runs_recent_emissions",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="emissions/recent",
        required_scopes=["signal_scout:read"],
        pagination_class=None,
    )
    def recent_emissions(self, request: Request, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        team_id = _canonical_team_id(self)
        limit = validated.get("limit") or DEFAULT_RECENT_EMISSIONS_LIMIT

        qs = SignalScoutEmission.objects.filter(team_id=team_id)
        if validated.get("date_from"):
            qs = qs.filter(emitted_at__gte=validated["date_from"])
        if validated.get("date_to"):
            qs = qs.filter(emitted_at__lt=validated["date_to"])
        if validated.get("skill_name"):
            qs = qs.filter(scout_run__skill_name=validated["skill_name"])

        emissions = qs.order_by("-emitted_at", "-id")[:limit]
        return Response(SignalScoutEmissionSerializer(emissions, many=True).data)

    @extend_schema(
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=ScoutEmissionReportLinkSerializer(many=True),
                description="Per-finding inbox report links for this run, newest finding first.",
            ),
            404: OpenApiResponse(description="Run not found or not visible to this project."),
        },
        summary="List the inbox reports a run's findings linked to",
        description=(
            "Best-effort reverse of the report -> signals link. For each finding the run emitted, resolve "
            "the inbox `SignalReport` (if any) its underlying signal grouped into by walking the deterministic "
            "`source_id` back through the signal store. `report` is null when the finding hasn't grouped into a "
            "report yet, was de-duplicated away, or its signal was deleted. Lets the scout UI surface which "
            "inbox report a finding contributed to — the reverse of the report's evidence list. Strictly "
            "team-scoped — a run UUID belonging to another team returns 404."
        ),
        operation_id="signals_scout_runs_emission_reports",
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="emissions/reports",
        # This action returns report titles, so it requires `task:read` (the scope
        # `SignalReportViewSet` gates report reads on) on top of `signal_scout:read` —
        # otherwise a scout-only token could read titles it can't reach canonically.
        required_scopes=["signal_scout:read", "task:read"],
        pagination_class=None,
    )
    def emission_reports(self, request: Request, **kwargs) -> Response:
        run_id = _parse_run_id_or_404(kwargs)
        team_id = _canonical_team_id(self)
        # Team-scope the run lookup first so a foreign-team UUID is a clean 404, not an empty list.
        if not SignalScoutRun.objects.filter(id=run_id, team_id=team_id).exists():
            raise exceptions.NotFound()

        emissions = list(
            SignalScoutEmission.objects.filter(scout_run_id=run_id, team_id=team_id).order_by("-emitted_at", "-id")[
                :MAX_EMISSIONS_PER_RUN
            ]
        )
        canonical_team = self.team.parent_team or self.team
        links = _resolve_emission_report_links(team_id, canonical_team, emissions, log_context={"run_id": str(run_id)})
        return Response(ScoutEmissionReportLinkSerializer(links, many=True).data)

    @validated_request(
        request_serializer=ScoutRunIdsBatchRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=SignalScoutEmissionSerializer(many=True),
                description="Findings emitted across all requested runs, newest first.",
            ),
        },
        summary="List emitted findings for many runs at once",
        description=(
            "Batched form of the per-run emissions endpoint: return the findings every requested "
            "`SignalScoutRun` emitted, flattened newest-first, in a single request. Each row carries its "
            "`run_id`, so the caller can regroup by run. The findings UI uses this to load the whole "
            "recent window in one round-trip instead of one request per run. Strictly team-scoped — run "
            "ids belonging to another team contribute no rows (no per-run 404; one stale id never fails "
            "the batch)."
        ),
        operation_id="signals_scout_runs_emissions_batch",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="emissions/batch",
        required_scopes=["signal_scout:read"],
        pagination_class=None,
    )
    def emissions_batch(self, request: Request, **kwargs) -> Response:
        run_ids = request.validated_data["run_ids"]
        team_id = _canonical_team_id(self)
        # `team_id` is the tenant guard, so a foreign run id simply matches no rows — no per-run
        # existence check. One global cap bounds the payload (realistic fleets stay well under it).
        emissions = SignalScoutEmission.objects.filter(scout_run_id__in=run_ids, team_id=team_id).order_by(
            "-emitted_at", "-id"
        )[:MAX_EMISSIONS_PER_BATCH]
        return Response(SignalScoutEmissionSerializer(emissions, many=True).data)

    @validated_request(
        request_serializer=ScoutRunIdsBatchRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ScoutEmissionReportLinkSerializer(many=True),
                description="Per-finding inbox report links across all requested runs, newest finding first.",
            ),
        },
        summary="List the inbox reports many runs' findings linked to",
        description=(
            "Batched form of the per-run emission-reports endpoint. For every finding the requested runs "
            "emitted, resolve the inbox `SignalReport` (if any) its signal grouped into — all in a single "
            "ClickHouse round-trip rather than one query per run, which is what made the findings page "
            "slow to open. `report` is null when a finding hasn't grouped yet, was de-duplicated, or its "
            "signal was deleted. Strictly team-scoped — run ids belonging to another team contribute no "
            "rows."
        ),
        operation_id="signals_scout_runs_emission_reports_batch",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="emissions/reports/batch",
        # Returns report titles, so it requires `task:read` on top of `signal_scout:read` — same as the
        # per-run `emission_reports` action; a scout-only token must not read titles it can't reach.
        required_scopes=["signal_scout:read", "task:read"],
        pagination_class=None,
    )
    def emission_reports_batch(self, request: Request, **kwargs) -> Response:
        run_ids = request.validated_data["run_ids"]
        team_id = _canonical_team_id(self)
        emissions = list(
            SignalScoutEmission.objects.filter(scout_run_id__in=run_ids, team_id=team_id).order_by(
                "-emitted_at", "-id"
            )[:MAX_EMISSIONS_PER_BATCH]
        )
        canonical_team = self.team.parent_team or self.team
        links = _resolve_emission_report_links(
            team_id, canonical_team, emissions, log_context={"run_count": len(run_ids)}
        )
        return Response(ScoutEmissionReportLinkSerializer(links, many=True).data)

    @validated_request(
        request_serializer=EmitFindingRequestSerializer,
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=EmitFindingResponseSerializer, description="Finding emitted, or skipped by a preflight gate."
            ),
            400: OpenApiResponse(description="Invalid emit shape (description, weight, confidence, evidence cap)."),
            404: OpenApiResponse(description="Run not found for this project."),
        },
        summary="Emit a finding for a run",
        description=(
            "Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the "
            "deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT "
            "idempotent — a second call with the same `finding_id` emits a second signal, so do not retry "
            "an emit that may have already succeeded."
        ),
        operation_id="signals_scout_emit_signal",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="emit-signal",
        required_scopes=["signal_scout_internal:write"],
        pagination_class=None,
    )
    def emit_signal(self, request: Request, **kwargs) -> Response:
        run_id = _parse_run_id_or_404(kwargs)
        from products.tasks.backend.facade import api as tasks_facade

        run = (
            SignalScoutRun.objects.select_related("scout_config", "task_run")
            .filter(team_id=_canonical_team_id(self), id=run_id)
            .first()
        )
        if run is None:
            raise _run_write_not_found(run_id)
        if run.task_run.status != tasks_facade.TaskRunStatus.IN_PROGRESS:
            raise exceptions.ValidationError(
                {"status": f"Findings can only be emitted on in-progress runs (current: {run.task_run.status})."}
            )

        data = request.validated_data
        time_range = data.get("time_range")
        time_range_tuple: tuple[str, str] | None = None
        if time_range:
            time_range_tuple = (time_range["date_from"], time_range["date_to"])

        evidence_payload = data.get("evidence") or []
        evidence = [
            EvidenceEntry(
                source_product=entry["source_product"],
                summary=entry["summary"],
                entity_id=entry.get("entity_id"),
            )
            for entry in evidence_payload
        ]

        try:
            result = emit_finding_sync(
                team=self.team,
                run=run,
                description=data["description"],
                confidence=data["confidence"],
                evidence=evidence,
                hypothesis=data.get("hypothesis") or None,
                severity=data.get("severity") or None,
                dedupe_keys=data.get("dedupe_keys") or None,
                time_range=time_range_tuple,
                mcp_trace_id=data.get("mcp_trace_id") or None,
                finding_id=data.get("finding_id") or None,
                tags=data.get("tags") or None,
            )
        except InvalidEmitError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})

        return Response(
            EmitFindingResponseSerializer(
                {
                    "finding_id": result.finding_id,
                    "emitted": result.emitted,
                    "skipped_reason": result.skipped_reason,
                    "remediation": result.remediation,
                }
            ).data,
            status=status.HTTP_200_OK,
        )

    def _resolve_in_progress_run(self, kwargs: dict, *, required_tool: str) -> SignalScoutRun:
        """Resolve the run for a report-channel write action: team-scoped lookup + the same in-progress
        guard `emit_signal` uses, plus the `allowed_tools` opt-in gate. A report is authored *during* a
        run, so a finished run can't author one.

        The report channel is opt-in by `allowed_tools`. Tool *exposure* is already gated at the scope
        layer — the runner grants the `signals_scout_reports` posture (which carries
        `signal_scout_report:write`, the scope these actions require) only when the skill opted in, so a
        non-opted scout never sees the tools and its token can't satisfy `required_scopes`. This server-side
        check is the matching fail-closed gate on the write itself: reject unless the run's skill lists
        `required_tool` in its `allowed_tools`, so the two enforcement layers can't drift."""
        run_id = _parse_run_id_or_404(kwargs)
        from products.tasks.backend.facade import api as tasks_facade

        run = (
            SignalScoutRun.objects.select_related("scout_config", "task_run", "team")
            .filter(team_id=_canonical_team_id(self), id=run_id)
            .first()
        )
        if run is None:
            raise _run_write_not_found(run_id)
        if run.task_run.status != tasks_facade.TaskRunStatus.IN_PROGRESS:
            raise exceptions.ValidationError(
                {"status": f"Reports can only be authored on in-progress runs (current: {run.task_run.status})."}
            )
        self._assert_report_tool_opted_in(run, required_tool)
        return run

    def _assert_report_tool_opted_in(self, run: SignalScoutRun, required_tool: str) -> None:
        """Fail closed unless the run's skill opted into `required_tool` via `allowed_tools`. Loads the
        exact skill version the run snapshotted so the gate matches what actually ran; a missing/unloadable
        skill is treated as not-opted-in (deny)."""
        # `run.team` is the canonical team the run was resolved on (the query above filters on
        # `_canonical_team_id`), and is where the scout's `LLMSkill` rows are seeded.
        try:
            skill = load_skill_for_run(run.team, run.skill_name, version=run.skill_version)
        except SkillNotFoundError:
            raise exceptions.PermissionDenied(
                f"Report channel is opt-in; skill '{run.skill_name}' (v{run.skill_version}) could not be "
                "resolved to verify its allowed_tools."
            )
        if required_tool not in skill.allowed_tools:
            raise exceptions.PermissionDenied(
                f"Report channel is opt-in: skill '{run.skill_name}' must list '{required_tool}' in its "
                "allowed_tools to use this tool."
            )

    @validated_request(
        request_serializer=EmitReportRequestSerializer,
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=EmitReportResponseSerializer,
                description="Report authored (READY/PENDING_INPUT/suppressed), or skipped by a preflight gate.",
            ),
            400: OpenApiResponse(description="Invalid report shape (empty title/summary/evidence, bad actionability)."),
            404: OpenApiResponse(description="Run not found for this project."),
        },
        summary="Author a full report for a run",
        description=(
            "The second emit channel: author a complete `SignalReport` directly instead of emitting a weak "
            "signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` "
            "call implies (or is suppressed). Backing `evidence` is written as bound signals so the report "
            "behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to "
            "find a prior report and `edit-report` to update it instead."
        ),
        operation_id="signals_scout_emit_report",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="emit-report",
        required_scopes=["signal_scout_report:write"],
        pagination_class=None,
    )
    def emit_report(self, request: Request, **kwargs) -> Response:
        run = self._resolve_in_progress_run(kwargs, required_tool="emit_report")
        data = request.validated_data
        evidence = [
            ReportEvidence(
                description=entry["description"],
                source_id=entry["source_id"],
                **({"weight": entry["weight"]} if entry.get("weight") is not None else {}),
            )
            for entry in data["evidence"]
        ]
        try:
            result = emit_report_sync(
                # `run.team` is the canonical (parent) team the run was resolved on; a child-environment
                # request's `self.team` would mismatch the run's owner and trip `_assert_team_owns_run`.
                team=run.team,
                run=run,
                title=data["title"],
                summary=data["summary"],
                evidence=evidence,
                actionability_explanation=data["actionability_explanation"],
                actionability=data["actionability"],
                already_addressed=data.get("already_addressed", False),
                repository=data.get("repository"),
                priority=data.get("priority"),
                priority_explanation=data.get("priority_explanation"),
                suggested_reviewers=_to_reviewer_inputs(data.get("suggested_reviewers")),
            )
        except InvalidScoutReportError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})
        return Response(
            EmitReportResponseSerializer(
                {
                    "report_id": result.report_id,
                    "report_status": result.status,
                    "emitted": result.emitted,
                    "skipped_reason": result.skipped_reason,
                    "safety_explanation": result.safety_explanation,
                    "remediation": result.remediation,
                }
            ).data,
            status=status.HTTP_200_OK,
        )

    @validated_request(
        request_serializer=EditReportRequestSerializer,
        parameters=[_RUN_ID_PATH_PARAMETER],
        responses={
            200: OpenApiResponse(response=EditReportResponseSerializer, description="Report edited."),
            400: OpenApiResponse(description="Nothing to edit, empty note, or report not found for this project."),
            404: OpenApiResponse(description="Run not found for this project."),
        },
        summary="Edit an existing report for a run",
        description=(
            "Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target "
            "ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to "
            "this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it "
            "replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can "
            "open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them."
        ),
        operation_id="signals_scout_edit_report",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="edit-report",
        required_scopes=["signal_scout_report:write"],
        pagination_class=None,
    )
    def edit_report(self, request: Request, **kwargs) -> Response:
        run = self._resolve_in_progress_run(kwargs, required_tool="edit_report")
        data = request.validated_data
        try:
            result = edit_report_sync(
                # Canonical team, as in `emit_report` above — avoids a child-env `_assert_team_owns_run` trip.
                team=run.team,
                run=run,
                report_id=data["report_id"],
                title=data.get("title"),
                summary=data.get("summary"),
                append_note=data.get("append_note"),
                suggested_reviewers=_to_reviewer_inputs(data.get("suggested_reviewers")),
            )
        except InvalidScoutReportError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})
        return Response(
            EditReportResponseSerializer(
                {
                    "report_id": result.report_id,
                    "updated_fields": result.updated_fields,
                    "note_appended": result.note_appended,
                    "reviewers_set": result.reviewers_set,
                }
            ).data,
            status=status.HTTP_200_OK,
        )

    # `EvidenceEntrySerializer` is referenced for OpenAPI nested-schema discovery; keep
    # the import live so drf-spectacular registers it even if the runtime never imports
    # it directly inside this module.
    _EVIDENCE_SHAPE = EvidenceEntrySerializer


class SignalScratchpadViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Durable agent memories (`SignalScratchpad`) — read, write, and delete.

    Reads (`list`) use the public `signal_scout:read` scope by inheriting the
    viewset's `scope_object`. Writes (`create`, `forget`) elevate to the
    internal-only `signal_scout_internal:write` scope — `forget` carries it
    on its `@action`, and `create` (a built-in DRF method) gets it via the
    `dangerously_get_required_scopes` hook below.
    """

    serializer_class = ScratchpadEntrySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    # `list` returns a raw newest-first array (capped at limit=1000 by the query serializer),
    # not a paginated wrapper. See SignalScoutRunViewSet for the same rationale.
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        # `create` is a default DRF action so it has no `@action` decorator to set
        # `required_scopes`; without this override the permission would resolve to
        # `signal_scout:write` (user-grantable) and let any team member with a PAK
        # write durable memories. Map it to the internal scope explicitly.
        if getattr(view, "action", None) == "create":
            return ["signal_scout_internal:write"]
        return None

    @validated_request(
        query_serializer=SearchMemoryQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=ScratchpadEntrySerializer(many=True),
                description="Matching memory entries newest-first.",
            ),
        },
        summary="Search the scout scratchpad",
        description=(
            "Return `SignalScratchpad` entries for this project, newest-first. ILIKE matches on `content` "
            "and `key`; pass `key` instead for an exact single-entry lookup. "
            "`date_from` / `date_to` are a half-open window on `updated_at` (`>= date_from`, "
            "`< date_to`); pass `date_to` (the `updated_at` of the oldest entry seen) on subsequent calls "
            "to walk past the cap. Pass `keys_only=true` to scan keys without pulling entry bodies, or "
            "`content_max_chars` to cap each `content` to a preview — both keep a wide orientation scan "
            "from returning every entry's full prose. Results capped at 1000."
        ),
        operation_id="signals_scout_scratchpad_search",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        text = validated.get("text") or None
        date_from = validated.get("date_from")
        date_to = validated.get("date_to")
        keys_only = bool(validated.get("keys_only", False))
        content_max_chars = validated.get("content_max_chars")
        limit = validated.get("limit") or 20
        rows = search_scratchpad(
            team_id=_canonical_team_id(self),
            text=text,
            key=validated.get("key") or None,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            keys_only=keys_only,
            content_max_chars=content_max_chars,
        )
        return Response(ScratchpadEntrySerializer([row.as_dict() for row in rows], many=True).data)

    @validated_request(
        request_serializer=RememberRequestSerializer,
        responses={
            200: OpenApiResponse(response=ScratchpadEntrySerializer, description="Memory entry written or refreshed."),
            400: OpenApiResponse(description="Invalid memory shape (empty key/content, key too long)."),
        },
        summary="Remember a scratchpad entry",
        description=("Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place."),
        operation_id="signals_scout_scratchpad_remember",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        data = request.validated_data
        run_id = data.get("run_id") or None
        # `run_id` only stamps best-effort `created_by_run_id` lineage — a memory write must
        # never be lost over it. So an unverifiable `run_id` is dropped (lineage left null),
        # not rejected. We still won't stamp a `run_id` that isn't a run on this project: the
        # agent's MCP token pins us to a team, but `run_id` is a free field on the body and a
        # foreign-team UUID would otherwise create a cross-team `created_by_run_id` reference.
        # Bad UUIDs are blocked by `UUIDField` in the serializer.
        if (
            run_id is not None
            and not SignalScoutRun.objects.filter(id=run_id, team_id=_canonical_team_id(self)).exists()
        ):
            run_id = None
        try:
            entry = remember(
                team_id=_canonical_team_id(self),
                key=data["key"],
                content=data["content"],
                run_id=str(run_id) if run_id is not None else None,
            )
        except InvalidScratchpadError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})
        return Response(ScratchpadEntrySerializer(entry.as_dict()).data, status=status.HTTP_200_OK)

    @validated_request(
        request_serializer=ForgetRequestSerializer,
        responses={
            200: OpenApiResponse(response=ForgetResponseSerializer, description="Whether a row was removed."),
        },
        summary="Forget a scratchpad entry by key",
        description="Delete an entry by key. Returns `deleted=false` if no row matched.",
        operation_id="signals_scout_scratchpad_forget",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="forget",
        required_scopes=["signal_scout_internal:write"],
        pagination_class=None,
    )
    def forget(self, request: Request, **kwargs) -> Response:
        data = request.validated_data
        removed = forget(team_id=_canonical_team_id(self), key=data["key"])
        return Response(ForgetResponseSerializer({"deleted": removed}).data)


class ScoutCanonicalTeamAccessPermission(BasePermission):
    """Authorize against the canonical (data-owning) team, not just the URL environment team.

    Scout notes are `TeamScopedRootMixin` rows that canonicalize to the parent (project-root)
    team on save, so a request made against a child environment reads and writes the PARENT's
    rows (`_canonical_team_id`). The default team gate only checks membership / token
    team-scope for the URL team, so a user or key scoped solely to a child environment would
    be authorized against one team while touching another's rows. Re-anchor both checks to
    the canonical team. Mirrors `StamphogCanonicalTeamAccessPermission`. Root teams (no
    parent) are unaffected — the default checks already cover them.
    """

    message = "You don't have access to the project that owns this data."

    def has_permission(self, request: Request, view) -> bool:
        if not request.user.is_authenticated:
            return True  # IsAuthenticated handles the unauthenticated case first
        team = view.team
        if team.parent_team_id is None or team.parent_team_id == team.id or team.parent_team is None:
            return True
        # A team-scoped token must cover the CANONICAL team too: the default scope check
        # accepted the URL (child) team, but the rows read and written belong to the parent.
        authenticator = request.successful_authenticator
        scoped_teams = None
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            scoped_teams = authenticator.access_token.scoped_teams
        elif isinstance(authenticator, PersonalAPIKeyAuthentication):
            scoped_teams = authenticator.personal_api_key.scoped_teams
        if scoped_teams and team.parent_team_id not in scoped_teams:
            return False
        # Same helper the default gate uses, re-pointed at the parent. It accounts for a
        # private parent team, so None means genuinely no access -> 403.
        level = view.user_permissions.team(team.parent_team).effective_membership_level
        return level is not None


class SignalScoutNoteViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Steering notes for the scout fleet (`SignalScoutNote`) — list, leave, and delete.

    Unlike the scratchpad (agent memory, write-gated to the sandbox), notes are the
    *inbound* channel: a team member — or an agent acting for one — leaves a note over the
    public MCP surface, and scout runs read it back as prior context. Reads sit on the
    user-grantable `signal_scout:read`. Writes are the prompt-injection surface the
    scratchpad's internal-only gate exists to block, so they demand skill-authoring-level
    authorization on both legs: API keys need `llm_skill:write` on top of
    `signal_scout:write` (see `dangerously_get_required_scopes`), and every writer must
    clear the same `llm_skill` RBAC editor bar that gates editing a scout's skill body
    (`_assert_can_steer_scouts`). A caller who can write a note could therefore already
    steer the fleet by editing its skills — notes add a cheaper channel, not new power.
    """

    serializer_class = ScoutNoteSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_scout"
    # `destroy` resolves the note through `_parse_run_id_or_404`, which reads the `id` kwarg.
    lookup_field = "id"
    # `list` returns a raw newest-first array (capped by the query serializer), not a
    # paginated wrapper. See SignalScoutRunViewSet for the same rationale.
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        # Both scopes are required (the permission ANDs them): `signal_scout:write` says the
        # key may act on the scout surface, `llm_skill:write` says it may author what a
        # privileged agent reads verbatim — the same capability as editing a scout's skill.
        if getattr(view, "action", None) in ("create", "destroy"):
            return ["signal_scout:write", "llm_skill:write"]
        return None

    def _assert_can_steer_scouts(self) -> None:
        # RBAC leg of the write gate: session callers (and key holders) must hold the same
        # `llm_skill` editor level that editing a scout's skill body requires — a member an
        # admin restricted from skill editing must not steer scouts through notes instead.
        # Bind the check to the CANONICAL team: the note lands on (and is read by) the parent
        # project's scouts, so a child-environment request must clear the parent's RBAC, not
        # the child's — mirroring `ScoutCanonicalTeamAccessPermission` for the resource level.
        # (`self.user_access_control` binds to the URL team, hence the explicit construction.)
        canonical_team = self.team.parent_team or self.team
        access = UserAccessControl(user=cast(User, self.request.user), team=canonical_team)
        if not access.check_access_level_for_resource("llm_skill", "editor"):
            raise exceptions.PermissionDenied(
                "Leaving or deleting scout notes requires editor access to skills, since notes steer the scout agents."
            )

    @validated_request(
        query_serializer=ScoutNotesQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=ScoutNoteSerializer(many=True),
                description="Matching notes newest-first.",
            ),
        },
        summary="List scout notes",
        description=(
            "Return the steering notes left for this project's scouts, newest first. Pass "
            "`skill_name` to get the notes addressed to one scout plus the general (blank-target) "
            "fleet-wide notes — the shape a scout run reads at cold start. Omit `skill_name` to "
            "browse every note. Expired notes are excluded unless `include_expired=true`. "
            "`date_from` / `date_to` are a half-open window on `created_at` (`>= date_from`, "
            "`< date_to`); pass `date_to` (the `created_at` of the oldest note seen) to walk past "
            "the cap. Results capped at 500."
        ),
        operation_id="signals_scout_notes_list",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        rows = list_notes(
            team_id=_canonical_team_id(self),
            skill_name=validated.get("skill_name") or None,
            include_general=bool(validated.get("include_general", True)),
            include_expired=bool(validated.get("include_expired", False)),
            date_from=validated.get("date_from"),
            date_to=validated.get("date_to"),
            limit=validated.get("limit") or DEFAULT_NOTES_LIST_LIMIT,
            content_max_chars=validated.get("content_max_chars"),
        )
        return Response(ScoutNoteSerializer([row.as_dict() for row in rows], many=True).data)

    @validated_request(
        request_serializer=ScoutNoteCreateRequestSerializer,
        responses={
            201: OpenApiResponse(response=ScoutNoteSerializer, description="The note as created."),
            400: OpenApiResponse(description="Invalid note (empty content, oversized, bad skill_name target)."),
        },
        summary="Leave a note for the scouts",
        description=(
            "Leave a steering note the scout fleet reads on its next runs. Address it to one scout "
            "via `skill_name` (`signals-scout-*`), or omit it for a general note every scout sees. "
            "Each call creates a new note (no upsert); delete retires one. Attributed to the "
            "authenticated user."
        ),
        operation_id="signals_scout_notes_create",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        self._assert_can_steer_scouts()
        data = request.validated_data
        # `request.user` is a real `User` under all three auth classes here; `pk` guards the
        # theoretical anonymous edge so attribution degrades to null instead of raising.
        created_by_id = request.user.pk if getattr(request.user, "pk", None) else None
        try:
            note = leave_note(
                team_id=_canonical_team_id(self),
                content=data["content"],
                skill_name=data.get("skill_name") or "",
                created_by_id=created_by_id,
                expires_at=data.get("expires_at"),
            )
        except InvalidNoteError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})
        return Response(ScoutNoteSerializer(note.as_dict()).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={
            204: OpenApiResponse(description="Note deleted."),
            404: OpenApiResponse(description="Note not found for this project."),
        },
        summary="Delete a scout note",
        description=(
            "Delete one note by its `id`, retiring it from every scout's view. Use this when a note "
            "has been acted on or no longer applies; time-boxed notes can instead carry an "
            "`expires_at` and retire themselves."
        ),
        operation_id="signals_scout_notes_destroy",
    )
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        self._assert_can_steer_scouts()
        note_id = _parse_run_id_or_404(kwargs)
        removed = delete_note(team_id=_canonical_team_id(self), note_id=str(note_id))
        if not removed:
            raise exceptions.NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SignalProjectProfileViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Project profile — deterministic snapshot of \"what's true about this project\".

    Singleton per team — there's no list, retrieve, or write surface. The agent calls
    `current` right after reading its skill to orient on this team's product mix,
    integrations, signal coverage, and existing inbox surface in one tool call instead of
    burning 4-5 discovery calls. Lazy-recomputes on cache miss / TTL expiry / source-version
    bump; the response is always either the latest cached profile or a freshly-built one.

    Exposed as a `@action(detail=False, url_path="current")` rather than `list()` so the
    OpenAPI spec — and every generated client downstream of it (`api.ts`, MCP tool
    response shape, etc.) — types the response as a single `ProjectProfileApi` instead
    of `ProjectProfileApi[]`. drf-spectacular and Orval treat the bare `list` action as
    a paginated collection by URL convention even when `responses=ProjectProfileSerializer`
    is set; routing through a named action breaks that convention without changing the
    semantics.
    """

    serializer_class = ProjectProfileSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    # `.unscoped()` — see `SignalScoutRunViewSet` for the same module-load reasoning.
    # The `current` action filters by team_id explicitly via `get_project_profile`.
    queryset = SignalProjectProfile.objects.unscoped()
    pagination_class = None

    # The DRF default `list` operation_id would be `signals_scout_project_profile_list`,
    # which renders as `scout-project-profile-list` in the MCP. The agent-facing
    # tool is semantically a "get the current profile" (singleton), not a "list" — override
    # the id so it matches the tool name in tools.yaml and the scout's bootstrap step.
    @validated_request(
        operation_id="signals_scout_project_profile_get",
        query_serializer=ProjectProfileQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=ProjectProfileSerializer,
                description="The team's current project profile (cached, or freshly built for the internal scout token).",
            ),
            404: OpenApiResponse(
                description=(
                    "No profile has been built for this team yet, and the caller is not the internal scout "
                    "token (which builds on cache miss). Public read callers never trigger a build."
                ),
            ),
        },
        summary="Get the current project profile",
        description=(
            "Return the team's deterministic project profile. For the internal scout token the response "
            "reflects the newest non-expired cached row or a freshly-built one (lazy compute on cache miss); "
            "`force_refresh=true` skips the cache and rebuilds from authoritative sources. Public read callers "
            "(session auth or a `signal_scout:read` PAK) get the newest cached profile, or 404 if none has been "
            "built yet — they never trigger a rebuild. Read this at the start of a run to orient on the team's "
            "product mix, integrations, warehouse sources, signal coverage, and existing inbox surface."
        ),
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="current",
        url_name="current",
        pagination_class=None,
        # Without explicit `required_scopes`, `APIScopePermission` falls into the
        # "no scopes declared" branch in `posthog/permissions.py:490` and rejects
        # the request — the rejection message even reads "does not support
        # personal API key access" regardless of whether the request was
        # authenticated via PAK or OAuth, because that branch fires for both.
        # `signal_scout:read` is the public, user-grantable read scope already
        # used by `runs-list`, `runs-retrieve`, and `memory-list` on this surface.
        required_scopes=["signal_scout:read"],
    )
    def current(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        caller_is_internal_scout = _caller_carries_scout_internal_scope(request)
        # Both `force_refresh` and the lazy build-on-miss run the full inventory rebuild
        # (per-section table scans + the ClickHouse top-events aggregation) and write a row,
        # so both are gated to the internal scout token. A session-authenticated GET bypasses
        # CSRF (safe method), so letting it build would make the rebuild CSRF-triggerable; a
        # `signal_scout:read` PAK could likewise spam recomputes. Untrusted read callers get
        # the newest cached profile, or a 404 if none exists — they never trigger a build. The
        # scout's sandbox token carries `signal_scout_internal:write`, and the Phase-7 Temporal
        # workflow builds out-of-band, so the build path stays covered.
        force_refresh = bool(validated.get("force_refresh", False)) and caller_is_internal_scout
        profile = get_project_profile(
            team_id=_canonical_team_id(self),
            force_refresh=force_refresh,
            lazy_build=caller_is_internal_scout,
        )
        if profile is None:
            raise exceptions.NotFound("No project profile has been built for this team yet.")
        return Response(ProjectProfileSerializer(profile.as_dict()).data)


class SignalScoutMetadataViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Team-scoped scout metadata: enrollment, the alpha banner, and the enforced run limits.

    All resolved from the `signals-scout` flag payload — the same read and three-layer cap
    resolution the coordinator applies at dispatch — so the UI shows the *enforced* throttle, not
    what a user assumes they set. Read-only and side-effect free.

    Exposed via a `current` action rather than `list` for the same reason as
    `SignalProjectProfileViewSet`: a bare `list` action types the response as a paginated
    collection downstream (drf-spectacular / Orval), and this is a singleton.
    """

    serializer_class = ScoutMetadataSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    # No model backs this endpoint — metadata is computed from the flag payload. A real queryset is
    # still required to satisfy the team/org viewset mixin; the `current` action never reads it.
    queryset = SignalScoutConfig.objects.unscoped()
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ScoutMetadataSerializer,
                description="This project's scout enrollment, announcement banner, and enforced run limits.",
            ),
        },
        summary="Get scout metadata",
        description=(
            "Return the project's scout metadata: whether it is enrolled, the current announcement "
            "banner (e.g. an alpha run-limit notice, or null when unset), and the enforced run "
            "limits with current usage. Limits reflect what the coordinator actually applies at "
            "dispatch, so a user can see the real throttle rather than what they assume they set. "
            "All values come from the `signals-scout` flag payload, so the banner and caps can "
            "change with no deploy."
        ),
        operation_id="signals_scout_metadata_get",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="current",
        url_name="current",
        pagination_class=None,
        # `signal_scout:read` is the public, user-grantable read scope used across this surface;
        # without explicit `required_scopes` APIScopePermission rejects the request outright.
        required_scopes=["signal_scout:read"],
    )
    def current(self, request: Request, *args, **kwargs) -> Response:
        metadata = resolve_team_metadata(_canonical_team_id(self))
        return Response(ScoutMetadataSerializer(metadata.as_dict()).data)


class SignalScoutMembersViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Project member roster for reviewer routing — sandbox-only.

    `scope_object = "signal_scout_internal"` makes this a strictly scout-run-only surface: the object is
    in `INTERNAL_API_SCOPE_OBJECTS`, so session auth, personal API keys, and the `*` consent wildcard are
    all rejected (`posthog/permissions.py`), and only a harness sandbox OAuth token — which carries
    `signal_scout_internal:write`, satisfying the default `list` action's `signal_scout_internal:read`
    requirement (write implies read) — can reach it. The roster is member PII (emails, names, GitHub
    logins), and this gate keeps it off every user-grantable credential and out of a customer's public MCP
    catalog — the same internal-vs-external boundary as `emit-signal`, the other internal-scope scout tool.
    The narrower `signal_scout_report` scope (report-channel scouts only) would tighten this to the tool's
    sole consumer, but that scope is transient — a temporary split kept only while emit-signal and
    emit-report coexist — so a durable tool stays on `signal_scout_internal` rather than coupling to a scope
    slated for removal. The residual exposure (a baseline scout reading its own team's roster) is bounded to
    the single-team sandbox token.

    The roster is resolved server-side (a plain ORM read via `Team.all_users_with_access()`, not a DRF
    request through the OAuth permission layer), which is why the org-nested `org-members-list` tool —
    stripped from a scoped-team token's catalog and 403'd by the org-nested permission gate — can't serve
    this and a project-nested tool can. Scoping through `all_users_with_access()` (not the whole org) keeps
    a scout on a private project from enumerating members who lack access to it.
    """

    serializer_class = ScoutMemberSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout_internal"
    # No team-scoped model backs this endpoint — members are resolved from project access. A queryset is
    # still required to satisfy the team/org viewset mixin; `list` never reads it. Mirrors
    # `SignalScoutMetadataViewSet`.
    queryset = SignalScoutConfig.objects.unscoped()
    pagination_class = None

    @validated_request(
        query_serializer=ScoutMembersQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=ScoutMemberSerializer(many=True),
                description="The project's members, each with their routing identity.",
            ),
        },
        summary="List project members for reviewer routing",
        description=(
            "Return the people who can review work on this project — one row per member with access to it, "
            "each with their `user_uuid`, `email`, `first_name`/`last_name`, and resolved GitHub `login` (null "
            "when they have no linked GitHub identity). The cold-start reviewer-routing path: when a finding's "
            "owner can't be read off a fetched entity's `created_by` and there's no cached `reviewer:<area>` "
            "memory or inbox precedent, list members, match the owner by email/name, then put their resolved "
            "`github_login` in `suggested_reviewers` on `emit-report` / `edit-report`. Pass `search` to narrow "
            f"a large roster; the result is capped at {MAX_PROJECT_MEMBERS}. Strictly team-scoped."
        ),
        operation_id="signals_scout_members_list",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        canonical_team = self.team.parent_team or self.team
        members = list_project_members(canonical_team, search=validated.get("search") or None)
        return Response(ScoutMemberSerializer([dataclasses.asdict(member) for member in members], many=True).data)


def _reject_if_enabled_cap_reached(team_id: int, skill_name: str) -> None:
    """Raise when enabling this scout would push the team past the per-team enabled cap.

    Counts every enabled config except this skill's own row, so re-asserting
    `enabled=True` on an already-enabled scout is always allowed. Best-effort
    (count + write, no lock): a concurrent enable can overshoot by one, which the
    coordinator's per-tick caps still bound.
    """
    if enabled_scout_count(team_id, exclude_skill=skill_name) >= MAX_ENABLED_SCOUTS_PER_TEAM:
        raise exceptions.ValidationError(
            {
                "enabled": (
                    f"This project already has {MAX_ENABLED_SCOUTS_PER_TEAM} enabled scouts (the maximum). "
                    "Disable one before enabling another."
                )
            }
        )


def _upsert_scout_config(
    *,
    team_id: int,
    skill_name: str,
    tunables: dict,
    request: Request,
    serializer_context: dict,
) -> tuple[SignalScoutConfig, bool]:
    """Create or tune one config while preserving the existing config endpoint's upsert semantics."""

    # The per-team cap only gates net-new enables: creating an enabled row or
    # flipping a disabled row on. Reasserting an already-enabled scout stays exempt.
    existing = SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).first()
    will_enable = (
        tunables.get("enabled", True)
        if existing is None
        else (not existing.enabled and tunables.get("enabled") is True)
    )
    if will_enable:
        _reject_if_enabled_cap_reached(team_id, skill_name)

    # `team_id` stays in the kwargs because queryset filters do not propagate into
    # the row Django builds for `get_or_create`.
    config, created = SignalScoutConfig.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        skill_name=skill_name,
        defaults={
            **tunables,
            "created_by": request.user,
            "enabled_by": request.user if tunables.get("enabled", True) else None,
        },
    )
    if created or not tunables:
        return config, created

    # The coordinator or another caller may have won the create race. Apply only
    # fields supplied by this request so omitted settings remain untouched.
    update = SignalScoutConfigUpdateSerializer(
        config,
        data=tunables,
        partial=True,
        context=serializer_context,
    )
    update.is_valid(raise_exception=True)
    save_kwargs = {}
    if not config.enabled and update.validated_data.get("enabled"):
        save_kwargs["enabled_by"] = request.user
    return update.save(**save_kwargs), False


def _skill_matches_scout_definition(
    skill: LLMSkill,
    *,
    description: str,
    body: str,
    files: list[dict[str, str]],
) -> bool:
    stored_files = list(
        LLMSkillFile.objects.filter(skill=skill).order_by("path").values_list("path", "content", "content_type")
    )
    requested_files = sorted((file["path"], file["content"], file.get("content_type", "text/plain")) for file in files)
    return (
        skill.description == description
        and skill.body == body
        and skill.category == "scout"
        and skill.license == ""
        and skill.compatibility == ""
        and skill.metadata == {}
        and set(skill.allowed_tools or []) == REPORT_CHANNEL_TOOLS
        and stored_files == requested_files
    )


@dataclass(frozen=True)
class _ScoutSkillInfo:
    """Per-skill metadata the config serializer needs but doesn't store on the config row.

    Both fields come from the team's latest `LLMSkill` row for the scout, resolved by the
    view in one query so the list endpoint stays a single lookup rather than one per config.
    """

    description: str
    origin: str  # "canonical" | "custom" — see `lazy_seed.scout_skill_origin`.


def _skill_info_for(team_id: int, skill_names: list[str]) -> dict[str, _ScoutSkillInfo]:
    """Map each scout `skill_name` to its latest `LLMSkill` description + origin on the team.

    One query for the whole config list — feeds the serializer's `description` and `origin`
    fields so callers get a quick steer on each scout (and whether it's a canonical or
    hand-authored scout) without loading the full skill body. Skills the team no longer has
    simply drop out of the map (serializer falls back to "" / "custom").
    """
    names = list(set(skill_names))
    if not names:
        return {}
    rows = LLMSkill.objects.filter(team_id=team_id, name__in=names, is_latest=True, deleted=False).values_list(
        "name", "description", "metadata"
    )
    return {
        name: _ScoutSkillInfo(description=description or "", origin=scout_skill_origin(name, metadata))
        for name, description, metadata in rows
    }


class SignalScoutViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Create a runnable custom scout and its config through one atomic API call."""

    serializer_class = SignalScoutCreateSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        AccessControlPermission,
        ScoutCanonicalTeamAccessPermission,
    ]
    required_scopes = ["llm_skill:write", "signal_scout:write"]
    scope_object = "llm_skill"
    queryset = LLMSkill.objects.all()
    pagination_class = None

    def _assert_can_create_scout(self, *, user: User, canonical_team: Team) -> None:
        access = UserAccessControl(user=user, team=canonical_team)
        if not access.check_access_level_for_resource("llm_skill", "editor"):
            raise exceptions.PermissionDenied("Creating a scout requires editor access to skills.")

    @validated_request(
        SignalScoutCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=SignalScoutCreateResponseSerializer,
                description="The scout skill, config, or both were created.",
            ),
            200: OpenApiResponse(
                response=SignalScoutCreateResponseSerializer,
                description="The scout definition already existed; the requested config fields were applied.",
            ),
            400: OpenApiResponse(description="The scout definition, config, or destination is invalid."),
            409: OpenApiResponse(description="A scout with this name already exists with a different definition."),
        },
        summary="Create a scout",
        description=(
            "Create a `signals-scout-*` skill and its runnable config atomically. The skill always receives the "
            "report-channel tools. The optional config controls schedule, enablement, dry-run posture, and typed "
            "destinations such as Slack. Repeating the same definition is safe and applies any supplied config fields; "
            "reusing its name for a different definition returns 409."
        ),
        operation_id="signals_scout_create",
        include_serializer_context=True,
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        canonical_team = self.team.parent_team or self.team
        user = cast(User, request.user)
        self._assert_can_create_scout(user=user, canonical_team=canonical_team)
        team_id = canonical_team.id
        validated = request.validated_data
        name = validated["name"]
        description = validated["description"]
        body = validated["body"]
        files = validated.get("files", [])
        config_options = validated.get("config", {})
        serializer_context = {**self.get_serializer_context(), "project_id": self.team.project_id}

        with transaction.atomic():
            try:
                skill = create_skill(
                    canonical_team,
                    user=user,
                    name=name,
                    description=description,
                    body=body,
                    allowed_tools=sorted(REPORT_CHANNEL_TOOLS),
                    files=files,
                )
                skill_created = True
            except LLMSkillDuplicateNameConflictError:
                existing_skill = (
                    LLMSkill.objects.select_for_update()
                    .filter(team=canonical_team, name=name, is_latest=True, deleted=False)
                    .first()
                )
                if existing_skill is None:
                    raise
                if not _skill_matches_scout_definition(
                    existing_skill,
                    description=description,
                    body=body,
                    files=files,
                ):
                    raise Conflict("A scout with this name already exists with a different definition.")
                skill = existing_skill
                skill_created = False

            config, config_created = _upsert_scout_config(
                team_id=team_id,
                skill_name=name,
                tunables=config_options,
                request=request,
                serializer_context=serializer_context,
            )

        created = skill_created or config_created
        skill_info = _skill_info_for(team_id, [name])
        response = SignalScoutCreateResponseSerializer(
            {"created": created, "skill": skill, "config": config},
            context={"skill_info": skill_info},
        )
        return Response(
            response.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SignalScoutConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-scout config: list, register, tune, and delete each scout's schedule, enablement,
    and emit posture.

    `list` is read (`signal_scout:read`) and side-effect free — the MCP tool is annotated
    `readOnly`, so it must never write. `create`, `partial_update`, and `destroy` are
    user-grantable writes (`signal_scout:write`) — config changes drive spend, so enablement is
    activity-logged and `enabled_by` records who flipped it on. `create` exists so a freshly
    authored `signals-scout-*` skill can be configured immediately instead of waiting for the
    coordinator tick to auto-register a row. `destroy` removes a row outright — the cleanup path
    for an orphaned config whose skill was archived/deleted, which `partial_update` can only make
    inert (`enabled=false`), not remove.
    """

    serializer_class = SignalScoutConfigSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    queryset = SignalScoutConfig.objects.unscoped()
    lookup_field = "id"
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=SignalScoutConfigSerializer(many=True),
                description="Per-scout configs for this project, ordered by skill name.",
            ),
        },
        summary="List scout configs",
        description=(
            "List the per-(team, skill) scout configs for this project. Each row includes its schedule "
            "(rolling `run_interval_minutes`, or a project-local `run_cron_schedule` when set), `enabled`, "
            "and `emit` posture. A freshly authored scout skill appears here once its config is registered, "
            "either explicitly via create or by the coordinator's next tick."
        ),
        operation_id="signals_scout_config_list",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        # Don't surface held-back scouts here either — keeps the config read surface consistent
        # with the sync response and the seeding gate, so a withheld scout stays invisible to a
        # held-back team across the whole config API. Storage is untouched; the row reappears if
        # the team is later un-withheld.
        withheld = withheld_skills_for_team(team_id)
        configs = list(
            SignalScoutConfig.objects.unscoped()
            .filter(team_id=team_id)
            .exclude(skill_name__in=withheld)
            .order_by("skill_name")
        )
        skill_info = _skill_info_for(team_id, [c.skill_name for c in configs])
        serializer = SignalScoutConfigSerializer(configs, many=True, context={"skill_info": skill_info})
        return Response(serializer.data)

    @extend_schema(
        request=SignalScoutConfigCreateSerializer,
        responses={
            201: OpenApiResponse(response=SignalScoutConfigSerializer, description="Created config."),
            200: OpenApiResponse(
                response=SignalScoutConfigSerializer,
                description="A config already existed for this skill; the provided fields were applied to it.",
            ),
            400: OpenApiResponse(
                description=(
                    "No such skill on this project, the name lacks the `signals-scout-` prefix, "
                    "or the project is already at its enabled-scouts maximum."
                )
            ),
        },
        summary="Create a scout config",
        description=(
            "Register the config for a `signals-scout-*` skill immediately, without waiting "
            "for the coordinator to auto-register it. The same call can optionally set "
            "`run_interval_minutes`, a cron `run_cron_schedule`, `enabled`, `emit`, and output destinations. "
            "The skill must already exist on this project. Upsert: if a config already exists "
            "for the skill, the provided fields are applied to it."
        ),
        operation_id="signals_scout_config_create",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        serializer = SignalScoutConfigCreateSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "project_id": self.team.project_id},
        )
        serializer.is_valid(raise_exception=True)
        skill_name = serializer.validated_data["skill_name"]
        if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).exists():
            raise exceptions.ValidationError(
                {"skill_name": "No skill with this name exists on this project. Author the skill first."}
            )
        # Explicit registration of a scout — stamp the skill's server-owned category so it shows on
        # the skills UI's Scouts tab immediately, without waiting for the next coordinator reconcile.
        ensure_scout_category(team_id, skill_name=skill_name)
        tunables = {key: value for key, value in serializer.validated_data.items() if key != "skill_name"}
        config, created = _upsert_scout_config(
            team_id=team_id,
            skill_name=skill_name,
            tunables=tunables,
            request=request,
            serializer_context={**self.get_serializer_context(), "project_id": self.team.project_id},
        )
        skill_info = _skill_info_for(team_id, [config.skill_name])
        return Response(
            SignalScoutConfigSerializer(config, context={"skill_info": skill_info}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        request=SignalScoutConfigUpdateSerializer,
        responses={
            200: OpenApiResponse(response=SignalScoutConfigSerializer, description="Updated config."),
            400: OpenApiResponse(
                description="Invalid fields, or enabling would exceed the project's enabled-scouts maximum."
            ),
            404: OpenApiResponse(description="Config not found for this project."),
        },
        summary="Update a scout config",
        description=(
            "Tune one scout: change its schedule (rolling `run_interval_minutes`, or a cron "
            "`run_cron_schedule` that takes precedence when set), `enabled`, or `emit` (dry-run) "
            "posture, or output destinations. `skill_name` is fixed. Enabling records `enabled_by` "
            "and is activity-logged since it drives spend."
        ),
        operation_id="signals_scout_config_update",
    )
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        config_id = _parse_run_id_or_404(kwargs)
        config = SignalScoutConfig.objects.unscoped().filter(team_id=team_id, id=config_id).first()
        if config is None:
            raise exceptions.NotFound()
        serializer = SignalScoutConfigUpdateSerializer(
            config,
            data=request.data,
            partial=True,
            context={**self.get_serializer_context(), "project_id": self.team.project_id},
        )
        serializer.is_valid(raise_exception=True)
        enabling = not config.enabled and serializer.validated_data.get("enabled")
        if enabling:
            _reject_if_enabled_cap_reached(team_id, config.skill_name)
        # Fold `enabled_by` into the same save so enabling logs one activity entry, not two.
        save_kwargs = {}
        if enabling:
            save_kwargs["enabled_by"] = request.user
        instance = serializer.save(**save_kwargs)
        skill_info = _skill_info_for(team_id, [instance.skill_name])
        return Response(SignalScoutConfigSerializer(instance, context={"skill_info": skill_info}).data)

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(
                response=SignalScoutManualRunSerializer,
                description="A run was dispatched. It executes asynchronously; poll the scout's runs for the result.",
            ),
            403: OpenApiResponse(description="Signals scouts are not enabled for this project."),
            404: OpenApiResponse(description="Config not found for this project (or the scout is withheld)."),
            409: OpenApiResponse(description="A run for this scout is already in progress."),
            429: OpenApiResponse(
                description="The project is over its Signals credits quota or daily scout run budget; try again later."
            ),
        },
        summary="Run a scout now",
        description=(
            "Dispatch one on-demand run of this scout immediately, regardless of its schedule. "
            "Useful to test a scout right after authoring it, or to refresh its findings on demand. "
            "The run executes asynchronously on the worker and inherits every guard the scheduled "
            "path has: it is forbidden if scouts are not enabled for the project (403), and skipped "
            "if the project is over its Signals credits quota or daily run budget (429) or a run for "
            "this scout is already in progress (409). A manual run counts against the same daily run "
            "budget as scheduled runs, so repeated manual runs of the same scout can exhaust the "
            "project's daily allowance. A manual run does not change the scout's schedule or "
            "`last_run_at`. A disabled scout can still be run this way (to test before enabling). "
            "Returns immediately with the workflow id — poll the scout's runs for the result."
        ),
        operation_id="signals_scout_config_run",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="run",
        # Running a scout drives spend, so this is a write — same scope as enabling a config.
        required_scopes=["signal_scout:write"],
    )
    def run(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        config_id = _parse_run_id_or_404(kwargs)
        config = SignalScoutConfig.objects.unscoped().filter(team_id=team_id, id=config_id).first()
        if config is None:
            raise exceptions.NotFound()
        skill_name = config.skill_name
        # A withheld scout is invisible across the whole config API (it's excluded from list), so a
        # run request for one is a 404 here too — and the runner would refuse it anyway. Resolved
        # against the canonical team, matching `list`/`sync`.
        if skill_name in withheld_skills_for_team(team_id):
            raise exceptions.NotFound()

        # A config can outlive its skill (the list serializer tolerates a missing skill). Dispatching
        # for one would 202 + hand back a workflow id, but the runner's `load_skill_for_run` raises
        # `SkillNotFoundError` before any run row exists — so polling never shows a result. Reject up
        # front, mirroring `create`'s latest-non-deleted-skill check. The config is effectively dead
        # without its skill, so this is a 404 alongside the withheld branch above.
        if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).exists():
            raise exceptions.NotFound()

        # Honor the fleet-level controls the scheduled coordinator enforces before it would ever
        # dispatch this scout: the enrollment kill switch (`skip_team_ids` / not-enrolled → 403) and
        # the per-team daily run budget (`max_runs_per_day` → 429). Without these, a manual trigger
        # would bypass a rollout/kill-switch the operator set in the flag, and let repeated runs
        # exceed the daily cap the scheduled path respects.
        _reject_if_manual_run_suppressed(team_id)

        # Fail-fast guards so the trigger can't be gamed into churning workflows or spend. Both are
        # re-checked authoritatively downstream (quota in the run activity, single-flight in the
        # runner and at the Temporal server), but rejecting here avoids dispatching a workflow that
        # would only be skipped, and turns the common cases into clean 429/409 responses.
        api_token = Team.objects.only("api_token").get(pk=team_id).api_token
        if is_team_signals_quota_limited(api_token):
            raise exceptions.Throttled(detail="This project is over its Signals credits quota. Try again later.")
        if _scout_run_in_flight(team_id, skill_name):
            raise Conflict()

        # Deferred: keeps the heavy Signals Temporal workflow/activity graph (dragged in by the
        # `products.signals.backend.temporal` package aggregator) off the route-load path — this viewset
        # is imported by routes.py just to register routes, so a module-level import would make every
        # API/schema route load pay the full graph.
        from products.signals.backend.temporal.agentic.scout_scheduler import (
            start_manual_signals_scout_run,  # noqa: PLC0415
        )

        try:
            workflow_id = start_manual_signals_scout_run(sync_connect(), team_id=team_id, skill_name=skill_name)
        except WorkflowAlreadyStartedError:
            # A run for this scout was dispatched between the in-flight check and the start call —
            # the Temporal server's id-conflict policy single-flights it. Surface the same 409.
            raise Conflict()

        logger.info(
            "signals_scout: manual run dispatched",
            team_id=team_id,
            skill_name=skill_name,
            workflow_id=workflow_id,
            user_id=request.user.pk,
        )
        return Response(
            SignalScoutManualRunSerializer(
                {"skill_name": skill_name, "workflow_id": workflow_id, "started": True}
            ).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=None,
        responses={
            204: OpenApiResponse(description="Config deleted."),
            404: OpenApiResponse(description="Config not found for this project."),
        },
        summary="Delete a scout config",
        description=(
            "Delete one scout config by its `id`, removing the per-(team, skill) schedule/emit row "
            "outright. The point is cleaning up an orphaned config whose `signals-scout-*` skill was "
            "archived or deleted — it lingers in `list` with an empty `description`, never runs (the "
            "coordinator skips it and the skill can't load), but can't otherwise be removed over the "
            "API. Deletion is activity-logged. Note: if the skill still exists, the coordinator "
            "re-creates a default-schedule config on its next tick — to retire a live scout, archive "
            "its skill (or set `enabled=false` to make it inert) rather than deleting the config."
        ),
        operation_id="signals_scout_config_destroy",
    )
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        config_id = _parse_run_id_or_404(kwargs)
        config = SignalScoutConfig.objects.unscoped().filter(team_id=team_id, id=config_id).first()
        if config is None:
            raise exceptions.NotFound()
        # Delete on the instance (not the queryset) so ModelActivityMixin's delete hook fires —
        # config changes drive spend and are activity-logged, removals included.
        config.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                response=SignalScoutConfigSerializer(many=True),
                description="The team's full scout fleet after the sync, ordered by skill name.",
            ),
        },
        summary="Sync scout configs",
        description=(
            "Materialize the scout fleet for this project on demand (idempotent): seed the "
            "canonical `signals-scout-*` skills, create a default-schedule config for any scout "
            "lacking one, and return all scout configs. Normally the Temporal coordinator does "
            "this on its next tick; this action exists so setup flows (e.g. the wizard's "
            "self-driving program) can hand the user a tunable fleet immediately."
        ),
        operation_id="signals_scout_config_sync",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="sync",
        # Custom actions need explicit scopes — see the `current` action's note on the
        # "no scopes declared" rejection branch in `posthog/permissions.py`. Write scope:
        # the sync materializes configs, and fresh configs are enabled (they drive spend).
        required_scopes=["signal_scout:write"],
        pagination_class=None,
    )
    def sync(self, request: Request, *args, **kwargs) -> Response:
        # Scout rows persist under the canonical parent team (see `_canonical_team_id`);
        # seed and register against that team so child-environment requests don't fork
        # a second fleet.
        team = self.team if self.team.parent_team_id is None else Team.objects.get(id=self.team.parent_team_id)
        # Resolve the holdback denylist + the launch seed posture from a single flag read so they
        # can't disagree if the flag changes mid-request (the coordinator reads once and threads the
        # snapshot too). Holdback: a held-back scout can't be seeded/enabled by a manual fleet
        # materialization (the coordinator already gates the scheduled path). Posture: seed the same
        # launch shape the coordinator applies (general-only / daily etc., team_configs over
        # default_team_config) so a self-serve materialization doesn't bypass the launch cost posture
        # by enabling the full fleet.
        seed_config_layers, withheld = resolve_sync_seed_inputs(team.id)
        sync_canonical_skills(team, withheld_skill_names=withheld)
        register_missing_configs(team.id, seed_config_layers, withheld_skill_names=withheld)
        # Exclude held-back scouts from the materialized fleet response too: a scout that was
        # previously seeded and later withheld still has a row, and surfacing it here would
        # advertise an unreleased scout despite the holdback. Storage is left untouched (no
        # tombstone/disable) — the row reappears if the team is later un-withheld.
        configs = (
            SignalScoutConfig.objects.unscoped()
            .filter(team_id=team.id)
            .exclude(skill_name__in=withheld)
            .order_by("skill_name")
        )
        skill_info = _skill_info_for(team.id, [c.skill_name for c in configs])
        return Response(SignalScoutConfigSerializer(configs, many=True, context={"skill_info": skill_info}).data)
