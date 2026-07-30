"""Workflow/run/job-scoped reads: health, activity, jobs, costs, and master state."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.workflows import (
    CurrentBranchHealthSerializer,
    MasterFailureGroupSerializer,
    RepoOverviewSerializer,
    RunFailureLogsSerializer,
    WorkflowHealthItemSerializer,
    WorkflowJobAggregateSerializer,
    WorkflowJobSerializer,
    WorkflowRunActivitySerializer,
    WorkflowRunDetailSerializer,
    WorkflowRunnerCostSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _BRANCH,
    _DATE_FROM,
    _DATE_TO,
    _REPO,
    _RUN_SCOPE,
    _SOURCE_ID,
    _WORKFLOW_DATE_FROM,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
    _bool_param,
    _optional_int_param,
    _require_int_param,
)


class WorkflowActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = [
        "workflow_health",
        "workflow_run",
        "workflow_runs",
        "workflow_run_activity",
        "workflow_runner_costs",
        "workflow_jobs",
        "repo_overview",
        "current_branch_health",
        "repo_run_activity",
        "master_failures",
        "run_failure_logs",
        "job_aggregates",
    ]

    @extend_schema(
        operation_id="engineering_analytics_workflow_health",
        parameters=[_WORKFLOW_DATE_FROM, _DATE_TO, _BRANCH, _RUN_SCOPE, _SOURCE_ID, _REPO],
        responses={
            200: WorkflowHealthItemSerializer(many=True),
            400: OpenApiResponse(
                description="Invalid date_from, date_to, run_scope, or source_id, or a window longer than 366 days."
            ),
        },
        description=(
            "Per-workflow CI health over a window (default last 24 hours, maximum 366 days): run count, success "
            "rate, p50/p95 duration, last failure time, latest-run status, and a zero-filled run history bucketed "
            "by hour/day/week to fit the window. p50/p95 are over successful runs only, so cancelled (superseded) "
            "and failed runs never bias the duration trend. Optionally scope to a single git branch via `branch`, "
            "or to attributed pull-request runs via `run_scope=pull_request`. Use this for 'is CI getting slower' "
            "and 'which workflow is the long pole'; compare two windows to get a trend."
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
                run_scope=request.query_params.get("run_scope") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(WorkflowHealthItemSerializer(instance=result, many=True).data)

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
            _REPO,
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
                repo=request.query_params.get("repo") or None,
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
            _REPO,
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
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(WorkflowJobSerializer(instance=jobs, many=True).data)

    @extend_schema(
        operation_id="engineering_analytics_repo_overview",
        parameters=[
            _DATE_FROM,
            _DATE_TO,
            OpenApiParameter(
                name="include_series",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Set false to skip the chart series (cost_series, time_to_green_series, "
                "success_rate_series, open_to_merge_series return empty) and their query cost — for "
                "headline-only consumers like the weekly digest. Defaults to true.",
            ),
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: RepoOverviewSerializer,
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id, or a window over 366 days."),
        },
        description=(
            "Repo-level headline aggregates over a window (default -30d): run count, success rate, re-run "
            "cycles, merged-PR count (bots included), median PR open-to-merge (bots and drafts excluded; "
            "coarse — draft and ready time fused), and billable minutes + estimated cost — each with its "
            "equal-length previous-window twin so a caller can render honest deltas. Also carries the "
            "detected default branch and its completed-run history series (skippable via include_series=false). "
            "Cost figures are null until the job-level source is synced."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def repo_overview(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_repo_overview(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                include_series=_bool_param(request, "include_series", default=True),
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, include_series, or source_id")
        return Response(RepoOverviewSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_current_branch_health",
        parameters=[_SOURCE_ID, _REPO],
        responses={
            200: CurrentBranchHealthSerializer,
            400: OpenApiResponse(description="Invalid source_id."),
        },
        description=(
            "Current default-branch CI verdict over the fixed last-24-hours window. Counts every workflow whose "
            "latest completed run failed or timed out; failing workflow names are a bounded preview. The default "
            "branch is detected from the same window, independently of analytics date filters."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def current_branch_health(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_current_branch_health(
                team=self.team,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(CurrentBranchHealthSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_repo_run_activity",
        parameters=[
            _DATE_FROM,
            _DATE_TO,
            # This endpoint never aggregates across branches, so the shared _BRANCH "omit to aggregate"
            # wording would misdescribe the omit behavior in every generated client.
            OpenApiParameter(
                name="branch",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional exact git branch (head_branch) to chart, e.g. 'main'. "
                "Omit or leave blank to use the repo's detected default branch.",
            ),
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: WorkflowRunActivitySerializer,
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id, or a window over 366 days."),
        },
        description=(
            "Default-branch health as compact chart points over a window (default -30d), newest first, for the "
            "repo-hub run-activity chart. All of a commit's workflow runs are collapsed into ONE point per commit "
            "(head SHA): its earliest workflow start, wall-clock duration until the last workflow settled (null "
            "while any is still running), and an overall conclusion that is 'failure' if any workflow decisively "
            "failed, else 'success' when at least one passed, else 'neutral'. `branch` overrides the detected "
            "default branch. `truncated` is true when more commits matched than the cap, so the chart covers only "
            "the most recent commits."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def repo_run_activity(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_repo_run_activity(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                branch=request.query_params.get("branch") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(WorkflowRunActivitySerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_master_failures",
        parameters=[_WORKFLOW_DATE_FROM, _DATE_TO, _BRANCH, _SOURCE_ID, _REPO],
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
                repo=request.query_params.get("repo") or None,
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
            _REPO,
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
                repo=request.query_params.get("repo") or None,
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
            _REPO,
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
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, workflow_name, or source_id")
        return Response(WorkflowJobAggregateSerializer(instance=result, many=True).data)
