from django.db.models import QuerySet

from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import ProjectSecretAPIKeyAuthentication, SessionAuthentication
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.permissions import ProjectSecretAPITokenPermission

from products.live_debugger.backend.models import LiveDebuggerBreakpoint, LiveDebuggerProgram


class LiveDebuggerBreakpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveDebuggerBreakpoint
        fields = [
            "id",
            "repository",
            "filename",
            "line_number",
            "enabled",
            "condition",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data: dict) -> LiveDebuggerBreakpoint:
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class BreakpointHitsRequestSerializer(serializers.Serializer):
    breakpoint_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Filter hits for specific breakpoints (use multiple breakpoint_ids params, e.g., ?breakpoint_ids=uuid1&breakpoint_ids=uuid2)",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=1000,
        help_text="Number of hits to return (max 1000)",
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Pagination offset")


class ActiveBreakpointsRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(
        required=False, help_text="Filter breakpoints for specific repository (e.g., 'PostHog/posthog')"
    )
    filename = serializers.CharField(required=False, help_text="Filter breakpoints for specific file")
    enabled = serializers.BooleanField(required=False, default=True, help_text="Only return enabled breakpoints")


class BreakpointHitSerializer(serializers.Serializer):
    """Schema for a single breakpoint hit event"""

    id = serializers.UUIDField(help_text="Unique identifier for the hit event")
    lineNumber = serializers.IntegerField(help_text="Line number where the breakpoint was hit")
    functionName = serializers.CharField(help_text="Name of the function where breakpoint was hit")
    timestamp = serializers.DateTimeField(help_text="When the breakpoint was hit")
    variables = serializers.DictField(help_text="Local variables at the time of the hit")
    stackTrace = serializers.ListField(help_text="Stack trace at the time of the hit")
    breakpoint_id = serializers.UUIDField(help_text="ID of the breakpoint that was hit")
    filename = serializers.CharField(help_text="Filename where the breakpoint was hit")


class BreakpointHitsResponseSerializer(serializers.Serializer):
    """Response schema for breakpoint hits endpoint"""

    results = serializers.ListField(child=BreakpointHitSerializer(), help_text="List of breakpoint hit events")
    count = serializers.IntegerField(help_text="Number of results returned")
    has_more = serializers.BooleanField(help_text="Whether there are more results available")


class ActiveBreakpointSerializer(serializers.Serializer):
    """Schema for a single active breakpoint"""

    id = serializers.UUIDField(help_text="Unique identifier for the breakpoint")
    repository = serializers.CharField(
        required=False, allow_null=True, help_text="Repository identifier (e.g., 'PostHog/posthog')"
    )
    filename = serializers.CharField(help_text="File path where the breakpoint is set")
    line_number = serializers.IntegerField(help_text="Line number of the breakpoint")
    enabled = serializers.BooleanField(help_text="Whether the breakpoint is enabled")
    condition = serializers.CharField(
        required=False, allow_null=True, help_text="Optional condition for the breakpoint"
    )


class ActiveBreakpointsResponseSerializer(serializers.Serializer):
    """Response schema for active breakpoints endpoint"""

    breakpoints = serializers.ListField(child=ActiveBreakpointSerializer(), help_text="List of active breakpoints")


class LiveDebuggerBreakpointFilterSet(FilterSet):
    class Meta:
        model = LiveDebuggerBreakpoint
        fields = ["repository", "filename"]


class LiveDebuggerBreakpointViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete breakpoints for live debugging.
    """

    scope_object = "live_debugger"
    scope_object_read_actions = ["list", "retrieve", "active_breakpoints", "breakpoint_hits"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    queryset = LiveDebuggerBreakpoint.objects.all()
    serializer_class = LiveDebuggerBreakpointSerializer
    basename = "live_debugger_breakpoints"
    filter_backends = [DjangoFilterBackend]
    filterset_class = LiveDebuggerBreakpointFilterSet

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.order_by("-created_at")

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    @extend_schema(
        summary="Get breakpoint hits",
        description=(
            "Retrieve breakpoint hit events from ClickHouse with optional filtering and pagination. "
            "Returns hit events containing stack traces, local variables, and execution context from your application's runtime. "
            "\n\nSecurity: Breakpoint IDs are filtered to only include those belonging to the current team."
        ),
        parameters=[
            OpenApiParameter(
                "breakpoint_ids",
                OpenApiTypes.STR,
                description="Filter hits for specific breakpoints (repeat parameter for multiple IDs, e.g., ?breakpoint_ids=uuid1&breakpoint_ids=uuid2)",
                required=False,
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="Number of hits to return (default: 100, max: 1000)",
                required=False,
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="Pagination offset for retrieving additional results (default: 0)",
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=BreakpointHitsResponseSerializer,
                description="List of breakpoint hits with pagination info",
            ),
            400: OpenApiResponse(description="Invalid query parameters (invalid UUID, limit out of range, etc.)"),
        },
    )
    @action(methods=["GET"], detail=False)
    def breakpoint_hits(self, request: Request, *args, **kwargs) -> Response:
        """
        Get breakpoint hit events from ClickHouse.

        Query parameters:
        - breakpoint_ids (optional): Filter hits for specific breakpoints (repeat parameter for multiple, e.g., ?breakpoint_ids=uuid1&breakpoint_ids=uuid2)
        - limit (default: 100): Number of hits to return
        - offset (default: 0): Pagination offset
        """
        param_serializer = BreakpointHitsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        breakpoint_ids = params.get("breakpoint_ids")
        limit = params["limit"]
        offset = params["offset"]

        # Filter to only breakpoints that exist and belong to this team
        if breakpoint_ids:
            breakpoint_ids = list(
                LiveDebuggerBreakpoint.objects.filter(id__in=breakpoint_ids, team=self.team).values_list(
                    "id", flat=True
                )
            )

        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(
            team=self.team, breakpoint_ids=breakpoint_ids, limit=limit, offset=offset
        )

        return Response(
            {
                "results": [hit.to_json() for hit in hits],
                "count": len(hits),
                "has_more": len(hits) == limit,
            }
        )

    @extend_schema(
        summary="Get active breakpoints (External API)",
        description=(
            "External API endpoint for client applications to fetch active breakpoints using Project API key. "
            "This endpoint allows external client applications (like Python scripts, Node.js apps, etc.) "
            "to fetch the list of active breakpoints so they can instrument their code accordingly. "
            "\n\nAuthentication: Requires a Project API Key in the Authorization header: "
            "`Authorization: Bearer phs_<your-project-api-key>`. "
            "You can find your Project API Key in PostHog at: Settings → Project → Project API Key"
        ),
        parameters=[
            OpenApiParameter(
                "repository",
                OpenApiTypes.STR,
                description="Filter breakpoints for a specific repository (e.g., 'PostHog/posthog')",
                required=False,
            ),
            OpenApiParameter(
                "filename",
                OpenApiTypes.STR,
                description="Filter breakpoints for a specific file",
                required=False,
            ),
            OpenApiParameter(
                "enabled",
                OpenApiTypes.BOOL,
                description="Only return enabled breakpoints",
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=ActiveBreakpointsResponseSerializer,
                description="List of breakpoints for client consumption",
            ),
            400: OpenApiResponse(description="Invalid query parameters"),
            401: OpenApiResponse(description="Invalid or missing Project API key"),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        authentication_classes=[
            ProjectSecretAPIKeyAuthentication,
            SessionAuthentication,
        ],
        required_scopes=["live_debugger:read"],
        permission_classes=[ProjectSecretAPITokenPermission],
        url_path="active",
    )
    def active_breakpoints(self, request: Request, *args, **kwargs) -> Response:
        """
        External API endpoint for client applications to fetch active breakpoints using Project API key.

        This endpoint allows external client applications (like Python scripts, Node.js apps, etc.)
        to fetch the list of active breakpoints so they can instrument their code accordingly.

        Authentication: Requires a Project API Key in the Authorization header:
        Authorization: Bearer phs_<your-project-api-key>

        You can find your Project API Key in PostHog at: Settings → Project → Project API Key

        Query parameters:
        - repository (optional): Filter breakpoints for specific repository (e.g., 'PostHog/posthog')
        - filename (optional): Filter breakpoints for specific file
        - enabled (default: true): Only return enabled breakpoints

        Response format:
        {
            "results": [
                {
                    "id": "uuid",
                    "repository": "PostHog/posthog",
                    "filename": "capture_event.py",
                    "line_number": 123,
                    "enabled": true,
                    "condition": "user_id == '12345'" // optional
                }
            ],
            "count": 1,
            "has_more": false
        }
        """
        param_serializer = ActiveBreakpointsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        enabled_filter = params["enabled"]
        repository = params.get("repository")
        filename = params.get("filename")

        queryset = self.get_queryset()

        if enabled_filter:
            queryset = queryset.filter(enabled=True)

        if repository:
            queryset = queryset.filter(repository=repository)

        if filename:
            queryset = queryset.filter(filename=filename)

        breakpoints = queryset.values("id", "repository", "filename", "line_number", "enabled", "condition")
        breakpoints_list = list(breakpoints)

        return Response(
            {
                "results": breakpoints_list,
                "count": len(breakpoints_list),
                "has_more": False,
            }
        )


class LiveDebuggerProgramSerializer(serializers.ModelSerializer):
    """Full representation of a live debugger program, including its code."""

    class Meta:
        model = LiveDebuggerProgram
        fields = ["id", "code", "description", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
        extra_kwargs = {
            "code": {
                "help_text": (
                    "The hogtrace program source code to install. "
                    "This is executed by the client-side runtime to instrument production code with probes."
                ),
            },
            "description": {
                "help_text": "Human-readable description of what this program does and why it was installed.",
            },
            "status": {
                "help_text": (
                    "Lifecycle status of the program. 'installed' programs are active and will emit events "
                    "when their probes are hit. 'uninstalled' programs are inactive and retained for history."
                ),
            },
            "created_at": {"help_text": "Time the program was installed."},
            "updated_at": {"help_text": "Time the program record was last modified (e.g. on uninstall)."},
        }

    def create(self, validated_data: dict) -> LiveDebuggerProgram:
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class LiveDebuggerProgramListItemSerializer(serializers.ModelSerializer):
    """Compact representation of a program for list views — omits the program code."""

    class Meta:
        model = LiveDebuggerProgram
        fields = ["id", "description", "status", "created_at", "updated_at"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for the program."},
            "description": {"help_text": "Human-readable description of the program."},
            "status": {"help_text": "Lifecycle status: 'installed' or 'uninstalled'."},
            "created_at": {"help_text": "Time the program was installed."},
            "updated_at": {"help_text": "Time the program record was last modified."},
        }


class ProgramEventSerializer(serializers.Serializer):
    """A single event emitted by a probe in a live debugger program."""

    id = serializers.UUIDField(help_text="Unique identifier for this event.")
    timestamp = serializers.DateTimeField(help_text="Wall-clock time at which the probe fired.")
    program_id = serializers.UUIDField(help_text="ID of the program that emitted this event.")
    probe_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Identifier of the specific probe within the program that fired (may be null).",
    )
    line_number = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="Source line where the probe fired (may be null if not applicable).",
    )
    filename = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Source file where the probe fired (may be null if not applicable).",
    )
    function_name = serializers.CharField(help_text="Function containing the probe at the time it fired.")
    locals = serializers.DictField(
        help_text="Snapshot of local variables captured at the probe site, as a key/value map.",
    )
    stack_trace = serializers.ListField(
        child=serializers.DictField(),
        help_text="Stack trace at the time the probe fired; each frame is a dict with at least 'function' and source info.",
    )


class ProgramEventsResponseSerializer(serializers.Serializer):
    """Paginated list of probe events for a single program."""

    results = serializers.ListField(
        child=ProgramEventSerializer(),
        help_text="List of probe events, most recent first.",
    )
    count = serializers.IntegerField(help_text="Number of events returned in this page.")
    has_more = serializers.BooleanField(help_text="Whether additional events are available beyond this page.")


class ProgramEventsRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=1000,
        help_text="Maximum number of events to return (default 100, max 1000).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Pagination offset; events are ordered by timestamp descending.",
    )


class LiveDebuggerProgramViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Install, list, inspect, and uninstall live debugger programs (hogtrace programs).

    Programs are soft-uninstalled (status transitions to 'uninstalled') rather than deleted,
    so previously emitted events remain queryable.
    """

    scope_object = "live_debugger"
    scope_object_read_actions = ["list", "retrieve", "events"]
    scope_object_write_actions = ["create", "uninstall"]
    queryset = LiveDebuggerProgram.objects.all()
    serializer_class = LiveDebuggerProgramSerializer
    basename = "live_debugger_programs"
    # Programs are immutable post-install except for status, which transitions via the
    # `uninstall` action — disable update/destroy so the only mutation paths are explicit.
    http_method_names = ["get", "post", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.order_by("-created_at")

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "list":
            return LiveDebuggerProgramListItemSerializer
        return LiveDebuggerProgramSerializer

    @extend_schema(
        summary="Install a live debugger program",
        description=(
            "Install a hogtrace program. The program will be picked up by the client-side runtime "
            "and its probes will start emitting events on hit. Returns the full program record "
            "including its newly assigned id."
        ),
        request=LiveDebuggerProgramSerializer,
        responses={
            201: OpenApiResponse(response=LiveDebuggerProgramSerializer, description="Program installed."),
            400: OpenApiResponse(description="Invalid request body."),
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="List live debugger programs",
        description="List programs for the current team, most recently installed first. Omits program code.",
        responses={200: OpenApiResponse(response=LiveDebuggerProgramListItemSerializer(many=True))},
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Show a live debugger program",
        description="Retrieve a single program by id, including its full hogtrace program source code.",
        responses={
            200: OpenApiResponse(response=LiveDebuggerProgramSerializer),
            404: OpenApiResponse(description="Program not found."),
        },
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Uninstall a live debugger program",
        description=(
            "Soft-uninstall a program by transitioning its status to 'uninstalled'. "
            "The program record and any events it previously emitted remain queryable. "
            "Returns the updated program."
        ),
        request=None,
        responses={
            200: OpenApiResponse(response=LiveDebuggerProgramSerializer, description="Program uninstalled."),
            404: OpenApiResponse(description="Program not found."),
        },
    )
    @action(methods=["POST"], detail=True)
    def uninstall(self, request: Request, *args, **kwargs) -> Response:
        program = self.get_object()
        if program.status != LiveDebuggerProgram.Status.UNINSTALLED:
            program.status = LiveDebuggerProgram.Status.UNINSTALLED
            program.save(update_fields=["status", "updated_at"])
        return Response(LiveDebuggerProgramSerializer(program).data)

    @extend_schema(
        summary="Get events emitted by a program",
        description=(
            "Retrieve probe-hit events emitted by this program from ClickHouse. "
            "Events are filtered by the program id stored in the `$program_id` property "
            "and returned most recent first."
        ),
        parameters=[
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="Maximum number of events to return (default 100, max 1000).",
                required=False,
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="Pagination offset.",
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(response=ProgramEventsResponseSerializer),
            400: OpenApiResponse(description="Invalid query parameters."),
            404: OpenApiResponse(description="Program not found."),
        },
    )
    @action(methods=["GET"], detail=True)
    def events(self, request: Request, *args, **kwargs) -> Response:
        program = self.get_object()
        param_serializer = ProgramEventsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        tag_queries(product=Product.LIVE_DEBUGGER, feature=Feature.QUERY)
        events = LiveDebuggerProgram.get_program_events(
            team=self.team,
            program_id=str(program.id),
            limit=params["limit"],
            offset=params["offset"],
        )
        return Response(
            {
                "results": [event.to_json() for event in events],
                "count": len(events),
                "has_more": len(events) == params["limit"],
            }
        )
