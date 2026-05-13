"""
DRF serializers for githog.

Two groups:

- GitHub integration views (``GitHogViewSet``): repository and pull-request
  listing schemas backed by the team's GitHub integration.
- PR impact analysis (``GithogPRImpactViewSet``): request/response shapes
  that wrap ``facade/contracts.py`` dataclasses.
"""

from dataclasses import asdict

from rest_framework import serializers

from ..facade.contracts import PRImpactReport


# --- GitHub integration views --------------------------------------------


class GitHogRepositorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    full_name = serializers.CharField()
    owner = serializers.CharField()
    integration_id = serializers.IntegerField()


class GitHogRepositoryListResponseSerializer(serializers.Serializer):
    repositories = GitHogRepositorySerializer(many=True)


class GitHogPullRequestSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    title = serializers.CharField()
    url = serializers.CharField()
    state = serializers.CharField()
    head_branch = serializers.CharField()
    base_branch = serializers.CharField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()


class GitHogPullRequestListQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format")
    state = serializers.ChoiceField(
        choices=["open", "closed", "all"],
        default="open",
        required=False,
        help_text="Pull request state to filter by.",
    )


class GitHogPullRequestListResponseSerializer(serializers.Serializer):
    repository = serializers.CharField()
    pull_requests = GitHogPullRequestSerializer(many=True)


# --- PR impact analysis ---------------------------------------------------


class PRImpactRequestSerializer(serializers.Serializer):
    """Input for POST /githog/pr_impact."""

    diff_text = serializers.CharField(
        help_text=(
            "Unified diff text (e.g. output of `git diff base...head` or the "
            "`patch` body from the GitHub Files API). Only added lines are scanned."
        ),
        required=True,
        allow_blank=False,
        trim_whitespace=False,
        style={"base_template": "textarea.html"},
    )
    lookback_days = serializers.IntegerField(
        help_text="How many days of $feature_flag_called events to use when measuring reach.",
        required=False,
        default=30,
        min_value=1,
        max_value=365,
    )


class _VariantReachResponseSerializer(serializers.Serializer):
    variant = serializers.CharField(help_text="Variant value as returned by feature flag evaluation.")
    users_affected = serializers.IntegerField(help_text="Distinct persons that evaluated to this variant.")


class _FlagReferenceResponseSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Flag key (or `const:<IDENTIFIER>` for unresolved constants).")
    file_paths = serializers.ListField(
        child=serializers.CharField(),
        help_text="Files in the diff where this flag was referenced.",
    )
    occurrences = serializers.IntegerField(help_text="Total times the flag was referenced across added lines.")


class _FlagReachResponseSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Flag key whose reach was measured.")
    users_affected = serializers.IntegerField(help_text="Distinct persons with a truthy evaluation in the window.")
    sessions_affected = serializers.IntegerField(help_text="Distinct sessions with a truthy evaluation in the window.")
    call_count = serializers.IntegerField(help_text="Total truthy evaluations in the window.")
    variants = _VariantReachResponseSerializer(many=True, help_text="Per-variant breakdown for multivariate flags.")
    has_data = serializers.BooleanField(
        help_text="False when the flag had no recorded evaluations in the window — reach is unknown, not zero."
    )


class PRImpactResponseSerializer(serializers.Serializer):
    """Response payload for POST /githog/pr_impact."""

    flag_references = _FlagReferenceResponseSerializer(many=True, help_text="Flag references extracted from the diff.")
    per_flag_reach = _FlagReachResponseSerializer(
        many=True, help_text="Reach metrics per flag, computed independently."
    )
    intersection_users = serializers.IntegerField(
        help_text=(
            "Distinct persons who evaluated EVERY referenced flag truthy in the window. "
            "This is the empirical 'users on this code path' number — defensible against "
            "compounding nested gates because it reads actual evaluations, not configured rollouts."
        ),
    )
    intersection_sessions = serializers.IntegerField(
        help_text="Sessions in which the full flag set was evaluated truthy."
    )
    lookback_days = serializers.IntegerField(help_text="Window used for reach computation.")
    notes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Caveats — unresolved constants, flags with no recorded evaluations, etc.",
    )

    @classmethod
    def from_report(cls, report: PRImpactReport) -> dict:
        """Render a PRImpactReport into a plain JSON-serializable dict."""
        return asdict(report)
