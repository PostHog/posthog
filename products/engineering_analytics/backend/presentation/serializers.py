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
    CIStatusRollup,
    PRLifecycle,
    PRLifecycleEvent,
    PullRequest,
    PullRequestList,
    PullRequestListItem,
    QuarantineEntry,
    QuarantineFile,
    RepoRef,
    WorkflowHealthDay,
    WorkflowHealthItem,
)


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


class CIStatusRollupSerializer(DataclassSerializer):
    class Meta:
        dataclass = CIStatusRollup
        extra_kwargs = {
            "runs": {"help_text": "Distinct workflows run on the PR's head SHA."},
            "passing": {"help_text": "Latest runs that completed with conclusion 'success'."},
            "failing": {"help_text": "Latest runs that completed with conclusion 'failure' or 'timed_out'."},
            "pending": {"help_text": "Latest runs not yet completed (queued or in progress)."},
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


class WorkflowHealthDaySerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowHealthDay
        extra_kwargs = {
            "day": {"help_text": "UTC calendar day."},
            "run_count": {"help_text": "Runs started that day."},
            "completed": {"help_text": "Runs that completed that day."},
            "successes": {"help_text": "Completed runs with conclusion 'success' that day."},
        }


class WorkflowHealthItemSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="Repository the workflow runs in.")
    daily = WorkflowHealthDaySerializer(
        many=True, help_text="Daily run history across the whole window, oldest first, zero-filled."
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
                "help_text": "When the most recent run with conclusion 'failure' started, or null.",
                "allow_null": True,
            },
        }
