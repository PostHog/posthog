"""DRF viewsets exposing the Signals scout surface over HTTP for MCP consumption.

These wrap the sync Python tools in `scout_harness/tools/` so the headless scout
(and any other agent on the team's PostHog MCP) can call the `signals-scout-*`
tools — `runs-list`, `runs-retrieve`, `runs-findings-create`, `memory-list`,
`memory-create`, `memory-delete`, and `project-profile-get` — over the standard
PostHog MCP plumbing.

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

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

# PostHog's `SessionAuthentication` (not DRF's) calls `enforce_two_factor()`.
# Authenticators are tried in order and a browser-session request authenticates on
# the first matching class, so DRF's plain `SessionAuthentication` would let a
# password-only user in a 2FA-enforced org read scout runs/scratchpad without
# completing 2FA.
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission

from products.ai_observability.backend.models.skills import LLMSkill
from products.signals.backend.models import SignalProjectProfile, SignalScoutConfig, SignalScoutEmission, SignalScoutRun
from products.signals.backend.scout_harness.config_registry import enabled_scout_count
from products.signals.backend.scout_harness.limits import MAX_ENABLED_SCOUTS_PER_TEAM
from products.signals.backend.scout_harness.serializers import (
    EmitFindingRequestSerializer,
    EmitFindingResponseSerializer,
    EvidenceEntrySerializer,
    ForgetRequestSerializer,
    ForgetResponseSerializer,
    ProjectProfileQuerySerializer,
    ProjectProfileSerializer,
    RememberRequestSerializer,
    ScratchpadEntrySerializer,
    SearchMemoryQuerySerializer,
    SearchRecentRunsQuerySerializer,
    SignalScoutConfigCreateSerializer,
    SignalScoutConfigSerializer,
    SignalScoutEmissionSerializer,
    SignalScoutRunDetailSerializer,
    SignalScoutRunSummarySerializer,
)
from products.signals.backend.scout_harness.tools.emit import EvidenceEntry, InvalidEmitError, emit_finding_sync
from products.signals.backend.scout_harness.tools.profile import get_project_profile
from products.signals.backend.scout_harness.tools.runs import get_run, search_recent_runs
from products.signals.backend.scout_harness.tools.scratchpad import (
    InvalidScratchpadError,
    forget,
    remember,
    search_scratchpad,
)

# Hard cap on the per-run emissions response. Far above any realistic run (a scout emits a
# handful of findings), so it never truncates in practice — it just bounds a pathological
# retry-heavy run rather than leaving the payload unbounded.
MAX_EMISSIONS_PER_RUN = 1000

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
        from products.tasks.backend.models import TaskRun

        run = (
            SignalScoutRun.objects.select_related("scout_config", "task_run")
            .filter(team_id=_canonical_team_id(self), id=run_id)
            .first()
        )
        if run is None:
            raise exceptions.NotFound()
        if run.task_run.status != TaskRun.Status.IN_PROGRESS:
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
    # `list` returns a raw newest-first array (capped at limit=100 by the query serializer),
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
            "Return `SignalScratchpad` entries for this project. ILIKE matches on `content` and `key`. "
            "Pass `keys_only=true` to scan keys without pulling entry bodies, or `content_max_chars` to "
            "cap each `content` to a preview — both keep a wide orientation scan from returning every "
            "entry's full prose."
        ),
        operation_id="signals_scout_scratchpad_search",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        text = validated.get("text") or None
        keys_only = bool(validated.get("keys_only", False))
        content_max_chars = validated.get("content_max_chars")
        limit = validated.get("limit") or 20
        rows = search_scratchpad(
            team_id=_canonical_team_id(self),
            text=text,
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
        # Verify the run is on this project before accepting cross-team lineage:
        # the agent's MCP token already pins us to a team, but `run_id` is a free
        # field on the request body and a foreign-team UUID would otherwise create
        # a cross-team `created_by_run_id` reference on this team's memory row.
        # Bad UUIDs are blocked by `UUIDField` in the serializer.
        if (
            run_id is not None
            and not SignalScoutRun.objects.filter(id=run_id, team_id=_canonical_team_id(self)).exists()
        ):
            raise exceptions.ValidationError({"run_id": "run_id does not reference a run on this project"})
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
    # which renders as `signals-scout-project-profile-list` in the MCP. The agent-facing
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


def _skill_descriptions_for(team_id: int, skill_names: list[str]) -> dict[str, str]:
    """Map each scout `skill_name` to the latest `LLMSkill.description` on the team.

    One query for the whole config list — feeds the serializer's `description` field so
    callers get a quick steer on each scout without loading the full skill body. Skills the
    team no longer has simply drop out of the map (serializer falls back to "").
    """
    names = list(set(skill_names))
    if not names:
        return {}
    rows = LLMSkill.objects.filter(team_id=team_id, name__in=names, is_latest=True, deleted=False).values_list(
        "name", "description"
    )
    return dict(rows)


class SignalScoutConfigViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Per-scout config: list, register, and tune each scout's schedule, enablement, and
    emit posture.

    `list` is read (`signal_scout:read`) and side-effect free — the MCP tool is annotated
    `readOnly`, so it must never write. `create` and `partial_update` are user-grantable
    writes (`signal_scout:write`) — config changes drive spend, so enablement is
    activity-logged and `enabled_by` records who flipped it on. `create` exists so a freshly
    authored `signals-scout-*` skill can be configured immediately instead of waiting for the
    coordinator tick to auto-register a row.
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
            "List the per-(team, skill) scout configs for this project — schedule "
            "(`run_interval_minutes`), `enabled`, and `emit` posture per scout. A freshly "
            "authored scout skill appears here once its config is registered, either "
            "explicitly via create or by the coordinator's next tick."
        ),
        operation_id="signals_scout_config_list",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        configs = list(SignalScoutConfig.objects.unscoped().filter(team_id=team_id).order_by("skill_name"))
        descriptions = _skill_descriptions_for(team_id, [c.skill_name for c in configs])
        serializer = SignalScoutConfigSerializer(configs, many=True, context={"skill_descriptions": descriptions})
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
            "for the coordinator to auto-register it — optionally setting `run_interval_minutes`, "
            "`enabled`, and `emit` in the same call. The skill must already exist on this "
            "project. Upsert: if a config already exists for the skill, the provided fields "
            "are applied to it."
        ),
        operation_id="signals_scout_config_create",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        serializer = SignalScoutConfigCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skill_name = serializer.validated_data["skill_name"]
        if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).exists():
            raise exceptions.ValidationError(
                {"skill_name": "No skill with this name exists on this project. Author the skill first."}
            )
        tunables = {key: value for key, value in serializer.validated_data.items() if key != "skill_name"}
        # The per-team cap only gates net-new enables: a fresh row defaulting (or set) to
        # enabled, or an upsert flipping a disabled row on. Tuning an already-enabled scout
        # stays exempt via the exclude-self count.
        existing = SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).first()
        will_enable = (
            tunables.get("enabled", True)
            if existing is None
            else (not existing.enabled and tunables.get("enabled") is True)
        )
        if will_enable:
            _reject_if_enabled_cap_reached(team_id, skill_name)
        # `team_id` stays in the kwargs: `get_or_create` builds the created row from
        # kwargs/defaults only — the queryset's team filter does not propagate into `create`.
        config, created = SignalScoutConfig.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            skill_name=skill_name,
            defaults={
                **tunables,
                "created_by": request.user,
                # Configs default enabled; record who switched the scout on (it drives spend).
                "enabled_by": request.user if tunables.get("enabled", True) else None,
            },
        )
        if not created and tunables:
            # The coordinator tick (or a concurrent caller) won the race — apply the provided
            # fields to the existing row so the call still lands the requested settings.
            update = SignalScoutConfigSerializer(config, data=tunables, partial=True)
            update.is_valid(raise_exception=True)
            save_kwargs = {}
            if not config.enabled and update.validated_data.get("enabled"):
                save_kwargs["enabled_by"] = request.user
            config = update.save(**save_kwargs)
        descriptions = _skill_descriptions_for(team_id, [config.skill_name])
        return Response(
            SignalScoutConfigSerializer(config, context={"skill_descriptions": descriptions}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        request=SignalScoutConfigSerializer,
        responses={
            200: OpenApiResponse(response=SignalScoutConfigSerializer, description="Updated config."),
            400: OpenApiResponse(
                description="Invalid fields, or enabling would exceed the project's enabled-scouts maximum."
            ),
            404: OpenApiResponse(description="Config not found for this project."),
        },
        summary="Update a scout config",
        description=(
            "Tune one scout: change its schedule (`run_interval_minutes`), `enabled`, or `emit` "
            "(dry-run) posture. `skill_name` is fixed. Enabling records `enabled_by` and is "
            "activity-logged since it drives spend."
        ),
        operation_id="signals_scout_config_update",
    )
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        team_id = _canonical_team_id(self)
        config_id = _parse_run_id_or_404(kwargs)
        config = SignalScoutConfig.objects.unscoped().filter(team_id=team_id, id=config_id).first()
        if config is None:
            raise exceptions.NotFound()
        serializer = SignalScoutConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        enabling = not config.enabled and serializer.validated_data.get("enabled")
        if enabling:
            _reject_if_enabled_cap_reached(team_id, config.skill_name)
        # Fold `enabled_by` into the same save so enabling logs one activity entry, not two.
        save_kwargs = {}
        if enabling:
            save_kwargs["enabled_by"] = request.user
        instance = serializer.save(**save_kwargs)
        descriptions = _skill_descriptions_for(team_id, [instance.skill_name])
        return Response(SignalScoutConfigSerializer(instance, context={"skill_descriptions": descriptions}).data)
