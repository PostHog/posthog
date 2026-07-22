"""Payloads for PR-scoped reads: backlog cards, lists, lifecycle, logs, and cost."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    BranchPRMatch,
    CICardSummary,
    CIFailureLogs,
    CIStatusRollup,
    PRCostSummary,
    PRLifecycle,
    PRLifecycleEvent,
    PRLLMSpend,
    PullRequest,
    PullRequestList,
    PullRequestListItem,
    PushCISample,
    RunCost,
    WorkflowCost,
)
from products.engineering_analytics.backend.presentation.serializers._shared import (
    CIJobFailureLogSerializer,
    RepoRefSerializer,
)


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


class PRLLMSpendSerializer(DataclassSerializer):
    class Meta:
        dataclass = PRLLMSpend
        extra_kwargs = {
            "cost_usd": {
                "help_text": "Total agent LLM token cost in USD attributed to this PR "
                "(sum of $ai_total_cost_usd over the matched $ai_generation events).",
            },
            "input_tokens": {"help_text": "Total input (prompt) tokens across the attributed generations."},
            "output_tokens": {"help_text": "Total output (completion) tokens across the attributed generations."},
            "generations": {
                "help_text": "Number of $ai_generation events attributed to this PR by git branch ($ai_git_branch).",
            },
        }


class PRCostSummarySerializer(DataclassSerializer):
    by_workflow = WorkflowCostSerializer(many=True, help_text="Same spend broken down per workflow.")
    by_run = RunCostSerializer(
        many=True, help_text="Same spend broken down per workflow run, keyed by (run_id, run_attempt)."
    )
    llm_spend = PRLLMSpendSerializer(
        required=False,
        allow_null=True,
        help_text="Agent LLM token spend attributed to this PR by git branch ($ai_git_branch), or null when "
        "no generation matched — independent of the CI cost figures, so it can be present even when "
        "jobs_available is false. The UI hides the row when null.",
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


class PushCISampleSerializer(DataclassSerializer):
    class Meta:
        dataclass = PushCISample
        extra_kwargs = {
            "head_sha": {"help_text": "Head commit SHA of this push (CI round)."},
            "started_at": {"help_text": "Earliest workflow-run start on this push."},
            "wall_seconds": {
                "help_text": "Wall-clock CI seconds for this push: earliest run start to latest completed "
                "run end. Null while nothing has completed.",
                "allow_null": True,
            },
            "failed": {
                "help_text": "True when any latest-per-workflow run on this push concluded 'failure' or 'timed_out'.",
            },
            "pending": {"help_text": "True when any latest-per-workflow run on this push hasn't completed yet."},
        }


class PullRequestListItemSerializer(DataclassSerializer):
    author = AuthorSerializer(help_text="The pull request author.")
    repo = RepoRefSerializer(help_text="Repository the pull request belongs to.")
    ci = CIStatusRollupSerializer(help_text="CI status from the latest workflow runs on the head SHA.")
    push_history = PushCISampleSerializer(
        many=True,
        help_text="This PR's CI rounds oldest-first, capped to the most recent pushes - one sample per "
        "push for the push-history sparkline. `pushes` stays the uncapped count.",
    )

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


class BranchPRMatchSerializer(DataclassSerializer):
    class Meta:
        dataclass = BranchPRMatch
        extra_kwargs = {
            "repo": {"help_text": "Repository the pull request belongs to, as 'owner/name'."},
            "number": {"help_text": "Pull request number within the repository — pair with `repo` to link to it."},
            "title": {
                "help_text": "Pull request title, or null when the snapshot carries no title.",
                "allow_null": True,
            },
            "state": {
                "help_text": "Derived PR state ('open', 'closed', 'merged'), or null when the snapshot carries no state.",
                "allow_null": True,
            },
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
