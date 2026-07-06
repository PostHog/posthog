"""DRF views for engineering_analytics.

Named, typed read endpoints over the curated PR/CI query builders. Each action
runs curated HogQL privately (no global view registration) and returns a typed
contract. These same endpoints back both the MCP tools and the UI:

- ``ci_cards`` — backlog headline counts.
- ``pull_requests`` — PR list with head-SHA CI rollup.
- ``workflow_health`` — per-workflow CI health over a window.
- ``pr_lifecycle`` — a single PR's header plus its ordered CI timeline.
- ``quarantine`` — the repo's checked-in flaky-test quarantine file.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import (
    GitHubSourceNotConnectedError,
    QuarantineRequest,
    QuarantineWriteError,
)
from products.engineering_analytics.backend.presentation.serializers import (
    CICardSummarySerializer,
    CIFailureLogsSerializer,
    GitHubSourceSerializer,
    MasterFailureGroupSerializer,
    PRCostSummarySerializer,
    PRLifecycleSerializer,
    PullRequestListSerializer,
    QuarantineFileSerializer,
    QuarantineRequestResultSerializer,
    QuarantineRequestSerializer,
    RepoOverviewSerializer,
    RunFailureLogsSerializer,
    WorkflowCostSerializer,
    WorkflowHealthItemSerializer,
    WorkflowJobAggregateSerializer,
    WorkflowJobSerializer,
    WorkflowRunActivitySerializer,
    WorkflowRunDetailSerializer,
    WorkflowRunnerCostSerializer,
)

ENGINEERING_ANALYTICS_TAG = "engineering_analytics"

_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.",
)

# Workflow health defaults to a tighter window than the PR list (a CI-health "now" view), so it
# advertises its own default rather than reusing _DATE_FROM's -30d.
_WORKFLOW_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window start: relative ('-24h', '-7d') or ISO8601. Defaults to -24h.",
)

_DATE_TO = OpenApiParameter(
    name="date_to",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window end: relative or ISO8601. Defaults to now.",
)

_BRANCH = OpenApiParameter(
    name="branch",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Optional exact git branch (head_branch) to scope results to, e.g. 'main'. "
    "Omit or leave blank to aggregate across all branches.",
)

_SOURCE_ID = OpenApiParameter(
    name="source_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub "
    "source when the team has more than one.",
)


def _bad_request(exc: ValueError, *, fallback: str) -> Response:
    return Response({"detail": str(exc) or fallback}, status=status.HTTP_400_BAD_REQUEST)


def _require_int_param(request: Request, name: str) -> int:
    """Required integer query param; raises ValueError (handled by `_bad_request`) when missing or non-int."""
    raw = request.query_params.get(name)
    if raw is None:
        raise ValueError(f"{name} is required")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _optional_int_param(request: Request, name: str) -> int | None:
    """Optional integer query param; None when absent/blank, ValueError when present but non-int."""
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    scope_object = "engineering_analytics"
    scope_object_read_actions = [
        "sources",
        "ci_cards",
        "pull_requests",
        "workflow_health",
        "pr_lifecycle",
        "quarantine",
        "pr_runs",
        "ci_failure_logs",
        "pr_cost",
        "workflow_run",
        "workflow_runs",
        "workflow_run_activity",
        "workflow_runner_costs",
        "author_workflow_costs",
        "workflow_jobs",
        "repo_overview",
        "master_failures",
        "run_failure_logs",
        "job_aggregates",
    ]
    scope_object_write_actions: list[str] = ["quarantine_request"]

    def handle_exception(self, exc: Exception) -> Response:
        # No GitHub warehouse source connected — every read action degrades the same way.
        if isinstance(exc, GitHubSourceNotConnectedError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # A quarantine write that can't proceed (App not installed, malformed file, GitHub
        # failure) — the message is user-safe and explains what to fix.
        if isinstance(exc, QuarantineWriteError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)

    @extend_schema(
        operation_id="engineering_analytics_sources",
        responses={200: GitHubSourceSerializer(many=True)},
        description=(
            "The team's connected GitHub data warehouse sources, oldest first. Populate a source picker "
            "from this and pass a chosen `id` back as `source_id` to the other endpoints. A team can connect "
            "GitHub more than once (e.g. one source per repository); this lists them all, including any whose "
            "tables aren't fully synced yet."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def sources(self, request: Request, **kwargs) -> Response:
        result = api.list_github_sources(team=self.team, user_access_control=self.user_access_control)
        return Response(GitHubSourceSerializer(instance=result, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_ci_cards",
        parameters=[_SOURCE_ID],
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
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from or source_id")
        return Response(PullRequestListSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_health",
        parameters=[_WORKFLOW_DATE_FROM, _DATE_TO, _BRANCH, _SOURCE_ID],
        responses={
            200: WorkflowHealthItemSerializer(many=True),
            400: OpenApiResponse(
                description="Invalid date_from, date_to, or source_id, or a window longer than 366 days."
            ),
        },
        description=(
            "Per-workflow CI health over a window (default last 24 hours, maximum 366 days): run count, success "
            "rate, p50/p95 duration over completed runs, last failure time, latest-run status, and a zero-filled "
            "run history bucketed by hour/day/week to fit the window. Optionally scope to a single git branch via "
            "`branch`. Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two "
            "windows to get a trend."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_health(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_workflow_health(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(WorkflowHealthItemSerializer(instance=result, many=True).data)

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
            "source isn't synced yet."
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
        operation_id="engineering_analytics_workflow_run",
        parameters=[
            OpenApiParameter(
                name="run_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="GitHub Actions run id to inspect.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowRunDetailSerializer,
            400: OpenApiResponse(description="Missing or non-integer run_id, or invalid source_id."),
            404: OpenApiResponse(description="No workflow run with that id in the warehouse."),
        },
        description=(
            "A single workflow run: status, conclusion, duration, branch, attempt, and the attributed pull "
            "request. Run-level only — per-job and per-step detail are not tracked yet."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_run(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_workflow_run(
                team=self.team,
                run_id=_require_int_param(request, "run_id"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        if result is None:
            return Response({"detail": "Workflow run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(WorkflowRunDetailSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_runs",
        parameters=[
            OpenApiParameter(
                name="workflow_name",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow name to list runs for.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the workflow belongs to.",
            ),
            _DATE_FROM,
            _DATE_TO,
            _BRANCH,
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowRunDetailSerializer(many=True),
            400: OpenApiResponse(description="Missing workflow_name/repo, or invalid date or source_id."),
        },
        description=(
            "Runs of a single workflow within a repo over a window (date_from default -30d), newest first. "
            "Optionally scope to a single git branch via `branch`. Each row is run-level — per-job and "
            "per-step detail are not tracked yet. Use this as the GitHub 'workflow' page between the "
            "workflow list and a single run."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_runs(self, request: Request, **kwargs) -> Response:
        workflow_name = request.query_params.get("workflow_name")
        repo = request.query_params.get("repo")
        if not workflow_name or not repo:
            return Response({"detail": "workflow_name and repo are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            runs = api.list_workflow_runs(
                team=self.team,
                repo=repo,
                workflow_name=workflow_name,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, repo, or source_id")
        return Response(WorkflowRunDetailSerializer(instance=runs, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_run_activity",
        parameters=[
            OpenApiParameter(
                name="workflow_name",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow name to load run activity for.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the workflow belongs to.",
            ),
            _DATE_FROM,
            _DATE_TO,
            _BRANCH,
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowRunActivitySerializer,
            400: OpenApiResponse(description="Missing workflow_name/repo, or invalid date or source_id."),
        },
        description=(
            "Compact per-run points for a single workflow over a window (date_from default -30d), newest first, for "
            "the run-activity chart: each run's start time, duration, conclusion, branch, and attributed PR. "
            "Optionally scope to a single git branch via `branch`, matching workflow_runs. Leaner and higher-capped "
            "than workflow_runs so the chart spans the full window even on busy workflows; `truncated` is true when "
            "the cap is hit, so the chart covers only the most recent runs."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_run_activity(self, request: Request, **kwargs) -> Response:
        workflow_name = request.query_params.get("workflow_name")
        repo = request.query_params.get("repo")
        if not workflow_name or not repo:
            return Response({"detail": "workflow_name and repo are required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = api.get_workflow_run_activity(
                team=self.team,
                repo=repo,
                workflow_name=workflow_name,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, repo, or source_id")
        return Response(WorkflowRunActivitySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_runner_costs",
        parameters=[
            OpenApiParameter(
                name="workflow_name",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow name to break down cost for.",
            ),
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="'owner/name' repository the workflow belongs to.",
            ),
            _DATE_FROM,
            _DATE_TO,
            _BRANCH,
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowRunnerCostSerializer(many=True),
            400: OpenApiResponse(description="Missing workflow_name/repo, or invalid date or source_id."),
        },
        description=(
            "A workflow's estimated CI cost broken down by runner tier over a window (date_from default "
            "-30d), highest spend first. Optionally scope to a single git branch via `branch`. Returns an "
            "empty list when the job-level source isn't synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_runner_costs(self, request: Request, **kwargs) -> Response:
        workflow_name = request.query_params.get("workflow_name")
        repo = request.query_params.get("repo")
        if not workflow_name or not repo:
            return Response({"detail": "workflow_name and repo are required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            costs = api.get_workflow_runner_costs(
                team=self.team,
                repo=repo,
                workflow_name=workflow_name,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, repo, or source_id")
        return Response(WorkflowRunnerCostSerializer(instance=costs, many=True).data)

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
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid author, date, or source_id")
        return Response(WorkflowCostSerializer(instance=costs, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_workflow_jobs",
        parameters=[
            OpenApiParameter(
                name="run_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow run id to list jobs for.",
            ),
            OpenApiParameter(
                name="run_attempt",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Which re-run attempt to scope jobs to. Omit to use the run's latest attempt; pass an "
                "explicit attempt to avoid mixing jobs across a re-run's attempts.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowJobSerializer(many=True),
            400: OpenApiResponse(description="Missing or non-integer run_id/run_attempt, or invalid source_id."),
        },
        description=(
            "Jobs of a single workflow run attempt, with per-job duration, runner tier, and estimated cost. "
            "Scoped to one run_attempt (the latest unless specified) so a re-run's attempts don't merge. "
            "Returns an empty list when the job-level source isn't synced yet."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def workflow_jobs(self, request: Request, **kwargs) -> Response:
        try:
            jobs = api.list_workflow_jobs(
                team=self.team,
                run_id=_require_int_param(request, "run_id"),
                run_attempt=_optional_int_param(request, "run_attempt"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(WorkflowJobSerializer(instance=jobs, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_repo_overview",
        parameters=[_DATE_FROM, _DATE_TO, _SOURCE_ID],
        responses={
            200: RepoOverviewSerializer,
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id, or a window over 366 days."),
        },
        description=(
            "Repo-level headline aggregates over a window (default -30d): run count, success rate, re-run "
            "cycles, median PR open-to-merge (bots and drafts excluded; coarse — draft and ready time fused), "
            "and billable minutes + estimated cost — each with its equal-length previous-window twin so a "
            "caller can render honest deltas. Also carries the detected default branch and its completed-run "
            "history series. Cost figures are null until the job-level source is synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def repo_overview(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_repo_overview(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(RepoOverviewSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_master_failures",
        parameters=[_WORKFLOW_DATE_FROM, _DATE_TO, _BRANCH, _SOURCE_ID],
        responses={
            200: MasterFailureGroupSerializer(many=True),
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id, or a window over 366 days."),
        },
        description=(
            "Default-branch failures over a window (default -24h), grouped error-tracking style by "
            "(workflow, de-sharded failing job) with a run count and first/last seen, newest group first. "
            "`branch` overrides the detected default branch. PR-branch failures are deliberately excluded — "
            "at monorepo volume a flat feed is a firehose; those surface per PR. Groups degrade to workflow "
            "level (failed_job '') when the job-level source isn't synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def master_failures(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_master_failures(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(MasterFailureGroupSerializer(instance=result, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_run_failure_logs",
        parameters=[
            OpenApiParameter(
                name="run_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow run id whose failure logs to fetch.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: RunFailureLogsSerializer,
            400: OpenApiResponse(description="Missing or non-integer run_id, or invalid source_id."),
        },
        description=(
            "The thinned CI failure logs of one workflow run, grouped by failed job — the run-scoped twin of "
            "ci_failure_logs for surfaces that aren't PR-scoped (default-branch failures, the run page). "
            "logs_available is false when the run didn't fail or its logs aged out of the short Logs retention."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def run_failure_logs(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_run_failure_logs(
                team=self.team,
                run_id=_require_int_param(request, "run_id"),
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(RunFailureLogsSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_job_aggregates",
        parameters=[
            OpenApiParameter(
                name="workflow_name",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Workflow name to aggregate jobs for.",
            ),
            _DATE_FROM,
            _DATE_TO,
            _BRANCH,
            _SOURCE_ID,
        ],
        responses={
            200: WorkflowJobAggregateSerializer(many=True),
            400: OpenApiResponse(description="Missing workflow_name, or invalid date or source_id."),
        },
        description=(
            "Per-job aggregates for one workflow over a window (default -30d), one row per de-sharded job "
            "name (matrix shards aggregate together), busiest first: queue p50, duration p50/p95, failure "
            "rate, retry pressure, run share (below 1.0 = conditional job), and billable cost. Jobs always "
            "need their run as context — this is the aggregate view; use workflow_jobs for one run's jobs. "
            "Empty when the job-level source isn't synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def job_aggregates(self, request: Request, **kwargs) -> Response:
        workflow_name = request.query_params.get("workflow_name")
        if not workflow_name:
            return Response({"detail": "workflow_name is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = api.list_job_aggregates(
                team=self.team,
                workflow_name=workflow_name,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, workflow_name, or source_id")
        return Response(WorkflowJobAggregateSerializer(instance=result, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_quarantine",
        summary="Flaky-test quarantine file",
        parameters=[
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional 'owner/name' repository to read the quarantine file from. Defaults to the "
                "connected GitHub source's most active repo over the last 30 days.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: QuarantineFileSerializer,
            400: OpenApiResponse(description="Invalid repo or source_id."),
        },
        description=(
            "The repository's checked-in .test_quarantine.json: flaky tests temporarily quarantined with a hard "
            "expiry, classified by urgency (overdue, in grace, expiring soon, active). `available` is false when "
            "the repo has no quarantine file — that is not an error. Parsing is fail-open: malformed entries are "
            "reported in parse_errors while well-formed ones are kept."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def quarantine(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_quarantine(
                team=self.team,
                repo=request.query_params.get("repo") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        return Response(QuarantineFileSerializer(instance=result).data)

    @validated_request(
        request_serializer=QuarantineRequestSerializer,
        operation_id="engineering_analytics_quarantine_request",
        responses={
            201: OpenApiResponse(
                response=QuarantineRequestResultSerializer,
                description="The opened pull request, plus the tracking issue for a new quarantine.",
            ),
            400: OpenApiResponse(
                description="Invalid input, or the write could not be completed (no GitHub App installed on the "
                "repo's org, a malformed quarantine file, or a GitHub failure). The detail message is safe to show."
            ),
        },
        summary="Quarantine, extend, or unquarantine a flaky test",
        description=(
            "Opens a pull request that edits the repository's checked-in .test_quarantine.json — and, for a new "
            "quarantine, a tracking issue the PR links but does not close. The file stays the source of truth that "
            "CI enforces; this never bypasses it. A quarantine only affects CI runs that start after the PR merges."
        ),
    )
    @action(detail=False, methods=["post"], url_path="quarantine/request", pagination_class=None)
    def quarantine_request(self, request: TypedRequest[QuarantineRequest], **kwargs) -> Response:
        result = api.request_quarantine(
            team=self.team,
            request=request.validated_data,
            user_access_control=self.user_access_control,
        )
        return Response(QuarantineRequestResultSerializer(instance=result).data, status=status.HTTP_201_CREATED)
