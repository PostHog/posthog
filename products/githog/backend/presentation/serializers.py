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


class GitHogPullRequestDiffQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/name format.")
    pr_number = serializers.IntegerField(help_text="Pull request number within the repository.", min_value=1)


class GitHogPullRequestDiffResponseSerializer(serializers.Serializer):
    repository = serializers.CharField()
    pr_number = serializers.IntegerField()
    diff = serializers.CharField(help_text="Raw unified diff as returned by the GitHub API.")


# --- PR impact analysis ---------------------------------------------------


class PRImpactRequestSerializer(serializers.Serializer):
    """Input for POST /githog/impact/pr_impact."""

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
        help_text="How many days of events ($feature_flag_called and direct capture calls) to use when measuring reach.",
        required=False,
        default=30,
        min_value=1,
        max_value=365,
    )


class PRImpactFromPRRequestSerializer(serializers.Serializer):
    """Input for POST /githog/impact/from_pr.

    Fetches the PR's unified diff via the team's GitHub integration, then runs
    the standard impact analysis. Convenience wrapper over ``/pr_impact`` —
    saves the caller from having to fetch and paste the diff themselves.
    """

    repository = serializers.CharField(
        help_text="Repository in owner/name format (e.g. PostHog/posthog).",
        required=True,
    )
    pr_number = serializers.IntegerField(
        help_text="Pull request number within the repository.",
        required=True,
        min_value=1,
    )
    lookback_days = serializers.IntegerField(
        help_text="How many days of events ($feature_flag_called and direct capture calls) to use when measuring reach.",
        required=False,
        default=30,
        min_value=1,
        max_value=365,
    )
    refresh = serializers.BooleanField(
        help_text=(
            "When true, bypasses the cached blast-radius result and recomputes from scratch "
            "(including the LLM call). Use after pushing new commits or to force a re-run."
        ),
        required=False,
        default=False,
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
    is_server_side = serializers.BooleanField(
        help_text=(
            "True when the evaluation pattern looks server-side (one service identity per many calls). "
            "In that case `users_affected` is the count of service identities, not humans — `call_count` is the meaningful number."
        )
    )


class _EventReferenceResponseSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event name captured in the diff.")
    file_paths = serializers.ListField(
        child=serializers.CharField(),
        help_text="Files in the diff where this event name was referenced.",
    )
    occurrences = serializers.IntegerField(help_text="Total times the event was referenced across added lines.")


class _EventReachResponseSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Event name whose reach was measured.")
    users_affected = serializers.IntegerField(help_text="Distinct persons who fired the event in the window.")
    sessions_affected = serializers.IntegerField(help_text="Distinct sessions in which the event fired in the window.")
    call_count = serializers.IntegerField(help_text="Total times the event fired in the window.")
    has_data = serializers.BooleanField(
        help_text="False when the event had no activity in the window — reach is unknown, not zero."
    )
    is_server_side = serializers.BooleanField(
        help_text=(
            "True when the capture pattern looks server-side (one service identity per many fires). "
            "In that case `users_affected` is the count of service identities, not humans — `call_count` is the meaningful number."
        )
    )


class _LLMPickResponseSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["flag", "event", "dashboard", "issue"],
        help_text="Which kind of signal this pick refers to.",
    )
    key = serializers.CharField(help_text="Flag key / event name / dashboard name / issue name.")
    reason = serializers.CharField(help_text="The model's justification, ideally citing real numbers.")


class _AffectedEstimateResponseSerializer(serializers.Serializer):
    headline = serializers.CharField(
        help_text="Glanceable phrase: 'Most users', '~14k users', 'iOS users only', etc. Under 5 words."
    )
    unit = serializers.ChoiceField(
        choices=["users", "events", "requests", "unknown"],
        help_text="What the numeric range counts. 'users' = humans, 'events'/'requests' = server-side firehose.",
    )
    lower = serializers.IntegerField(
        allow_null=True, required=False, help_text="Lower bound of the numeric range; null when not estimable."
    )
    upper = serializers.IntegerField(
        allow_null=True, required=False, help_text="Upper bound of the numeric range; null when not estimable."
    )
    share_lower = serializers.FloatField(
        allow_null=True, required=False, help_text="Fraction of the active base (0.0-1.0), lower bound."
    )
    share_upper = serializers.FloatField(
        allow_null=True, required=False, help_text="Fraction of the active base (0.0-1.0), upper bound."
    )
    confidence = serializers.ChoiceField(
        choices=["high", "medium", "low"],
        help_text="Model's self-rated confidence. 'low' = inferred from diff alone without PostHog data.",
    )
    rationale = serializers.CharField(help_text="1-2 sentences explaining the estimate, citing numbers.")


class _LLMAnalysisResponseSerializer(serializers.Serializer):
    headline = serializers.CharField(help_text="One-sentence synopsis of the PR's blast radius.")
    summary = serializers.CharField(help_text="2-4 sentences elaborating on the headline.")
    affected = _AffectedEstimateResponseSerializer(
        allow_null=True,
        required=False,
        help_text="Glanceable answer to 'how many users will this affect' — surfaced as the loud metric.",
    )
    audience = serializers.ListField(
        child=serializers.CharField(),
        help_text="1-4 short phrases describing WHO is affected (platform, feature area, service).",
    )
    top_picks = _LLMPickResponseSerializer(
        many=True, help_text="Most important signals a reviewer should look at, in priority order."
    )
    caveats = serializers.ListField(
        child=serializers.CharField(),
        help_text="Model-flagged caveats (no recent data, server-side only, etc.).",
    )
    tool_calls_used = serializers.IntegerField(
        help_text="Total tool calls the orchestrator used. Useful for spotting runaway loops."
    )


class _RelatedSignalResponseSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["flag", "event"],
        help_text="Whether this related signal is a feature flag key or an event name.",
    )
    key = serializers.CharField(help_text="The flag key or event name.")
    matched_tokens = serializers.ListField(
        child=serializers.CharField(),
        help_text="Filename tokens from the diff that overlap this signal's name.",
    )
    users_affected = serializers.IntegerField(help_text="Distinct persons who hit this signal in the window.")
    sessions_affected = serializers.IntegerField(help_text="Distinct sessions in which the signal fired in the window.")
    call_count = serializers.IntegerField(help_text="Total evaluations or fires in the window.")
    is_server_side = serializers.BooleanField(
        help_text="True when the capture pattern looks server-side (many calls per identity)."
    )
    has_data = serializers.BooleanField(help_text="False when no activity was recorded in the window.")


class _IssueReferenceResponseSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="UUID of the Error Tracking issue.")
    name = serializers.CharField(help_text="Issue name; falls back to 'Untitled issue' if unset.")
    status = serializers.CharField(help_text="Issue status (active, resolved, archived, pending_release, suppressed).")
    occurrences = serializers.IntegerField(help_text="Number of $exception events in the lookback window.")
    users_affected = serializers.IntegerField(help_text="Distinct persons who hit this issue in the window.")
    sample_message = serializers.CharField(
        help_text="Truncated exception message from a representative event.", allow_blank=True
    )
    matched_terms = serializers.ListField(
        child=serializers.CharField(),
        help_text="File basenames or flag/event keys that caused this issue to surface.",
    )


class _DashboardReferenceResponseSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["insight", "dashboard"],
        help_text="Whether this reference is a saved insight or a dashboard containing matching insights.",
    )
    id = serializers.IntegerField(help_text="Database id of the insight or dashboard.")
    name = serializers.CharField(help_text="Display name; falls back to derived name or 'Untitled' when unset.")
    short_id = serializers.CharField(
        help_text="Short URL id for insights (None for dashboards).",
        allow_null=True,
        required=False,
    )
    matched_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="The flag keys or event names that caused this surface to match.",
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
    event_references = _EventReferenceResponseSerializer(
        many=True, help_text="Event names captured in the diff (e.g. `posthog.capture('...')`)."
    )
    per_event_reach = _EventReachResponseSerializer(
        many=True, help_text="Reach metrics per event name, computed independently."
    )
    dashboard_references = _DashboardReferenceResponseSerializer(
        many=True,
        help_text="Saved insights and dashboards that reference any matched flag key or event name.",
    )
    issue_references = _IssueReferenceResponseSerializer(
        many=True,
        help_text="Error Tracking issues whose recent $exception events mention touched files or matched keys.",
    )
    related_signals = _RelatedSignalResponseSerializer(
        many=True,
        help_text=(
            "Flag keys and event names that share filename tokens with this PR's files. "
            "Not literal references — surfaced as 'you may also care about these' suggestions."
        ),
    )
    changed_files = serializers.ListField(
        child=serializers.CharField(),
        help_text="Unique file paths with content visible in the diff. Useful for the empty-state UX.",
    )
    known_flag_count = serializers.IntegerField(
        help_text="How many of the team's flag keys were scanned for literal matches."
    )
    known_event_count = serializers.IntegerField(
        help_text="How many of the team's recent event names were scanned for literal matches."
    )
    llm_analysis = _LLMAnalysisResponseSerializer(
        allow_null=True,
        required=False,
        help_text="LLM synthesis of the blast radius — null when ANTHROPIC_API_KEY is missing or the call failed.",
    )
    notes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Caveats — unresolved constants, flags/events with no recorded activity, etc.",
    )

    @classmethod
    def from_report(cls, report: PRImpactReport) -> dict:
        """Render a PRImpactReport into a plain JSON-serializable dict."""
        return asdict(report)
