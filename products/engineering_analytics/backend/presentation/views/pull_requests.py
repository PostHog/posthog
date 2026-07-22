"""PR-scoped reads: backlog cards, lists, lifecycle, runs, logs, and cost."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.pull_requests import (
    BranchPRMatchSerializer,
    CICardSummarySerializer,
    CIFailureLogsSerializer,
    PRCostSummarySerializer,
    PRLifecycleSerializer,
    PullRequestListSerializer,
    WorkflowCostSerializer,
)
from products.engineering_analytics.backend.presentation.serializers.workflows import WorkflowRunDetailSerializer
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_FROM,
    _DATE_TO,
    _REPO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
    _optional_datetime_param,
    _require_int_param,
)


class PullRequestActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = [
        "ci_cards",
        "pull_requests",
        "pr_lifecycle",
        "resolve_branch",
        "pr_runs",
        "ci_failure_logs",
        "pr_cost",
        "author_workflow_costs",
    ]

    @extend_schema(
        operation_id="engineering_analytics_ci_cards",
        parameters=[_SOURCE_ID, _REPO],
        responses={
            200: CICardSummarySerializer,
            400: OpenApiResponse(description="Invalid source_id."),
        },
        description=(
            "Headline counts for the open-PR backlog: open PRs, distinct repos, stuck PRs (open, non-draft, "
            "non-bot, older than 7 days), and PRs with failing CI. The failing-CI count rests on the head-SHA "
            "join and can lag until late CI completions settle."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def ci_cards(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_ci_cards(
                team=self.team,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(CICardSummarySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_pull_requests",
        parameters=[
            _DATE_FROM,
            OpenApiParameter(
                name="author",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional GitHub login to scope the list to one author's pull requests.",
            ),
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: PullRequestListSerializer,
            400: OpenApiResponse(description="Invalid date_from or source_id."),
        },
        description=(
            "Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with "
            "its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards "
            "counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; "
            "CI counts can lag until late completions settle."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pull_requests(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_pull_requests(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                author=request.query_params.get("author") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from or source_id")
        return Response(PullRequestListSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_pr_lifecycle",
        parameters=[
            OpenApiParameter(
                name="pr_number",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Pull request number to inspect.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the pull request belongs to.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: PRLifecycleSerializer,
            400: OpenApiResponse(description="Missing pr_number/repo, or invalid repo or source_id."),
            404: OpenApiResponse(description="No pull request with that number in the warehouse."),
        },
        description=(
            "The timeline of a single pull request: header plus ordered events (opened, CI started/finished, "
            "merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a "
            "partial view: review and comment events are not yet available."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pr_lifecycle(self, request: Request, **kwargs) -> Response:
        repo = request.query_params.get("repo")
        try:
            pr_number = _require_int_param(request, "pr_number")
            if not repo:
                raise ValueError("repo is required")
            result = api.get_pr_lifecycle(
                team=self.team,
                pr_number=pr_number,
                repo=repo,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        if result is None:
            return Response({"detail": "Pull request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(PRLifecycleSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_resolve_branch",
        parameters=[
            OpenApiParameter(
                name="branch",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Git branch (the PR's head ref) to resolve. Open PRs are returned first, then most "
                "recently updated.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional 'owner/name' repository to narrow matching to a single repo.",
            ),
            OpenApiParameter(
                name="timestamp",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional ISO8601 timestamp, e.g. the trace's capture time. When a branch name has been "
                "reused across PRs over time, the PR whose lifetime window contains this moment is ranked first so the "
                "result matches the PR that was active when the trace was captured. A preference only, not a filter; "
                "omit to rank purely by open state then recency.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: BranchPRMatchSerializer(many=True),
            400: OpenApiResponse(description="Branch missing/empty, or invalid repo/timestamp/source_id."),
        },
        description=(
            "Resolve a git branch to the pull request(s) it belongs to — the cross-product link seam so another "
            "product (the LLM analytics UI) can turn a git branch into a PR detail link. Matches the PR's head ref, "
            "open PRs first then most recently updated. Pass `timestamp` (the trace's capture time) to prefer the PR "
            "that was active at that moment when a branch name has been reused across PRs. `branch` is required. "
            "Returns a possibly-empty, possibly-multi list — an empty list is a valid 200 (the caller renders a plain "
            "chip)."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def resolve_branch(self, request: Request, **kwargs) -> Response:
        try:
            matches = api.resolve_branch(
                team=self.team,
                branch=request.query_params.get("branch") or None,
                repo=request.query_params.get("repo") or None,
                timestamp=_optional_datetime_param(request, "timestamp"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Provide a branch")
        return Response(BranchPRMatchSerializer(instance=matches, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_pr_runs",
        parameters=[
            OpenApiParameter(
                name="pr_number",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Pull request number whose runs to list.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the pull request belongs to.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowRunDetailSerializer(many=True),
            400: OpenApiResponse(description="Missing pr_number/repo, or invalid repo or source_id."),
        },
        description=(
            "Every workflow run attributed to a pull request, across all its commits (grouped by head SHA "
            "client-side), newest first. Run-level only."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pr_runs(self, request: Request, **kwargs) -> Response:
        repo = request.query_params.get("repo")
        try:
            pr_number = _require_int_param(request, "pr_number")
            if not repo:
                raise ValueError("repo is required")
            runs = api.list_pr_runs(
                team=self.team,
                pr_number=pr_number,
                repo=repo,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        return Response(WorkflowRunDetailSerializer(instance=runs, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_ci_failure_logs",
        parameters=[
            OpenApiParameter(
                name="pr_number",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Pull request number whose CI failure logs to fetch.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the pull request belongs to.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: CIFailureLogsSerializer,
            400: OpenApiResponse(description="Missing pr_number/repo, or invalid repo or source_id."),
        },
        description=(
            "The thinned CI failure logs for a pull request, grouped by failed job. Resolves the PR to "
            "its workflow runs via the pull_requests association (all of the PR's pushes, not just the "
            "latest commit), then reads the Logs product joined on run_id. Returns failed jobs only (the "
            "worker fetches logs for failures); logs_available is false when CI hasn't failed, the logs "
            "aged out of the short Logs retention, or a fork PR has no run association. Each line carries "
            "its original 1-based line number in the full pre-thinning log; lines are the failure region "
            "(errors plus surrounding context, with omission markers), capped per job and overall."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def ci_failure_logs(self, request: Request, **kwargs) -> Response:
        repo = request.query_params.get("repo")
        try:
            pr_number = _require_int_param(request, "pr_number")
            if not repo:
                raise ValueError("repo is required")
            result = api.get_ci_failure_logs(
                team=self.team,
                pr_number=pr_number,
                repo=repo,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        return Response(CIFailureLogsSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_pr_cost",
        parameters=[
            OpenApiParameter(
                name="pr_number",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Pull request number to estimate cost for.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the pull request belongs to.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: PRCostSummarySerializer,
            400: OpenApiResponse(description="Missing pr_number/repo, or invalid repo or source_id."),
        },
        description=(
            "Estimated CI cost for a pull request, summed over the jobs of all its workflow runs. "
            "Billable self-hosted Linux runners only — provider-hosted (free GitHub-hosted) and non-Linux "
            "jobs are excluded. Every figure is zero/null with `jobs_available` false when the job-level "
            "source isn't synced yet. `llm_spend` carries the agent LLM token spend attributed to the PR "
            "by git branch, or null when no `$ai_generation` event matched."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def pr_cost(self, request: Request, **kwargs) -> Response:
        repo = request.query_params.get("repo")
        try:
            pr_number = _require_int_param(request, "pr_number")
            if not repo:
                raise ValueError("repo is required")
            result = api.get_pr_cost(
                team=self.team,
                pr_number=pr_number,
                repo=repo,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        return Response(PRCostSummarySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_author_workflow_costs",
        parameters=[
            OpenApiParameter(
                name="author",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="GitHub handle whose CI spend to break down.",
            ),
            _DATE_FROM,
            _DATE_TO,
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: WorkflowCostSerializer(many=True),
            400: OpenApiResponse(description="Missing author, or invalid date or source_id."),
        },
        description=(
            "One author's estimated CI cost split by workflow over a window (date_from default -30d), "
            "highest spend first. Runs are attributed to the author through their pull requests (attribution "
            "is by PR number). Returns an empty list when the job-level source isn't synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def author_workflow_costs(self, request: Request, **kwargs) -> Response:
        author = request.query_params.get("author")
        if not author:
            return Response({"detail": "author is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            costs = api.list_author_workflow_costs(
                team=self.team,
                author=author,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, date, or source_id")
        return Response(WorkflowCostSerializer(instance=costs, many=True).data)
