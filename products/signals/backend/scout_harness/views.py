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

from drf_spectacular.utils import OpenApiResponse, extend_schema
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

from products.signals.backend.models import SignalProjectProfile, SignalScoutRun
from products.signals.backend.scout_harness.serializers import (
    EmitFindingRequestSerializer,
    EmitFindingResponseSerializer,
    EvidenceEntrySerializer,
    ForgetRequestSerializer,
    ForgetResponseSerializer,
    ProjectProfileSerializer,
    RememberRequestSerializer,
    ScratchpadEntrySerializer,
    SearchMemoryQuerySerializer,
    SearchRecentRunsQuerySerializer,
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


def _parse_run_id_or_404(kwargs: dict) -> uuid.UUID:
    """Parse the `id` URL kwarg as a UUID; raise 404 on missing or malformed.

    DRF routes any string the default `lookup_value_regex` accepts (anything
    except `/` and `.`) into the action, so the action is responsible for
    rejecting non-UUID inputs cleanly rather than letting them surface as
    500s from `UUIDField.to_python()` on the underlying ORM query.
    """
    raw = kwargs.get("id")
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
    # Lookup is the run's UUID PK; DRF parses with the default `pk` URL kwarg.
    # No `lookup_value_regex` — use DRF's default and let the view actions parse
    # the raw segment with `uuid.UUID()` (via `_parse_run_id_or_404`) so malformed
    # IDs return a clean 404 rather than hitting `.filter(id=…)` with a non-UUID
    # and blowing up on Django's UUIDField conversion.
    lookup_field = "id"
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
            "100-row cap. Results capped at 100."
        ),
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        date_from = validated.get("date_from")
        date_to = validated.get("date_to")
        text = validated.get("text") or None
        limit = validated.get("limit") or 20
        rows = search_recent_runs(
            team_id=_canonical_team_id(self),
            date_from=date_from,
            date_to=date_to,
            text=text,
            limit=limit,
        )
        return Response(SignalScoutRunSummarySerializer([row.as_dict() for row in rows], many=True).data)

    @extend_schema(
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

    @validated_request(
        request_serializer=EmitFindingRequestSerializer,
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
                weight=data["weight"],
                confidence=data["confidence"],
                evidence=evidence,
                hypothesis=data.get("hypothesis") or None,
                severity=data.get("severity") or None,
                dedupe_keys=data.get("dedupe_keys") or None,
                time_range=time_range_tuple,
                mcp_trace_id=data.get("mcp_trace_id") or None,
                finding_id=data.get("finding_id") or None,
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
        description=("Return `SignalScratchpad` entries for this project. ILIKE matches on `content` and `key`."),
        operation_id="signals_scout_scratchpad_search",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        text = validated.get("text") or None
        limit = validated.get("limit") or 20
        rows = search_scratchpad(team_id=_canonical_team_id(self), text=text, limit=limit)
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
    queryset = SignalProjectProfile.objects.all()
    pagination_class = None

    # The DRF default `list` operation_id would be `signals_scout_project_profile_list`,
    # which renders as `signals-scout-project-profile-list` in the MCP. The agent-facing
    # tool is semantically a "get the current profile" (singleton), not a "list" — override
    # the id so it matches the tool name in tools.yaml and the scout's bootstrap step.
    @extend_schema(
        operation_id="signals_scout_project_profile_get",
        responses={
            200: OpenApiResponse(
                response=ProjectProfileSerializer,
                description="The team's current project profile (cached or freshly computed).",
            ),
        },
        summary="Get the current project profile",
        description=(
            "Return the team's deterministic project profile. The response always reflects "
            "either the newest non-expired cached row or a freshly-built one (lazy compute "
            "on cache miss). Read this at the start of a run to orient on the team's product "
            "mix, integrations, warehouse sources, signal coverage, and existing inbox surface."
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
        # `signal_agent:read` is the public, user-grantable read scope already
        # used by `runs-list`, `runs-retrieve`, and `memory-list` on this surface.
        required_scopes=["signal_agent:read"],
    )
    def current(self, request: Request, *args, **kwargs) -> Response:
        profile = get_project_profile(team_id=self.team_id)
        return Response(ProjectProfileSerializer(profile.as_dict()).data)
