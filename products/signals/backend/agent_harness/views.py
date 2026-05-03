"""DRF viewsets exposing the Signals agent surface over HTTP for MCP consumption.

These wrap the sync Python tools in `agent_harness/tools/` so the headless agent
(and any other agent on the team's PostHog MCP) can call the `signals-agent-*`
tools — `runs-list`, `runs-retrieve`, `runs-findings-create`, `memory-list`,
`memory-create`, `memory-delete`, and `project-profile-get` — over the standard
PostHog MCP plumbing.

Auth uses the dedicated `signal_agent:read` / `signal_agent:write` scopes. Read
is user-grantable via the personal-API-key picker; write is sandbox-internal
only (added to MCP tokens via `INTERNAL_SCOPES`). Every read filters on
`team_id` first; the agent's MCP token is already pinned to the team.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.agent_harness.serializers import (
    EmitFindingRequestSerializer,
    EmitFindingResponseSerializer,
    EvidenceEntrySerializer,
    ForgetRequestSerializer,
    ForgetResponseSerializer,
    MemoryEntrySerializer,
    ProjectProfileSerializer,
    RememberRequestSerializer,
    SearchMemoryQuerySerializer,
    SearchRecentRunsQuerySerializer,
    SignalAgentRunDetailSerializer,
    SignalAgentRunSummarySerializer,
)
from products.signals.backend.agent_harness.tools.emit import EvidenceEntry, InvalidEmitError, emit_finding_sync
from products.signals.backend.agent_harness.tools.memory import (
    HumanConfirmedMemoryError,
    InvalidMemoryError,
    forget,
    remember,
    search_memory,
)
from products.signals.backend.agent_harness.tools.profile import get_project_profile
from products.signals.backend.agent_harness.tools.runs import get_run, search_recent_runs
from products.signals.backend.models import SignalAgentRun, SignalProjectProfile


class SignalAgentRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Run history + finding emission for the headless agent."""

    serializer_class = SignalAgentRunSummarySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_agent"
    queryset = SignalAgentRun.objects.all()
    # Lookup is the run's UUID PK; DRF parses with the default `pk` URL kwarg.
    lookup_field = "id"
    lookup_value_regex = "[0-9a-f-]+"

    @validated_request(
        query_serializer=SearchRecentRunsQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=SignalAgentRunSummarySerializer(many=True),
                description="Recent run summaries newest-first.",
            ),
        },
        summary="Search recent agent runs",
        description=(
            "Return the most recent `SignalAgentRun` summaries for this project, newest first. "
            "Used by the headless agent to dedupe against work other runs already covered. "
            "ILIKE matches on `summary`; results are capped at 100."
        ),
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        text = validated.get("text") or None
        since = validated.get("since")
        limit = validated.get("limit") or 20
        rows = search_recent_runs(team_id=self.team_id, text=text, since=since, limit=limit)
        return Response(SignalAgentRunSummarySerializer([row.as_dict() for row in rows], many=True).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(response=SignalAgentRunDetailSerializer, description="Full run detail."),
            404: OpenApiResponse(description="Run not found or not visible to this project."),
        },
        summary="Get a run by ID",
        description=(
            "Return the full `SignalAgentRun` row including `summary`, `findings`, "
            "`hypotheses_considered`, `tool_call_log`, and `metadata`. Strictly team-scoped — "
            "a UUID belonging to another team returns 404."
        ),
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        run_id = kwargs.get("id")
        if run_id is None:
            raise exceptions.NotFound()
        detail = get_run(team_id=self.team_id, run_id=str(run_id))
        if detail is None:
            raise exceptions.NotFound()
        return Response(SignalAgentRunDetailSerializer(detail.as_dict()).data)

    @validated_request(
        request_serializer=EmitFindingRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=EmitFindingResponseSerializer, description="Finding emitted or short-circuited."
            ),
            400: OpenApiResponse(description="Invalid emit shape (description, weight, confidence, evidence cap)."),
            404: OpenApiResponse(description="Run not found for this project."),
        },
        summary="Emit a finding for a run",
        description=(
            "Persist a finding to `SignalAgentRun.findings` and fire `emit_signal` with "
            "`source_product = signals_agent`. Idempotent on `(run_id, finding_id)` — a "
            "second call with the same `finding_id` short-circuits without re-firing the pipeline. "
            "Honors the team's `shadow_mode` flag: when true, the finding is persisted but the external "
            "emit is a no-op."
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="findings",
        required_scopes=["signal_agent:write"],
        pagination_class=None,
    )
    def findings(self, request: Request, **kwargs) -> Response:
        run_id = kwargs.get("id")
        if run_id is None:
            raise exceptions.NotFound()
        run = SignalAgentRun.objects.select_related("agent_config").filter(team_id=self.team_id, id=run_id).first()
        if run is None:
            raise exceptions.NotFound()
        if run.status != SignalAgentRun.Status.RUNNING:
            raise exceptions.ValidationError(
                {"status": f"Findings can only be emitted on RUNNING runs (current: {run.status})."}
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

        # Default to shadow mode when there is no config (e.g. legacy run row from a deleted
        # config) — safe-by-default keeps a misconfigured run from accidentally firing emits.
        config = run.agent_config
        shadow_mode = True if config is None else bool(config.shadow_mode)

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
                shadow_mode=shadow_mode,
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


class SignalMemoryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Durable agent memories (`SignalMemory`) — read, write, and delete."""

    serializer_class = MemoryEntrySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_agent"

    @validated_request(
        query_serializer=SearchMemoryQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=MemoryEntrySerializer(many=True),
                description="Matching memory entries newest-first.",
            ),
        },
        summary="Search durable memories",
        description=(
            "Return `SignalMemory` entries for this project. ILIKE matches on `content`; tags "
            "filter via Postgres array overlap. Expired `agent_inference` entries are hidden by "
            "default."
        ),
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        validated = getattr(request, "validated_query_data", {}) or {}
        text = validated.get("text") or None
        tags = validated.get("tags") or None
        limit = validated.get("limit") or 20
        include_expired = bool(validated.get("include_expired") or False)
        rows = search_memory(
            team_id=self.team_id,
            text=text,
            tags=list(tags) if tags else None,
            limit=limit,
            include_expired=include_expired,
        )
        return Response(MemoryEntrySerializer([row.as_dict() for row in rows], many=True).data)

    @validated_request(
        request_serializer=RememberRequestSerializer,
        responses={
            200: OpenApiResponse(response=MemoryEntrySerializer, description="Memory entry written or refreshed."),
            400: OpenApiResponse(description="Invalid memory shape (empty key/content, key too long)."),
            403: OpenApiResponse(description="Tried to overwrite a `human_confirmed` entry."),
        },
        summary="Write or refresh an agent memory",
        description=(
            "Upsert an `agent_inference` memory keyed on `(team, key)`. Re-using a key updates the "
            "existing entry in place and resets its TTL. Cannot overwrite `human_confirmed` entries."
        ),
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        data = request.validated_data
        run_id = data.get("run_id") or None
        # Verify the run is on this project before accepting cross-team lineage:
        # the agent's MCP token already pins us to a team, but `run_id` is a free
        # field on the request body and a foreign-team UUID would otherwise create
        # a cross-team `created_by_run_id` reference on this team's memory row.
        # Bad UUIDs are blocked by `UUIDField` in the serializer.
        if run_id is not None and not SignalAgentRun.objects.filter(id=run_id, team_id=self.team_id).exists():
            raise exceptions.ValidationError({"run_id": "run_id does not reference a run on this project"})
        try:
            entry = remember(
                team_id=self.team_id,
                key=data["key"],
                content=data["content"],
                tags=list(data["tags"]) if data.get("tags") else None,
                ttl_days=data.get("ttl_days") or 7,
                run_id=str(run_id) if run_id is not None else None,
            )
        except InvalidMemoryError as exc:
            raise exceptions.ValidationError({"detail": str(exc)})
        except HumanConfirmedMemoryError as exc:
            raise exceptions.PermissionDenied(detail=str(exc))
        return Response(MemoryEntrySerializer(entry.as_dict()).data, status=status.HTTP_200_OK)

    @validated_request(
        request_serializer=ForgetRequestSerializer,
        responses={
            200: OpenApiResponse(response=ForgetResponseSerializer, description="Whether a row was removed."),
            403: OpenApiResponse(description="Tried to delete a `human_confirmed` entry."),
        },
        summary="Delete an agent memory by key",
        description=(
            "Delete an `agent_inference` entry by key. Returns `deleted=false` if no row matched. "
            "Cannot delete `human_confirmed` entries — those are human-managed only."
        ),
        operation_id="signals_agent_memory_delete",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="delete",
        required_scopes=["signal_agent:write"],
        pagination_class=None,
    )
    def delete(self, request: Request, **kwargs) -> Response:
        data = request.validated_data
        try:
            removed = forget(team_id=self.team_id, key=data["key"])
        except HumanConfirmedMemoryError as exc:
            raise exceptions.PermissionDenied(detail=str(exc))
        return Response(ForgetResponseSerializer({"deleted": removed}).data)


class SignalProjectProfileViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Project profile — deterministic snapshot of \"what's true about this project\".

    Singleton per team — there's no list, retrieve, or write surface. The agent calls the
    `list` action right after reading its skill to orient on this team's product mix,
    integrations, signal coverage, and existing inbox surface in one tool call instead of
    burning 4-5 discovery calls. Lazy-recomputes on cache miss / TTL expiry / source-version
    bump; the response is always either the latest cached profile or a freshly-built one.
    """

    serializer_class = ProjectProfileSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_agent"
    queryset = SignalProjectProfile.objects.all()
    pagination_class = None

    # The DRF default `list` operation_id would be `signals_agent_project_profile_list`,
    # which renders as `signals-agent-project-profile-list` in the MCP. The agent-facing
    # tool is semantically a "get the current profile" (singleton), not a "list" — override
    # the id so it matches the tool name in tools.yaml and the scout's bootstrap step.
    @extend_schema(
        operation_id="signals_agent_project_profile_get",
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
    def list(self, request: Request, *args, **kwargs) -> Response:
        profile = get_project_profile(team_id=self.team_id)
        return Response(ProjectProfileSerializer(profile.as_dict()).data)
