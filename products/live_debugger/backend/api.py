from django.db.models import QuerySet

from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import ProjectSecretAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import ProjectSecretAPITokenPermission

from products.live_debugger.backend import github_cache, github_client
from products.live_debugger.backend.models import LiveDebuggerBreakpoint


class LiveDebuggerBreakpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiveDebuggerBreakpoint
        fields = ["id", "repository", "filename", "line_number", "enabled", "condition", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
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

    def safely_get_queryset(self, queryset) -> QuerySet:
        return queryset.order_by("-created_at")

    def get_serializer_context(self):
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
    def breakpoint_hits(self, request, *args, **kwargs) -> Response:
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
        authentication_classes=[ProjectSecretAPIKeyAuthentication, SessionAuthentication],
        required_scopes=["live_debugger:read"],
        permission_classes=[ProjectSecretAPITokenPermission],
        url_path="active",
    )
    def active_breakpoints(self, request, *args, **kwargs) -> Response:
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


class RepositorySerializer(serializers.Serializer):
    """Schema for a repository item"""

    name = serializers.CharField(help_text="Repository name (e.g., 'posthog')")
    full_name = serializers.CharField(help_text="Full repository path (e.g., 'PostHog/posthog')")


class RepositoriesResponseSerializer(serializers.Serializer):
    """Response schema for repositories endpoint"""

    repositories = serializers.ListField(child=RepositorySerializer(), help_text="List of accessible repositories")


class TreeItemSerializer(serializers.Serializer):
    """Schema for a tree item (file or directory)"""

    path = serializers.CharField(help_text="Path within the repository")
    mode = serializers.CharField(help_text="File mode")
    type = serializers.CharField(help_text="Type: 'blob' (file) or 'tree' (directory)")
    sha = serializers.CharField(help_text="Git SHA hash")
    size = serializers.IntegerField(required=False, help_text="File size in bytes (for blobs)")
    url = serializers.CharField(help_text="GitHub API URL")


class TreeResponseSerializer(serializers.Serializer):
    """Response schema for tree endpoint"""

    sha = serializers.CharField(help_text="Commit SHA")
    url = serializers.CharField(help_text="GitHub API URL")
    tree = serializers.ListField(child=TreeItemSerializer(), help_text="Tree items (files and directories)")
    truncated = serializers.BooleanField(help_text="Whether the tree was truncated")


class FileContentResponseSerializer(serializers.Serializer):
    """Response schema for file content endpoint"""

    name = serializers.CharField(help_text="File name")
    path = serializers.CharField(help_text="Full path within repository")
    sha = serializers.CharField(help_text="Git SHA hash")
    size = serializers.IntegerField(help_text="File size in bytes")
    url = serializers.CharField(help_text="GitHub API URL")
    html_url = serializers.CharField(help_text="GitHub web URL")
    git_url = serializers.CharField(help_text="Git URL")
    download_url = serializers.CharField(help_text="Direct download URL")
    type = serializers.CharField(help_text="Content type")
    content = serializers.CharField(help_text="File content (decoded)")
    encoding = serializers.CharField(help_text="Content encoding")


class LiveDebuggerRepoBrowserViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Browse GitHub repositories for live debugger using team's GitHub integration.
    """

    scope_object = "live_debugger"

    @extend_schema(
        summary="List accessible repositories",
        description=(
            "List all repositories accessible to the team's GitHub integration. "
            "Requires a GitHub integration to be configured for the team."
        ),
        responses={
            200: OpenApiResponse(
                response=RepositoriesResponseSerializer, description="List of accessible repositories"
            ),
            404: OpenApiResponse(description="No GitHub integration found for team"),
            500: OpenApiResponse(description="Failed to fetch repositories from GitHub"),
        },
    )
    @action(methods=["GET"], detail=False)
    def repositories(self, request, *args, **kwargs) -> Response:
        """
        List all repositories accessible to the team's GitHub integration.
        """
        try:
            repositories = github_client.list_repositories(self.team)
            return Response({"repositories": repositories})
        except github_client.GitHubIntegrationNotFoundError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except github_client.GitHubClientError as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="Get repository tree structure",
        description=(
            "Get the complete file tree for a repository at a specific branch. "
            "Results are cached for 1 hour based on commit SHA. "
            "Only returns Python files (.py) and directories."
        ),
        parameters=[
            OpenApiParameter("repo", OpenApiTypes.STR, description="Repository name (e.g., 'posthog')", required=True),
            OpenApiParameter(
                "branch",
                OpenApiTypes.STR,
                description="Branch name (e.g., 'master')",
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(response=TreeResponseSerializer, description="Repository tree structure"),
            400: OpenApiResponse(description="Missing or invalid parameters"),
            404: OpenApiResponse(description="No GitHub integration found or branch not found"),
            500: OpenApiResponse(description="Failed to fetch tree from GitHub"),
        },
    )
    @action(methods=["GET"], detail=False)
    def tree(self, request, *args, **kwargs) -> Response:
        """
        Get the repository tree structure for a specific branch.

        Query parameters:
        - repo (required): Repository name (e.g., 'posthog')
        - branch (optional): Branch name (default: 'master')
        """
        repo = request.query_params.get("repo")
        branch = request.query_params.get("branch", "master")

        if not repo:
            return Response({"error": "Missing required parameter: repo"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get current SHA for the branch
            sha = github_client.get_branch_sha(self.team, repo, branch)

            # Check cache first
            cached_tree = github_cache.get_cached_tree(self.team.pk, repo, branch, sha)
            if cached_tree:
                return Response(cached_tree)

            # Fetch from GitHub and cache
            tree_data = github_client.get_repository_tree(self.team, repo, sha)
            github_cache.cache_tree(self.team.pk, repo, branch, sha, tree_data)

            return Response(tree_data)

        except github_client.GitHubIntegrationNotFoundError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except github_client.GitHubClientError as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        summary="Get file content",
        description=(
            "Get the content of a specific file from a repository. "
            "Results are cached for 24 hours. "
            "Content is automatically decoded from base64."
        ),
        parameters=[
            OpenApiParameter("repo", OpenApiTypes.STR, description="Repository name (e.g., 'posthog')", required=True),
            OpenApiParameter(
                "branch",
                OpenApiTypes.STR,
                description="Branch name (e.g., 'master')",
                required=False,
            ),
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                description="File path within repository (e.g., 'posthog/api/test.py')",
                required=True,
            ),
        ],
        responses={
            200: OpenApiResponse(response=FileContentResponseSerializer, description="File content"),
            400: OpenApiResponse(description="Missing or invalid parameters"),
            404: OpenApiResponse(description="No GitHub integration found or file not found"),
            500: OpenApiResponse(description="Failed to fetch file from GitHub"),
        },
    )
    @action(methods=["GET"], detail=False)
    def file(self, request, *args, **kwargs) -> Response:
        """
        Get the content of a specific file from a repository.

        Query parameters:
        - repo (required): Repository name (e.g., 'posthog')
        - branch (optional): Branch name (default: 'master')
        - path (required): File path within repository
        """
        repo = request.query_params.get("repo")
        branch = request.query_params.get("branch", "master")
        path = request.query_params.get("path")

        if not repo:
            return Response({"error": "Missing required parameter: repo"}, status=status.HTTP_400_BAD_REQUEST)

        if not path:
            return Response({"error": "Missing required parameter: path"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Get current SHA for the branch
            sha = github_client.get_branch_sha(self.team, repo, branch)

            # Check cache first
            cached_file = github_cache.get_cached_file(self.team.pk, repo, branch, sha, path)
            if cached_file:
                return Response(cached_file)

            # Fetch from GitHub and cache
            file_data = github_client.get_file_content(self.team, repo, path)
            github_cache.cache_file(self.team.pk, repo, branch, sha, path, file_data)

            return Response(file_data)

        except github_client.GitHubIntegrationNotFoundError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except github_client.GitHubClientError as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
