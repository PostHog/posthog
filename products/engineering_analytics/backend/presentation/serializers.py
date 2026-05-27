"""DRF serializers for engineering_analytics.

Output-only serializers that turn the facade's frozen dataclasses into JSON via
``DataclassSerializer``. Field types are auto-derived from the contract types;
``help_text`` is added through ``Meta.extra_kwargs`` so it flows downstream into
the OpenAPI spec, generated TypeScript types, and MCP tool schemas.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    Author,
    PRLifecycle,
    PRLifecycleEvent,
    PullRequest,
    RepoRef,
    TimeToMerge,
    TimeToMergeRow,
    WorkflowReport,
    WorkflowReportRow,
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


class WorkflowReportRowSerializer(DataclassSerializer):
    class Meta:
        dataclass = WorkflowReportRow
        extra_kwargs = {
            "workflow_name": {"help_text": "GitHub Actions workflow name."},
            "total_runs": {"help_text": "Number of runs of this workflow in the window."},
            "success_rate": {"help_text": "Fraction of runs that concluded 'success', from 0.0 to 1.0."},
            "median_duration_seconds": {"help_text": "Median run duration in seconds."},
            "p95_duration_seconds": {"help_text": "95th-percentile run duration in seconds."},
            "last_failed_at": {
                "help_text": "Timestamp of the most recent failed run, or null if none failed in the window.",
                "allow_null": True,
            },
        }


class WorkflowReportSerializer(DataclassSerializer):
    rows = WorkflowReportRowSerializer(many=True, help_text="Workflows in the window, slowest median duration first.")
    repo = RepoRefSerializer(
        allow_null=True,
        required=False,
        help_text="Repository the report is labeled with, if a repo filter was supplied.",
    )

    class Meta:
        dataclass = WorkflowReport
        extra_kwargs = {
            "date_from": {"help_text": "Start of the window, echoed from the request (relative string or ISO8601)."},
            "date_to": {
                "help_text": "End of the window, echoed from the request; null means 'now'.",
                "allow_null": True,
            },
            "metric_quality": {"help_text": "Always 'precise' — computed directly from CI run records."},
        }


class TimeToMergeRowSerializer(DataclassSerializer):
    class Meta:
        dataclass = TimeToMergeRow
        extra_kwargs = {
            "bucket": {"help_text": "'all', or an author handle when grouping by author."},
            "bucket_kind": {"help_text": "Whether this row aggregates all PRs ('all') or one author ('author')."},
            "pr_count": {"help_text": "Number of merged pull requests in the bucket."},
            "median_seconds": {"help_text": "Median seconds from PR open to merge."},
            "p95_seconds": {"help_text": "95th-percentile seconds from PR open to merge."},
        }


class TimeToMergeSerializer(DataclassSerializer):
    rows = TimeToMergeRowSerializer(
        many=True, help_text="One row for 'all', or one per author when grouping by author."
    )
    repo = RepoRefSerializer(
        allow_null=True,
        required=False,
        help_text="Repository the result is labeled with, if a repo filter was supplied.",
    )

    class Meta:
        dataclass = TimeToMerge
        extra_kwargs = {
            "date_from": {"help_text": "Start of the window, echoed from the request (relative string or ISO8601)."},
            "date_to": {
                "help_text": "End of the window, echoed from the request; null means 'now'.",
                "allow_null": True,
            },
            "group_by_author": {"help_text": "Whether rows are split per author."},
            "metric_quality": {
                "help_text": "Always 'coarse' — measures PR open to merge, combining draft and ready-for-review time.",
            },
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
