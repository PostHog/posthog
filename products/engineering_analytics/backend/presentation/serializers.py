"""DRF serializers for engineering_analytics.

Output-only serializers that turn the facade's frozen dataclasses into JSON via
``DataclassSerializer``. Field types are auto-derived from the contract types;
``help_text`` is added through ``Meta.extra_kwargs`` so it flows downstream into
the OpenAPI spec, generated TypeScript types, and the ``pr_lifecycle`` MCP tool
schema.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    CICardSummary,
    CIFailureLogLine,
    CIFailureLogs,
    CIJobFailureLog,
    CIStatusRollup,
    GitHubSource,
    MasterFailureGroup,
    PRCostSummary,
    PRLifecycle,
    PRLifecycleEvent,
    PullRequest,
    PullRequestList,
    PullRequestListItem,
    QuarantineEntry,
    QuarantineFile,
    QuarantineRequest,
    QuarantineRequestResult,
    RepoOverview,
    RepoRef,
    RunCost,
    RunFailureLogs,
    WorkflowCost,
    WorkflowHealthBucket,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunActivityPoint,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)


class GitHubSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = GitHubSource
        extra_kwargs = {
            "id": {"help_text": "Source id — pass as `source_id` to the other endpoints to read this source."},
            "repo": {"help_text": "Connected repository as 'owner/name', or '' if unknown."},
            "prefix": {"help_text": "User-chosen warehouse table-name prefix for this source, or '' when none."},
        }


class RepoRefSerializer(DataclassSerializer):
    class Meta:
        dataclass = RepoRef
        extra_kwargs = {
            "provider": {"help_text": "Code host provider, e.g. 'github'."},
            "owner": {"help_text": "Repository owner or organization."},
            "name": {"help_text": "Repository name."},
        }


class AuthorSerializer(DataclassSerializer):
    class Meta:
        dataclass = Author
        extra_kwargs = {
            "handle": {"help_text": "Login handle of the pull request author."},
            "display_name": {"help_text": "Human-readable name; equals the handle in v1."},
            "avatar_url": {"help_text": "URL of the author's avatar image."},
            "is_bot": {"help_text": "True if the author is a bot (handle ends in [bot] or is a known bot)."},
        }


class PullRequestSerializer(DataclassSerializer):
    author = AuthorSerializer(help_text="The pull request author.")
    repo = RepoRefSerializer(help_text="Repository the pull request belongs to.")

    class Meta:
        dataclass = PullRequest
        extra_kwargs = {
            "id": {"help_text": "GitHub pull request id."},
            "number": {"help_text": "Pull request number within the repository."},
            "title": {"help_text": "Pull request title."},
            "state": {"help_text": "Derived state: 'open', 'closed', or 'merged'."},
            "is_draft": {"help_text": "True if the pull request is a draft."},
            "created_at": {"help_text": "When the pull request was opened."},
            "merged_at": {"help_text": "When the pull request was merged, or null.", "allow_null": True},
            "closed_at": {"help_text": "When the pull request was closed, or null.", "allow_null": True},
        }


class PRLifecycleEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = PRLifecycleEvent
        extra_kwargs = {
            "kind": {"help_text": "Event kind: opened, ci_started, ci_finished, merged, or closed."},
            "at": {"help_text": "When the event occurred."},
            "detail": {
                "help_text": "Optional detail, e.g. workflow name and conclusion for CI events.",
                "allow_null": True,
            },
            "run_id": {
                "help_text": "GitHub Actions run id for ci_started/ci_finished events, null otherwise.",
                "allow_null": True,
            },
        }


class PRLifecycleSerializer(DataclassSerializer):
    pull_request = PullRequestSerializer(help_text="The pull request header.")
    events = PRLifecycleEventSerializer(many=True, help_text="Lifecycle events ordered by time.")

    class Meta:
        dataclass = PRLifecycle
        extra_kwargs = {
            "metric_quality": {
                "help_text": "Always 'partial' — CI events only; reviews and comments are not yet available.",
            },
        }


class CIFailureLogLineSerializer(DataclassSerializer):
    class Meta:
        dataclass = CIFailureLogLine
        extra_kwargs = {
            "original_line": {
                "help_text": "1-based line number in the full pre-thinning job log, or null for a "
                "'... N lines omitted ...' marker. The gap between consecutive values is how many lines were elided.",
                "allow_null": True,
            },
            "text": {"help_text": "The log line text, or the omission-marker text."},
        }


class CIJobFailureLogSerializer(DataclassSerializer):
    lines = CIFailureLogLineSerializer(
        many=True, help_text="The thinned failure-log lines in original order, with omission markers."
    )

    class Meta:
        dataclass = CIJobFailureLog
        extra_kwargs = {
            "job_id": {"help_text": "GitHub Actions job id of the failed job."},
            "run_id": {"help_text": "Workflow run id the job belongs to."},
            "conclusion": {
                "help_text": "Job conclusion ('failure', 'timed_out', ...). Only failed jobs have logs.",
            },
            "branch": {"help_text": "Git branch the run was triggered on, or '' when unknown."},
            "original_total_lines": {
                "help_text": "Total lines in the full job log before thinning (the denominator for each line's "
                "original_line); 0 when unknown.",
            },
            "line_count": {"help_text": "Number of lines returned for this job (after the per-job cap)."},
            "truncated": {"help_text": "True when the job had more failure lines than the per-job cap."},
        }


class CIFailureLogsSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="Repository the pull request belongs to.")
    jobs = CIJobFailureLogSerializer(
        many=True, help_text="Failed CI jobs with their thinned failure logs, grouped by job."
    )

    class Meta:
        dataclass = CIFailureLogs
        extra_kwargs = {
            "pr_number": {"help_text": "Pull request number the failure logs are for."},
            "runs_attributed": {
                "help_text": "Workflow runs attributed to the PR (across all its pushes) that were searched for logs.",
            },
            "logs_available": {
                "help_text": "False when no failure logs were found — CI hasn't failed, the logs aged out of the "
                "short Logs retention, or a fork PR carries no run association to resolve.",
            },
            "truncated": {"help_text": "True when the overall line cap across all jobs was hit."},
        }


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


class WorkflowCostSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowCost
        extra_kwargs = {
            "workflow_name": {"help_text": "GitHub Actions workflow name this cost is for."},
            "billable_minutes": {"help_text": "Billable (self-hosted) minutes for this workflow within the scope."},
            "estimated_cost_usd": {
                "help_text": "Estimated dollar cost for this workflow, or null when nothing was costable.",
                "allow_null": True,
            },
            "costed_jobs": {"help_text": "Costed jobs for this workflow (billable Linux runner, finished)."},
            "unsettled_jobs": {"help_text": "Billable Linux jobs still queued/running for this workflow."},
            "excluded_jobs": {"help_text": "Provider-hosted/non-Linux jobs for this workflow, outside the estimate."},
        }


class RunCostSerializer(DataclassSerializer):
    class Meta:
        dataclass = RunCost
        extra_kwargs = {
            "run_id": {"help_text": "GitHub Actions run id this cost is for."},
            "run_attempt": {"help_text": "Re-run attempt number; 1 for the first attempt."},
            "billable_minutes": {"help_text": "Billable (self-hosted) minutes for this run attempt."},
            "estimated_cost_usd": {
                "help_text": "Estimated dollar cost for this run attempt, or null when nothing was costable.",
                "allow_null": True,
            },
        }


class PRCostSummarySerializer(DataclassSerializer):
    by_workflow = WorkflowCostSerializer(many=True, help_text="Same spend broken down per workflow.")
    by_run = RunCostSerializer(
        many=True, help_text="Same spend broken down per workflow run, keyed by (run_id, run_attempt)."
    )

    class Meta:
        dataclass = PRCostSummary
        extra_kwargs = {
            "jobs_available": {
                "help_text": "False when the job-level source (github_workflow_jobs) isn't synced — every "
                "figure is then zero/null and the cost cards should be hidden.",
            },
            "billable_minutes": {
                "help_text": "Billable CI minutes: each costed (self-hosted) job's elapsed time, summed. "
                "Parallel jobs add up, so this is compute time spent, not wall-clock run duration.",
            },
            "estimated_cost_usd": {
                "help_text": "Estimated dollar cost (sum of per-job estimates: elapsed x tier multiplier x "
                "reference rate). Null when no job was costable.",
                "allow_null": True,
            },
            "costed_jobs": {"help_text": "Jobs counted in the estimate (billable Linux runner, finished)."},
            "unsettled_jobs": {
                "help_text": "Billable Linux jobs still queued/running (no elapsed) — excluded from the estimate.",
            },
            "excluded_jobs": {
                "help_text": "Jobs on provider-hosted (GitHub-hosted, free) or non-Linux runners — outside the estimate.",
            },
        }


class CIStatusRollupSerializer(DataclassSerializer):
    class Meta:
        dataclass = CIStatusRollup
        extra_kwargs = {
            "runs": {"help_text": "Distinct workflows run on the PR's head SHA."},
            "passing": {"help_text": "Latest runs that completed with conclusion 'success'."},
            "failing": {"help_text": "Latest runs that completed with conclusion 'failure' or 'timed_out'."},
            "pending": {"help_text": "Latest runs not yet completed (queued or in progress)."},
            "failing_workflows": {
                "help_text": "The workflow names behind `failing`, sorted - names what is failing instead of "
                "leaving a bare count."
            },
        }


class PullRequestListItemSerializer(DataclassSerializer):
    author = AuthorSerializer(help_text="The pull request author.")
    repo = RepoRefSerializer(help_text="Repository the pull request belongs to.")
    ci = CIStatusRollupSerializer(help_text="CI status from the latest workflow runs on the head SHA.")

    class Meta:
        dataclass = PullRequestListItem
        extra_kwargs = {
            "number": {"help_text": "Pull request number within the repository."},
            "title": {"help_text": "Pull request title."},
            "state": {"help_text": "Derived state: 'open', 'closed', or 'merged'."},
            "is_draft": {"help_text": "True if the pull request is a draft."},
            "created_at": {"help_text": "When the pull request was opened."},
            "merged_at": {"help_text": "When the pull request was merged, or null.", "allow_null": True},
            "open_to_merge_seconds": {
                "help_text": "Coarse open-to-merge time in seconds (merged_at - created_at; fuses draft and "
                "ready-for-review time). Null until merged.",
                "allow_null": True,
            },
            "labels": {"help_text": "GitHub label names on the pull request."},
            "pushes": {
                "help_text": "CI triggers attributed to this PR: distinct head SHAs across its workflow runs. "
                "Fork-PR runs are unattributed.",
            },
            "rerun_cycles": {
                "help_text": "Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run).",
            },
            "estimated_cost_usd": {
                "help_text": "Estimated CI cost in USD summed over this PR's jobs (billable runners only). "
                "Null when nothing was costable or the job-level source isn't synced.",
                "allow_null": True,
            },
            "billable_minutes": {
                "help_text": "Billable (self-hosted) minutes summed over this PR's jobs. Null when the job "
                "source isn't synced.",
                "allow_null": True,
            },
        }


class PullRequestListSerializer(DataclassSerializer):
    items = PullRequestListItemSerializer(many=True, help_text="Pull requests, newest first, capped at `limit`.")

    class Meta:
        dataclass = PullRequestList
        extra_kwargs = {
            "truncated": {
                "help_text": "True when more pull requests match than the cap; `items` is the newest `limit` rows "
                "and the aggregate counts in ci_cards can exceed it.",
            },
            "limit": {"help_text": "Maximum number of pull requests returned in `items`."},
        }


class CICardSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = CICardSummary
        extra_kwargs = {
            "open_prs": {"help_text": "Count of open pull requests."},
            "repos": {"help_text": "Distinct repositories with at least one open pull request."},
            "stuck": {"help_text": "Open, non-draft, non-bot pull requests older than 7 days."},
            "failing_ci": {
                "help_text": "Open pull requests with at least one failing latest CI run. May lag until the "
                "workflow_run webhook settles late completions.",
            },
        }


class QuarantineEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineEntry
        extra_kwargs = {
            "id": {
                "help_text": "Test selector: an exact test id, a file, a directory, a class prefix, or "
                "'product:<dashed-name>'.",
            },
            "runner": {"help_text": "Test runner the selector targets, e.g. 'pytest' or 'jest'."},
            "reason": {"help_text": "Why the test was quarantined."},
            "owner": {"help_text": "GitHub team or user handle responsible for the fix."},
            "issue": {"help_text": "Tracking issue URL, or empty when none was filed."},
            "added": {"help_text": "ISO date the entry was added."},
            "expires": {"help_text": "ISO date the quarantine expires; past it the test blocks CI normally again."},
            "mode": {
                "help_text": "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).",
            },
            "lifecycle": {
                "help_text": "Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), "
                "'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).",
            },
            "days_until_expiry": {"help_text": "Days until the entry expires; negative once past expiry."},
            "selector_kind": {
                "help_text": "What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.",
            },
        }


class QuarantineFileSerializer(DataclassSerializer):
    entries = QuarantineEntrySerializer(
        many=True,
        help_text="Quarantined selectors, most urgent first (overdue, in_grace, expiring_soon, active), "
        "then by soonest expiry.",
    )
    repo = RepoRefSerializer(
        help_text="Repository the file was read from. Null in local-dev mode, where the server's own checkout is read.",
        allow_null=True,
    )

    class Meta:
        dataclass = QuarantineFile
        extra_kwargs = {
            "available": {
                "help_text": "False when the repository has no quarantine file (not an error) or it could not "
                "be fetched.",
            },
            "parse_errors": {
                "help_text": "Contract violations (malformed JSON, bad entries) or fetch failures. Malformed "
                "entries are dropped; well-formed ones are kept.",
            },
            "parse_warnings": {"help_text": "Forward-compatibility notices, e.g. unknown entry fields."},
            "source_url": {
                "help_text": "GitHub blob URL of the quarantine file, or empty when read locally or unavailable.",
            },
            "generated_at": {"help_text": "When this snapshot was computed (UTC); expiry math uses this clock."},
        }


class QuarantineRequestSerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineRequest
        extra_kwargs = {
            "operation": {
                "help_text": "What to do: 'quarantine' (add or replace an entry and file a tracking issue), 'extend' "
                "(re-stamp an existing entry's expiry, reusing its issue), or 'remove' (delete the entry). All three "
                "open a pull request.",
            },
            "selector": {
                "help_text": "Test selector to act on: an exact test id, a file, a directory, a class prefix, or "
                "'product:<dashed-name>'.",
            },
            "repo": {
                "help_text": "Optional 'owner/name' repository override; defaults to the team's most active repo.",
                "allow_null": True,
                "required": False,
            },
            # Blank is meaningful: remove sends no reason/owner, and quarantine sends no issue
            # (the server files one). Per-action required checks live in the logic layer.
            "reason": {
                "help_text": "Why the test is quarantined. Required for quarantine and extend; ignored by remove.",
                "required": False,
                "allow_blank": True,
            },
            "owner": {
                "help_text": "GitHub team or user handle responsible for the fix, e.g. '@PostHog/team-x'. Required "
                "for quarantine and extend.",
                "required": False,
                "allow_blank": True,
            },
            "issue": {
                "help_text": "Existing tracking issue URL, carried forward on extend and remove. Ignored by "
                "quarantine, which files a fresh issue.",
                "required": False,
                "allow_blank": True,
            },
            "expires": {
                "help_text": "ISO date the quarantine expires (at most 30 days out). Defaults to 14 days from today. "
                "Ignored by remove.",
                "allow_null": True,
                "required": False,
            },
            "mode": {
                "help_text": "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all). "
                "Defaults to 'run'.",
                "required": False,
            },
        }


class QuarantineRequestResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = QuarantineRequestResult
        extra_kwargs = {
            "pr_url": {"help_text": "URL of the opened pull request that edits the quarantine file."},
            "issue_url": {
                "help_text": "URL of the tracking issue filed for a new quarantine; empty for extend and remove.",
            },
            "branch": {"help_text": "Branch the pull request was opened from."},
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
                "help_text": "Median duration of completed runs, in seconds. Null if none completed.",
                "allow_null": True,
            },
            "p95_seconds": {
                "help_text": "95th-percentile duration of completed runs, in seconds. Null if none completed.",
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


class RepoOverviewSerializer(DataclassSerializer):
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
                "help_text": "Median duration of completed job instances, in seconds. Null if none completed.",
                "allow_null": True,
            },
            "p95_seconds": {
                "help_text": "95th-percentile duration of completed job instances, in seconds. Null if none completed.",
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
