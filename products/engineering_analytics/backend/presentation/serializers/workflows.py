"""Payloads for workflow/run/job-scoped reads: health, activity, jobs, costs, and master state."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    CostPerMergeBucket,
    CurrentBranchHealth,
    MasterFailureGroup,
    OpenToMergeBucket,
    PassRateBucket,
    RepoOverview,
    RunFailureLogs,
    TimeToGreenBucket,
    WorkflowHealthBucket,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunActivityPoint,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.presentation.serializers._shared import (
    CIJobFailureLogSerializer,
    RepoRefSerializer,
)


class WorkflowRunDetailSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="Repository the run belongs to.")

    class Meta:
        dataclass = WorkflowRunDetail
        extra_kwargs = {
            "id": {"help_text": "GitHub Actions run id."},
            "workflow_name": {"help_text": "GitHub Actions workflow name."},
            "head_sha": {"help_text": "Commit SHA the run was triggered on."},
            "head_branch": {"help_text": "Git branch the run was triggered on."},
            "status": {"help_text": "Raw run status: 'queued', 'in_progress', 'completed', etc."},
            "conclusion": {
                "help_text": "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', "
                "'action_required', ...), or null while still in progress.",
                "allow_null": True,
            },
            "run_started_at": {
                "help_text": "When the run started, or null for a queued/barely-started run.",
                "allow_null": True,
            },
            "updated_at": {
                "help_text": "When the run was last updated (its finish time once completed), or null when unstarted.",
                "allow_null": True,
            },
            "duration_seconds": {
                "help_text": "Wall-clock duration in seconds; null until the run completes.",
                "allow_null": True,
            },
            "run_attempt": {"help_text": "Re-run attempt number; 1 for the first attempt."},
            "pr_number": {"help_text": "Attributed pull request number, or 0 when unattributed."},
        }


class WorkflowRunActivityPointSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowRunActivityPoint
        extra_kwargs = {
            "run_id": {"help_text": "GitHub Actions run id."},
            "conclusion": {
                "help_text": "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', ...), "
                "or null while still in progress.",
                "allow_null": True,
            },
            "run_started_at": {
                "help_text": "When the run started. Never null on this endpoint: runs without a parseable "
                "start timestamp are excluded from the window (they can't be plotted on the chart's time axis).",
            },
            "duration_seconds": {
                "help_text": "Wall-clock duration in seconds; null until the run completes.",
                "allow_null": True,
            },
            "head_branch": {"help_text": "Git branch the run was triggered on, or '' when unknown."},
            "pr_number": {"help_text": "Attributed pull request number, or 0 when unattributed."},
            "head_sha": {"help_text": "Head commit SHA of the run/commit, or '' when unknown."},
        }


class WorkflowRunActivitySerializer(DataclassSerializer):
    points = WorkflowRunActivityPointSerializer(
        many=True, help_text="Per-run chart points, newest first, capped at `limit`."
    )

    class Meta:
        dataclass = WorkflowRunActivity
        extra_kwargs = {
            "truncated": {
                "help_text": "True when more runs matched than the cap; `points` is the newest `limit` runs, so the "
                "chart covers only the most recent activity, not the full window.",
            },
            "limit": {"help_text": "Maximum number of run points returned in `points`."},
        }


class WorkflowJobSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowJob
        extra_kwargs = {
            "id": {"help_text": "GitHub Actions job id."},
            "run_id": {"help_text": "The workflow run id this job belongs to."},
            "name": {"help_text": "Job name."},
            "status": {"help_text": "Raw job status: 'queued', 'in_progress', 'completed', etc."},
            "conclusion": {
                "help_text": "Job conclusion ('success', 'failure', 'cancelled', 'skipped', ...), or null while running.",
                "allow_null": True,
            },
            "started_at": {"help_text": "When the job started, or null while still queued.", "allow_null": True},
            "completed_at": {"help_text": "When the job completed, or null while still running.", "allow_null": True},
            "duration_seconds": {
                "help_text": "Wall-clock duration in seconds; null until the job completes.",
                "allow_null": True,
            },
            "runner_provider": {
                "help_text": "Where the job ran: 'github_hosted' (free for open source), 'self_hosted' (billable), "
                "or 'unknown'.",
            },
            "runner_label": {
                "help_text": "Runner tier the job ran on (e.g. '16-core' or 'ubuntu-latest'), or '' when unknown."
            },
            "estimated_cost_usd": {
                "help_text": "Estimated cost in USD from runner tier + elapsed time; null when the tier is "
                "unknown or the job hasn't finished.",
                "allow_null": True,
            },
        }


class WorkflowRunnerCostSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowRunnerCost
        extra_kwargs = {
            "provider": {"help_text": "'self_hosted' (billable), 'github_hosted' (free), or 'unknown'."},
            "runner_label": {"help_text": "Runner tier, e.g. '16-core' or 'ubuntu-latest'."},
            "job_count": {"help_text": "Jobs that ran on this tier for the workflow."},
            "billable_minutes": {"help_text": "Billable minutes on this tier."},
            "estimated_cost_usd": {
                "help_text": "Estimated cost in USD on this tier; null for non-billable (github-hosted/non-Linux).",
                "allow_null": True,
            },
        }


class WorkflowHealthBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowHealthBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to the item's granularity (top of hour, midnight, or Monday)."
            },
            "run_count": {"help_text": "Runs started in this bucket."},
            "completed": {"help_text": "Runs that completed in this bucket."},
            "successes": {"help_text": "Completed runs with conclusion 'success' in this bucket."},
            "failures": {
                "help_text": "Completed runs that failed in this bucket (conclusion 'failure' or 'timed_out'); "
                "excludes skipped, cancelled, and action_required runs."
            },
        }


class WorkflowHealthItemSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="Repository the workflow runs in.")
    buckets = WorkflowHealthBucketSerializer(
        many=True, help_text="Run history across the whole window, oldest first, zero-filled, bucketed by granularity."
    )

    class Meta:
        dataclass = WorkflowHealthItem
        extra_kwargs = {
            "workflow_name": {"help_text": "GitHub Actions workflow name."},
            "run_count": {"help_text": "Total runs started in the window."},
            "success_rate": {
                "help_text": "Fraction of completed runs that succeeded (0-1). Null if no completed runs.",
                "allow_null": True,
            },
            "p50_seconds": {
                "help_text": "Median duration in seconds over successful runs only — cancelled (superseded) and "
                "failed runs end early and would bias the percentile. Null if no run succeeded in the window.",
                "allow_null": True,
            },
            "p95_seconds": {
                "help_text": "95th-percentile duration in seconds over successful runs only — cancelled "
                "(superseded) and failed runs end early and would bias the percentile. Null if no run succeeded "
                "in the window.",
                "allow_null": True,
            },
            "last_failure_at": {
                "help_text": "When the most recent failing run (conclusion 'failure' or 'timed_out') started, or null.",
                "allow_null": True,
            },
            "latest_run_failed": {
                "help_text": "Whether the most recent completed run was a decisive failure (conclusion 'failure' "
                "or 'timed_out'). Null when no run has completed in the window. Powers the OK/RED status badge.",
                "allow_null": True,
            },
            "latest_run_conclusion": {
                "help_text": "Raw conclusion of the most recent completed run ('success', 'cancelled', 'skipped', "
                "...), so a real pass can be told from a non-failure non-success. Null when none completed.",
                "allow_null": True,
            },
            "granularity": {
                "help_text": "Bucket width of the `buckets` series, chosen to fit the window: 'hour', 'day', or 'week'."
            },
            "billable_minutes": {
                "help_text": "Billable (self-hosted) minutes over this workflow's jobs in the window. Null when "
                "the job-level source isn't synced.",
                "allow_null": True,
            },
            "estimated_cost_usd": {
                "help_text": "Estimated cost in USD over this workflow's jobs in the window. Null when nothing "
                "was costable or the job source isn't synced.",
                "allow_null": True,
            },
            "rerun_cycles": {
                "help_text": "Runs in the window that were a 2nd+ attempt - retry pressure, a flakiness proxy."
            },
            "success_rate_prev": {
                "help_text": "Success rate over the equal-length window before date_from - the delta baseline. "
                "Null when that window had no completed runs.",
                "allow_null": True,
            },
        }


class CostPerMergeBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = CostPerMergeBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to cost_series_granularity (top of hour, midnight, or Monday)."
            },
            "estimated_cost_usd": {
                "help_text": "Estimated Depot CI cost (USD) of all runs started in this bucket. Null when nothing "
                "was costable (no billable self-hosted Linux jobs) or the job source isn't synced.",
                "allow_null": True,
            },
            "merges": {"help_text": "PRs merged in this bucket (all authors, bots included)."},
            "cost_per_merge_usd": {
                "help_text": "Rolling ratio: trailing-window CI cost divided by trailing-window merges "
                "(24 h / 7 d / 4 w to match the granularity). Null when the trailing window had no merges "
                "or no costable cost.",
                "allow_null": True,
            },
        }


class TimeToGreenBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = TimeToGreenBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to time_to_green_series_granularity (top of hour, midnight, or Monday)."
            },
            "p50_seconds": {
                "help_text": "Median wall-clock seconds of successful PR-attributed CI runs started in this bucket. "
                "Null when the bucket had no successful PR run (a gap, not instant CI).",
                "allow_null": True,
            },
        }


class PassRateBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = PassRateBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to success_rate_series_granularity (top of hour, midnight, or Monday)."
            },
            "success_rate": {
                "help_text": "Fraction (0-1) of completed runs started in this bucket that succeeded. "
                "Null when the bucket had no completed run (a gap, not a 0% pass rate).",
                "allow_null": True,
            },
        }


class OpenToMergeBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = OpenToMergeBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to open_to_merge_series_granularity (top of hour, midnight, or Monday)."
            },
            "p50_seconds": {
                "help_text": "Median merged_at - created_at seconds over PRs merged in this bucket, bots and "
                "drafts excluded. Null when nothing merged in the bucket (a gap, not instant merges).",
                "allow_null": True,
            },
        }


class RepoOverviewSerializer(DataclassSerializer):
    cost_series = CostPerMergeBucketSerializer(
        many=True,
        help_text="CI cost per merged PR across the window, oldest first, zero-filled, bucketed by "
        "cost_series_granularity. Empty when the job-level source isn't synced or include_series=false.",
    )
    time_to_green_series = TimeToGreenBucketSerializer(
        many=True,
        help_text="Median time-to-green (p50 successful PR-attributed CI run duration) per bucket across the "
        "window, oldest first, bucketed by time_to_green_series_granularity. Empty buckets carry null; the "
        "whole series is empty when include_series=false.",
    )
    success_rate_series = PassRateBucketSerializer(
        many=True,
        help_text="CI pass rate (completed runs that succeeded, all branches) per bucket across the window, "
        "oldest first, bucketed by success_rate_series_granularity. Empty buckets carry null; the whole "
        "series is empty when include_series=false.",
    )
    open_to_merge_series = OpenToMergeBucketSerializer(
        many=True,
        help_text="Median time-to-merge (p50 open_to_merge_seconds, bots/drafts excluded) per bucket across "
        "the window, oldest first, bucketed by open_to_merge_series_granularity. Empty buckets carry null; "
        "the whole series is empty when include_series=false.",
    )

    class Meta:
        dataclass = RepoOverview
        extra_kwargs = {
            "run_count": {"help_text": "Workflow runs started in the window, all branches and workflows."},
            "run_count_prev": {
                "help_text": "Same count over the equal-length window immediately before date_from — the delta baseline."
            },
            "success_rate": {
                "help_text": "Fraction of completed runs that succeeded (0-1) in the window. Null if none completed.",
                "allow_null": True,
            },
            "success_rate_prev": {
                "help_text": "Success rate over the previous window. Null if none completed.",
                "allow_null": True,
            },
            "rerun_cycles": {"help_text": "Runs in the window that were a 2nd+ attempt (attempt > 1)."},
            "rerun_cycles_prev": {"help_text": "Re-run cycles over the previous window."},
            "merged_pr_count": {
                "help_text": "PRs merged in the window, all authors and bots included — the merge population "
                "that triggered the CI spend, so it divides cleanly into billable_minutes and estimated_cost_usd."
            },
            "merged_pr_count_prev": {"help_text": "Merged-PR count over the previous window."},
            "median_open_to_merge_seconds": {
                "help_text": "Median merged_at - created_at over PRs merged in the window, bots and drafts excluded. "
                "Coarse by design: draft and ready-for-review time are fused. Null when nothing merged.",
                "allow_null": True,
            },
            "median_open_to_merge_seconds_prev": {
                "help_text": "The same median over the previous window. Null when nothing merged.",
                "allow_null": True,
            },
            "billable_minutes": {
                "help_text": "Billable (self-hosted) job minutes in the window; null when the job-level source "
                "isn't synced.",
                "allow_null": True,
            },
            "billable_minutes_prev": {
                "help_text": "Billable minutes over the previous window; null when the job-level source isn't synced.",
                "allow_null": True,
            },
            "estimated_cost_usd": {
                "help_text": "Estimated CI cost in USD (billable minutes x runner-tier rate); null when the "
                "job-level source isn't synced.",
                "allow_null": True,
            },
            "estimated_cost_usd_prev": {
                "help_text": "Estimated cost over the previous window; null when the job-level source isn't synced.",
                "allow_null": True,
            },
            "jobs_available": {"help_text": "Whether the job-level source is synced (cost and queue figures exist)."},
            "default_branch": {"help_text": "'master' or 'main', picked by observed run volume in the window."},
            "cost_series_granularity": {
                "help_text": "Bucket width of the cost_series trend, chosen to fit the window: 'hour', 'day', or 'week'."
            },
            "time_to_green_series_granularity": {
                "help_text": "Bucket width of the time_to_green_series trend: 'hour', 'day', or 'week'."
            },
            "success_rate_series_granularity": {
                "help_text": "Bucket width of the success_rate_series trend: 'hour', 'day', or 'week'."
            },
            "open_to_merge_series_granularity": {
                "help_text": "Bucket width of the open_to_merge_series trend: 'hour', 'day', or 'week'."
            },
        }


class CurrentBranchHealthSerializer(DataclassSerializer):
    class Meta:
        dataclass = CurrentBranchHealth
        extra_kwargs = {
            "default_branch": {
                "help_text": "Detected default branch ('master' or 'main') from runs in the same 24-hour window."
            },
            "settled_workflows": {"help_text": "Workflows with at least one completed run in the last 24 hours."},
            "failing_workflows": {
                "help_text": "Workflows whose latest completed run in the last 24 hours failed or timed out."
            },
            "failing_workflow_names": {
                "help_text": "Alphabetical preview of failing workflow names, capped at 20; use failing_workflows "
                "for the complete count."
            },
        }


class MasterFailureGroupSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="Repository the failures occurred in.")

    class Meta:
        dataclass = MasterFailureGroup
        extra_kwargs = {
            "workflow_name": {"help_text": "GitHub Actions workflow name the failing runs belong to."},
            "failed_job": {
                "help_text": "De-sharded failing job name (matrix '(G/N)' suffix stripped) — the group's failure "
                "signature together with the workflow. '' when the job-level source isn't synced and the group "
                "degrades to workflow level."
            },
            "run_count": {"help_text": "Distinct failing default-branch runs in this group within the window."},
            "first_seen": {"help_text": "When the oldest failing run in the group started."},
            "last_seen": {"help_text": "When the newest failing run in the group started."},
            "latest_run_id": {"help_text": "Run id of the newest failing run — the drill-down anchor."},
        }


class RunFailureLogsSerializer(DataclassSerializer):
    jobs = CIJobFailureLogSerializer(
        many=True, help_text="Failed CI jobs of this run with their thinned failure logs, grouped by job."
    )

    class Meta:
        dataclass = RunFailureLogs
        extra_kwargs = {
            "run_id": {"help_text": "Workflow run id the failure logs are for."},
            "logs_available": {
                "help_text": "False when no failure logs were found — the run didn't fail, or its logs aged out of "
                "the short Logs retention.",
            },
            "truncated": {"help_text": "True when the overall line cap across all jobs was hit."},
        }


class WorkflowJobAggregateSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowJobAggregate
        extra_kwargs = {
            "job_name": {
                "help_text": "De-sharded job name: the matrix '(G/N)' suffix is stripped and unexpanded "
                "'${{ matrix.* }}' templates are collapsed, so shards of one matrix aggregate together."
            },
            "job_count": {"help_text": "Job instances observed in the window (all shards, all attempts)."},
            "shard_count": {"help_text": "Distinct raw job names inside the group - the observed matrix width."},
            "runs_in": {"help_text": "Distinct workflow runs the job appeared in."},
            "run_share": {
                "help_text": "runs_in divided by the workflow's total runs in the window; below 1.0 means the "
                "job is conditional and skips some runs. Null when the workflow had no runs.",
                "allow_null": True,
            },
            "queue_p50_seconds": {
                "help_text": "Median queue wait (created to started) in seconds - where runner-capacity problems "
                "hide. Null when nothing started.",
                "allow_null": True,
            },
            "p50_seconds": {
                "help_text": "Median duration of successful job instances, in seconds — cancelled and failed "
                "instances end early and would bias the percentile. Null if none succeeded.",
                "allow_null": True,
            },
            "p95_seconds": {
                "help_text": "95th-percentile duration of successful job instances, in seconds — cancelled and "
                "failed instances end early and would bias the percentile. Null if none succeeded.",
                "allow_null": True,
            },
            "failure_rate": {
                "help_text": "Decisive failures ('failure', 'timed_out') over completed instances (0-1). Null if "
                "none completed.",
                "allow_null": True,
            },
            "retry_job_count": {"help_text": "Job instances that ran on a 2nd+ run attempt - retry pressure."},
            "billable_minutes": {
                "help_text": "Billable (self-hosted) minutes across the group's instances; null when every "
                "instance ran on an unknown tier.",
                "allow_null": True,
            },
            "estimated_cost_usd": {
                "help_text": "Estimated cost in USD via the runner-tier rate ladder; null when every instance ran "
                "on an unknown tier.",
                "allow_null": True,
            },
        }
