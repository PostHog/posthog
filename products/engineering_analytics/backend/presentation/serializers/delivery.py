"""Payloads for the delivery reads: a scope's delivery summary and its pull request timelines."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryLeadTime,
    DeliverySummary,
    DurationDistribution,
    PRTimeline,
    PRTimelinePush,
    PRTimelineSegment,
    PullRequestTimelines,
    ScopeRepoDistribution,
    ScopeRepoFigure,
)
from products.engineering_analytics.backend.presentation.serializers._shared import RepoRefSerializer

_SCOPE_KIND_HELP = (
    "What the read covers: 'author' (one GitHub login), 'github_team' (the members of one GitHub team, "
    "through the team membership table), or 'pull_request' (one pull request)."
)


class ScopeRepoFigureSerializer(DataclassSerializer):
    class Meta:
        dataclass = ScopeRepoFigure
        extra_kwargs = {
            "scope": {
                "help_text": "The figure over the pull requests in scope. Null when the scope has nothing to measure.",
                "allow_null": True,
            },
            "repo": {
                "help_text": "The same figure over every non-bot pull request in the repository, the scope "
                "included. Null when the repository has nothing to measure.",
                "allow_null": True,
            },
        }


def _figure(help_text: str) -> ScopeRepoFigureSerializer:
    return ScopeRepoFigureSerializer(help_text=help_text)


class DurationDistributionSerializer(DataclassSerializer):
    class Meta:
        dataclass = DurationDistribution
        extra_kwargs = {
            "pr_count": {"help_text": "Pull requests in the distribution. Every statistic is null when this is 0."},
            "min_seconds": {"help_text": "Fastest duration, in seconds.", "allow_null": True},
            "p05_seconds": {"help_text": "5th percentile, in seconds: the lower whisker.", "allow_null": True},
            "p25_seconds": {"help_text": "25th percentile, in seconds: the box's lower edge.", "allow_null": True},
            "p50_seconds": {"help_text": "Median, in seconds.", "allow_null": True},
            "mean_seconds": {"help_text": "Mean, in seconds.", "allow_null": True},
            "p75_seconds": {"help_text": "75th percentile, in seconds: the box's upper edge.", "allow_null": True},
            "p95_seconds": {"help_text": "95th percentile, in seconds: the upper whisker.", "allow_null": True},
            "max_seconds": {"help_text": "Slowest duration, in seconds.", "allow_null": True},
        }


class ScopeRepoDistributionSerializer(DataclassSerializer):
    scope = DurationDistributionSerializer(help_text="The deployed pull requests in scope.")
    repo = DurationDistributionSerializer(help_text="Every deployed pull request in the repository.")

    class Meta:
        dataclass = ScopeRepoDistribution


class DeliveryLeadTimeSerializer(DataclassSerializer):
    open_to_deploy = ScopeRepoDistributionSerializer(
        help_text="Open to the first successful deploy containing the merge, over PRs deployed in the window."
    )
    open_to_merge = ScopeRepoDistributionSerializer(
        help_text="Open to merge over the same deployed PRs, so it composes with merge_to_deploy. Includes draft time."
    )
    merge_to_deploy = ScopeRepoDistributionSerializer(help_text="Merge to deploy over the same deployed PRs.")

    class Meta:
        dataclass = DeliveryLeadTime
        extra_kwargs = {
            "deploy_data_available": {
                "help_text": "False when the deployments and deployment statuses tables aren't synced. The "
                "distributions are then empty."
            },
            "environment_scope": {
                "help_text": "The deploy environments lead time was scoped to: production by default. Empty "
                "when deploy data is not available."
            },
            "merged_pr_count": {"help_text": "PRs in scope merged in the window (bots and drafts excluded)."},
            "deployed_merged_pr_count": {
                "help_text": "Of merged_pr_count, the PRs a successful in-scope deploy contains. The rest are "
                "still waiting for a deploy or fall outside the scan."
            },
        }


class DeliverySummarySerializer(DataclassSerializer):
    cost_per_merged_pr_usd = _figure(
        "Median estimated CI cost per merged PR, in USD, over every run linked to the PR (merge-queue gate runs "
        "included) that started up to 30 days before the window. Null when the jobs table isn't synced."
    )
    billable_minutes_per_merged_pr = _figure(
        "Median billable runner minutes per merged PR, on the billed clock. Null when the jobs table isn't synced."
    )
    cost_per_push_usd = _figure(
        "Total CI cost divided by total pushes over the merged PRs: the price of one iteration. A push is a "
        "distinct head commit that triggered CI."
    )
    median_ready_to_merge_seconds = _figure(
        "Median seconds from the last ready_for_review to merge. Null when issue events aren't synced."
    )
    p90_ready_to_merge_seconds = _figure("90th percentile of the ready-to-merge seconds.")
    median_ready_to_first_approval_seconds = _figure(
        "Median seconds from ready to the first approval. An approval given while the PR was a draft counts "
        "as 0. PRs merged without an approval are left out. Null when reviews aren't synced."
    )
    median_first_approval_to_merge_seconds = _figure(
        "Median seconds from the first approval to merge. This median and the one before it do not add up to "
        "the ready-to-merge median."
    )
    before_first_approval_share = _figure(
        "Share (0 to 1) of all ready-to-merge hours spent before the first approval, summed over the PRs, so "
        "long PRs weigh more. The rest came after the approval."
    )
    pushes_after_approval_per_merged_pr = _figure(
        "Mean pushes after the first approval per merged PR, over PRs with an approval."
    )
    merge_queue_attempts_per_merged_pr = _figure(
        "Mean merge-queue gate attempts per merged PR that went through the queue. A bisection probe folds "
        "into its attempt."
    )
    failed_merge_queue_share = _figure(
        "Share (0 to 1) of queue-landed merged PRs with at least one failed gate attempt. A failure caused by "
        "another PR ahead in the queue also counts, because the queue history is not in the warehouse."
    )
    lead_time = DeliveryLeadTimeSerializer(help_text="Lead time to deploy for the scope against the repository.")

    class Meta:
        dataclass = DeliverySummary
        extra_kwargs = {
            "scope_kind": {"help_text": _SCOPE_KIND_HELP},
            "scope": {"help_text": "The GitHub login or GitHub team slug the summary is for."},
            "has_membership_data": {
                "help_text": "True when the team membership table is synced. A github_team scope without it "
                "matches no pull requests, so every scope figure is empty rather than the whole repository."
            },
            "jobs_available": {"help_text": "True when the workflow jobs table is synced, which cost needs."},
            "review_data_available": {
                "help_text": "True when the reviews table is synced, which the approval split needs."
            },
            "ready_data_available": {
                "help_text": "True when issue events are synced, which ready-to-merge time needs."
            },
            "opened_pr_count": {"help_text": "PRs in scope opened in the window, drafts included, bots excluded."},
            "merged_pr_count": {
                "help_text": "PRs in scope merged in the window (bots and drafts excluded): the population of every "
                "per-merged-PR figure."
            },
            "open_pr_count": {"help_text": "PRs in scope that are open and not drafts right now. Ignores the window."},
            "draft_pr_count": {"help_text": "PRs in scope that are open drafts right now. Ignores the window."},
            "total_cost_usd": {
                "help_text": "Estimated CI cost summed over the merged PRs in scope. Null when nothing was costable.",
                "allow_null": True,
            },
            "total_billable_minutes": {
                "help_text": "Billable minutes summed over the merged PRs in scope. Null when the jobs table isn't "
                "synced.",
                "allow_null": True,
            },
            "push_count": {"help_text": "Pushes summed over the merged PRs in scope."},
        }


class PRTimelineSegmentSerializer(DataclassSerializer):
    class Meta:
        dataclass = PRTimelineSegment
        extra_kwargs = {
            "kind": {
                "help_text": "What the PR waited on: draft; waiting_for_review (no approval yet, or re-review "
                "after a push); changes_requested (no push since); approved_not_enqueued (approved, with no failing or running check); "
                "review_state_unknown (reviews not synced); ci_running; red_passed_on_rerun (the failed "
                "workflows passed a re-run of the same commit); red_master_broken (the failed jobs also failed "
                "on the default branch within 12 hours); red_fixed_by_push (a later commit arrived); "
                "red_not_provable; merge_queue (every queue state collapsed); out_of_merge_queue (open PR, "
                "Trunk says failed or cancelled)."
            },
            "started_at": {"help_text": "Segment start."},
            "ended_at": {"help_text": "Segment end: the next segment's start, the merge or close, or now."},
        }


class PRTimelinePushSerializer(DataclassSerializer):
    class Meta:
        dataclass = PRTimelinePush
        extra_kwargs = {
            "head_sha": {"help_text": "The pushed head commit."},
            "pushed_at": {
                "help_text": "When the commit's first workflow run was created, which is when the commit arrived."
            },
        }


class PRTimelineSerializer(DataclassSerializer):
    repo = RepoRefSerializer(help_text="The repository the pull request belongs to.")
    pushes = PRTimelinePushSerializer(
        many=True,
        help_text="Distinct head commits that triggered CI, oldest first, merge-queue gate runs excluded. A PR "
        "listed for an author or a team misses pushes from more than 30 days before the window.",
    )
    segments = PRTimelineSegmentSerializer(
        many=True, help_text="Consecutive segments from started_at to the merge, the close, or now, with no gaps."
    )

    class Meta:
        dataclass = PRTimeline
        extra_kwargs = {
            "number": {"help_text": "Pull request number."},
            "title": {"help_text": "Pull request title."},
            "author": {"help_text": "The pull request's author."},
            "state": {
                "help_text": "open, merged, or closed. Author and team scopes list open and merged PRs only; a "
                "pull_request scope returns the PR whatever its state."
            },
            "is_draft": {"help_text": "True when the PR is a draft right now."},
            "created_at": {"help_text": "When the PR was opened."},
            "started_at": {
                "help_text": "Where the timeline starts: the last ready_for_review before the end, else created_at. A PR listed for an author or a team starts no earlier than 30 days before the window, because older CI is not read."
            },
            "merged_at": {"help_text": "Merge time; null when not merged.", "allow_null": True},
            "estimated_cost_usd": {
                "help_text": "Estimated CI cost over the PR's runs, in USD. Null when nothing was costable.",
                "allow_null": True,
            },
            "billable_minutes": {
                "help_text": "Billable minutes over the PR's runs. Null when the jobs table isn't synced.",
                "allow_null": True,
            },
        }


class PullRequestTimelinesSerializer(DataclassSerializer):
    items = PRTimelineSerializer(
        many=True,
        help_text="The pull requests in scope, newest first: open PRs plus PRs merged in the window, or the one "
        "pull request of a pull_request scope.",
    )

    class Meta:
        dataclass = PullRequestTimelines
        extra_kwargs = {
            "scope_kind": {"help_text": _SCOPE_KIND_HELP},
            "scope": {"help_text": "The GitHub login, GitHub team slug, or 'owner/name#number' the timelines are for."},
            "has_membership_data": {
                "help_text": "True when the team membership table is synced. A github_team scope without it lists "
                "no pull requests."
            },
            "review_data_available": {
                "help_text": "False when reviews aren't synced: review stretches read review_state_unknown."
            },
            "jobs_available": {
                "help_text": "False when workflow jobs aren't synced: a check a re-run turned green is not "
                "visible, and no red stretch reads red_master_broken."
            },
            "merge_queue_state_available": {
                "help_text": "True when the Trunk merge-queue table is synced, so out_of_merge_queue can appear."
            },
            "generated_at": {"help_text": "The now every open PR's timeline ends at."},
            "truncated": {"help_text": "True when more PRs matched than the limit."},
            "limit": {"help_text": "The maximum number of PRs returned."},
        }
