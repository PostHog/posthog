"""Payloads for the DORA deploy-metrics read."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    DeploymentFrequencyBucket,
    DoraOverview,
    MergeToDeployBucket,
)


class DeploymentFrequencyBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = DeploymentFrequencyBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to series_granularity (top of hour, midnight, or Monday)."
            },
            "deployment_count": {
                "help_text": "Deployments whose first success status landed in this bucket, within the "
                "environment scope. Zero-filled: 0 means nothing shipped."
            },
        }


class MergeToDeployBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = MergeToDeployBucket
        extra_kwargs = {
            "bucket_start": {
                "help_text": "Bucket start, aligned to series_granularity (top of hour, midnight, or Monday). "
                "Keyed on deploy time: a PR lands in the bucket its first post-merge deploy succeeded in."
            },
            "deployed_pr_count": {
                "help_text": "PRs whose first post-merge successful deployment landed in this bucket "
                "(bots and drafts excluded; narrowed by github_team when given)."
            },
            "min_seconds": {
                "help_text": "Fastest merge-to-deploy in this bucket, in seconds. Null when nothing deployed.",
                "allow_null": True,
            },
            "p25_seconds": {
                "help_text": "25th percentile merge-to-deploy seconds. Null when nothing deployed.",
                "allow_null": True,
            },
            "p50_seconds": {
                "help_text": "Median merge-to-deploy seconds. Null when nothing deployed.",
                "allow_null": True,
            },
            "mean_seconds": {
                "help_text": "Mean merge-to-deploy seconds. Null when nothing deployed.",
                "allow_null": True,
            },
            "p75_seconds": {
                "help_text": "75th percentile merge-to-deploy seconds. Null when nothing deployed.",
                "allow_null": True,
            },
            "max_seconds": {
                "help_text": "Slowest merge-to-deploy in this bucket, in seconds. Null when nothing deployed.",
                "allow_null": True,
            },
        }


class DoraOverviewSerializer(DataclassSerializer):
    deployment_frequency_series = DeploymentFrequencyBucketSerializer(
        many=True,
        help_text="Successful deployments per bucket across the window, oldest first, zero-filled, "
        "bucketed by series_granularity. Empty when the deploy tables aren't synced.",
    )
    merge_to_deploy_series = MergeToDeployBucketSerializer(
        many=True,
        help_text="Merge-to-deploy distribution per bucket across the window, oldest first — the box-plot "
        "series (min/p25/p50/mean/p75/max seconds per bucket). Empty when the deploy tables aren't synced, "
        "or when github_team was passed without membership data synced.",
    )

    class Meta:
        dataclass = DoraOverview
        extra_kwargs = {
            "deploy_data_available": {
                "help_text": "False when the deployments/deployment_statuses tables aren't synced for the "
                "selected repo; every other field is then empty or null, never a fake zero."
            },
            "environment_scope": {
                "help_text": "What the environment filter resolved to: 'production' (deployments GitHub marks "
                "production_environment), an exact environment name (the one passed, or the busiest persistent "
                "environment when nothing is marked production), or 'persistent' (no persistent environment "
                "deployed in the window, so every non-transient one counts). Transient environments (ephemeral "
                "per-PR previews) never join a default scope. The scope resolves from deployments in the scan "
                "window, so two different windows can resolve different scopes and are not always comparable."
            },
            "environments": {
                "help_text": "Distinct persistent environments deployed to in the scan window, most-deployed "
                "first — the environment picker's options. Transient environments are omitted but stay "
                "reachable by exact name."
            },
            "has_membership_data": {
                "help_text": "True when the optional team-membership snapshot is synced. When false, a "
                "github_team filter cannot be honored and the merge-to-deploy figures go empty rather than "
                "silently unfiltered."
            },
            "github_teams": {
                "help_text": "Distinct GitHub team slugs from the membership snapshot, sorted — the team "
                "picker's options. Empty when membership isn't synced."
            },
            "deployment_count": {
                "help_text": "Deployments whose first success status landed in the window, within the "
                "environment scope."
            },
            "deployment_count_prev": {"help_text": "Same count over the equal-length window before date_from."},
            "deployments_per_day": {
                "help_text": "deployment_count normalized by the window length in days. Null only when the deploy tables aren't synced.",
                "allow_null": True,
            },
            "deployments_per_day_prev": {
                "help_text": "Previous-window twin of deployments_per_day. Null only when the deploy tables aren't synced.",
                "allow_null": True,
            },
            "median_merge_to_deploy_seconds": {
                "help_text": "Median seconds from a PR's merge to the first successful deployment containing "
                "it (bots/drafts excluded; narrowed by github_team when given). Containment is resolved "
                "through the deploy's head commit, not the deploy's success time. Keyed on deploy time. This "
                "is merge-to-deploy, not full commit-to-deploy DORA lead time. Null when nothing deployed in "
                "the window.",
                "allow_null": True,
            },
            "median_merge_to_deploy_seconds_prev": {
                "help_text": "Previous-window twin of median_merge_to_deploy_seconds.",
                "allow_null": True,
            },
            "deployed_pr_count": {
                "help_text": "PRs first deployed in the window — the population behind the merge-to-deploy "
                "median and box plot."
            },
            "deployed_pr_count_prev": {"help_text": "Previous-window twin of deployed_pr_count."},
            "failed_deployment_count": {
                "help_text": "Deployments with at least one failure/error status, keyed on the first failure time."
            },
            "failed_deployment_count_prev": {"help_text": "Previous-window twin of failed_deployment_count."},
            "failed_deployment_share": {
                "help_text": "Failed deployments over deployments that reached any outcome (success or "
                "failure). A change-failure proxy: no incident data is linked, so a deploy that succeeded but "
                "broke production is not counted. Null when nothing reached an outcome.",
                "allow_null": True,
            },
            "failed_deployment_share_prev": {
                "help_text": "Previous-window twin of failed_deployment_share.",
                "allow_null": True,
            },
            "median_failed_deploy_to_next_success_seconds": {
                "help_text": "Median seconds from a deployment's first failure status to the next successful "
                "deployment in the same environment. A time-to-restore proxy: recovery by anything other than "
                "a deploy is invisible, and failures not yet recovered are excluded. Null when no failed "
                "deploy recovered in the window.",
                "allow_null": True,
            },
            "median_failed_deploy_to_next_success_seconds_prev": {
                "help_text": "Previous-window twin of median_failed_deploy_to_next_success_seconds.",
                "allow_null": True,
            },
            "merged_pr_count": {
                "help_text": "PRs merged in the window (bots and drafts excluded; narrowed by github_team "
                "when given) — the denominator behind unattributed_merged_pr_share."
            },
            "unattributed_merged_pr_share": {
                "help_text": "Share of merged_pr_count no successful in-scope deployment attributed: recent "
                "merges still waiting for their deploy, plus merges whose deploy the scope or scan bounds "
                "miss. Null when nothing merged in the window.",
                "allow_null": True,
            },
            "latest_deploy_status_at": {
                "help_text": "The newest deployment status row synced, any environment — how fresh the deploy "
                "data is. Windows ending after this instant undercount. Null when the deploy tables are empty.",
                "allow_null": True,
            },
            "series_granularity": {
                "help_text": "Bucket width of both series, chosen to fit the window: 'hour', 'day', or 'week'."
            },
        }
