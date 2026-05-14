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
    number = serializers.IntegerField(help_text="Pull request number.")
    title = serializers.CharField(help_text="Pull request title.")
    url = serializers.CharField(help_text="GitHub HTML URL for the PR.")
    state = serializers.CharField(help_text="PR state (open, closed).")
    head_branch = serializers.CharField(help_text="Source branch.")
    base_branch = serializers.CharField(help_text="Target branch.")
    created_at = serializers.CharField(help_text="ISO 8601 creation timestamp.")
    updated_at = serializers.CharField(help_text="ISO 8601 last-update timestamp.")
    draft = serializers.BooleanField(required=False, default=False, help_text="True if the PR is a draft.")
    author = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="GitHub login of the PR author."
    )
    author_avatar_url = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Avatar URL of the PR author."
    )


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
        choices=["flag", "event", "dashboard", "issue", "page"],
        help_text="Which kind of signal this pick refers to.",
    )
    key = serializers.CharField(help_text="Flag key / event name / dashboard name / issue name / URL path.")
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


class _WebPathReachResponseSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="URL path (matched against properties.$pathname).")
    pageviews = serializers.IntegerField(help_text="Total $pageview events on this path in the window.")
    unique_visitors = serializers.IntegerField(help_text="Distinct persons who viewed this path in the window.")
    sessions = serializers.IntegerField(help_text="Distinct sessions in which this path was viewed.")
    has_data = serializers.BooleanField(help_text="False when no pageviews were recorded for this path in the window.")
    matched_from = serializers.ChoiceField(
        choices=["diff_literal", "llm_tool"],
        help_text=(
            "How this path was identified: 'diff_literal' (regex match on string literals in the diff) "
            "or 'llm_tool' (model inferred it from framework conventions)."
        ),
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
    web_paths = _WebPathReachResponseSerializer(
        many=True,
        help_text=(
            "URL paths from the diff with pageview reach. Built from string literals found in "
            "added/context lines plus paths the LLM inferred from framework conventions."
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


# --- PR detail / diff / data flow / risk score / layout ------------------


class GitHogPullRequestDetailQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")


class GitHogPullRequestFileSerializer(serializers.Serializer):
    filename = serializers.CharField()
    status = serializers.CharField()
    additions = serializers.IntegerField()
    deletions = serializers.IntegerField()
    changes = serializers.IntegerField()
    patch = serializers.CharField(allow_null=True, allow_blank=True, required=False)


class GitHogPullRequestWithDiffSerializer(serializers.Serializer):
    """PR metadata returned alongside the unified diff for the agent chat widget.

    Distinct from the leaner ``GitHogPullRequestDetailResponseSerializer`` below,
    which is for the basic PR-detail panel and does not include files/diff.
    """

    number = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    url = serializers.CharField()
    state = serializers.CharField()
    draft = serializers.BooleanField()
    head_branch = serializers.CharField()
    head_sha = serializers.CharField()
    base_branch = serializers.CharField()
    base_sha = serializers.CharField()
    author = serializers.CharField(allow_blank=True)
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    additions = serializers.IntegerField()
    deletions = serializers.IntegerField()
    changed_files = serializers.IntegerField()
    commits = serializers.IntegerField()


class GitHogPullRequestDiffResponseSerializer(serializers.Serializer):
    """Response for the ``pull_request_diff`` endpoint: PR meta + files + unified diff."""

    repository = serializers.CharField()
    pull_request = GitHogPullRequestWithDiffSerializer()
    files = GitHogPullRequestFileSerializer(many=True)
    diff = serializers.CharField(allow_null=True, allow_blank=True)


class GitHogPullRequestDetailResponseSerializer(serializers.Serializer):
    number = serializers.IntegerField(help_text="Pull request number.")
    title = serializers.CharField(help_text="Pull request title.")
    body = serializers.CharField(allow_blank=True, help_text="Pull request description body.")
    state = serializers.CharField(help_text="Pull request state (open, closed).")
    draft = serializers.BooleanField(help_text="True if the PR is a draft.")
    html_url = serializers.CharField(help_text="Public GitHub URL of the PR.")
    author = serializers.CharField(allow_blank=True, help_text="GitHub login of the PR author.")
    author_avatar_url = serializers.CharField(allow_blank=True, help_text="Avatar URL of the PR author.")
    head_branch = serializers.CharField(help_text="Branch the PR is merging from.")
    base_branch = serializers.CharField(help_text="Branch the PR is merging into.")
    head_sha = serializers.CharField(help_text="Commit SHA at the head of the PR.")
    base_sha = serializers.CharField(help_text="Commit SHA at the base of the PR.")
    created_at = serializers.CharField(allow_blank=True, help_text="ISO 8601 creation timestamp.")
    updated_at = serializers.CharField(allow_blank=True, help_text="ISO 8601 last-update timestamp.")
    merged_at = serializers.CharField(
        allow_blank=True, allow_null=True, required=False, help_text="ISO 8601 merge timestamp, or null."
    )


class GitHogDataFlowQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")
    refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="If true, bypass cache and force a fresh LLM call.",
    )


class GitHogDataFlowStepSerializer(serializers.Serializer):
    id = serializers.CharField(allow_blank=True, help_text="Matches the corresponding FlowNode id in the graph.")
    title = serializers.CharField(help_text="Short imperative phrase for this step.")
    file = serializers.CharField(help_text="Relative file path this step lives in.", allow_blank=True)
    detail = serializers.CharField(help_text="One sentence describing what happens in this step.", allow_blank=True)


class GitHogFlowNodeSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable, slugified id reused across before/after for unchanged steps.")
    label = serializers.CharField(help_text="Short human title for the step.")
    file = serializers.CharField(allow_blank=True, help_text="Relative file path this node lives in, or empty.")
    detail = serializers.CharField(allow_blank=True, help_text="One sentence describing what happens at this node.")
    kind = serializers.CharField(help_text="entry | step | side_effect | return.")


class GitHogFlowEdgeSerializer(serializers.Serializer):
    source = serializers.CharField(help_text="Source FlowNode.id.")
    target = serializers.CharField(help_text="Target FlowNode.id.")
    label = serializers.CharField(allow_blank=True, help_text="Optional edge label.")


class GitHogFlowGraphSerializer(serializers.Serializer):
    nodes = GitHogFlowNodeSerializer(many=True, help_text="Graph nodes.")
    edges = GitHogFlowEdgeSerializer(many=True, help_text="Directed edges between nodes.")


class GitHogDataFlowResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    pr_number = serializers.IntegerField(help_text="Pull request number.")
    head_sha = serializers.CharField(help_text="Commit SHA at the PR head when the flow was computed.")
    base_sha = serializers.CharField(help_text="Commit SHA at the PR base when the flow was computed.")
    flow_before = GitHogFlowGraphSerializer(help_text="Execution-flow graph BEFORE the change.")
    flow_after = GitHogFlowGraphSerializer(help_text="Execution-flow graph AFTER the change.")
    steps_before = GitHogDataFlowStepSerializer(many=True, help_text="Ordered execution-flow steps BEFORE the change.")
    steps_after = GitHogDataFlowStepSerializer(many=True, help_text="Ordered execution-flow steps AFTER the change.")
    summary = serializers.CharField(help_text="LLM-generated summary of how the flow changed.", allow_blank=True)
    truncated = serializers.BooleanField(help_text="True if file content was truncated for the LLM prompt.")
    files_total = serializers.IntegerField(help_text="Number of files changed in the PR.")
    files_with_content = serializers.IntegerField(help_text="Number of files whose full content was sent to the LLM.")
    cached = serializers.BooleanField(
        help_text="True if the response was served from cache (no LLM call this request)."
    )
    computed_at = serializers.DateTimeField(help_text="When this data-flow row was last (re)computed.")


class GitHogRiskScoreQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")
    refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="If true, bypass cache and force a fresh computation.",
    )


class GitHogRiskScoreFactorSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier for this factor (e.g. 'diff_size').")
    label = serializers.CharField(help_text="Human-readable factor name.")
    score = serializers.IntegerField(
        min_value=0, max_value=100, help_text="Sub-score 0-100 contributed by this factor."
    )
    weight = serializers.FloatField(help_text="Relative weight of this factor in the composite score.")
    detail = serializers.CharField(allow_blank=True, help_text="One-line explanation of this factor's value.")


class GitHogRiskScoreResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    pr_number = serializers.IntegerField(help_text="Pull request number.")
    head_sha = serializers.CharField(help_text="Commit SHA at the PR head when the score was computed.")
    base_sha = serializers.CharField(help_text="Commit SHA at the PR base when the score was computed.")
    score = serializers.IntegerField(
        min_value=0, max_value=100, help_text="Composite risk score 0-100, higher is riskier."
    )
    level = serializers.ChoiceField(
        choices=["low", "moderate", "high", "critical"],
        help_text="Discrete risk level derived from the composite score.",
    )
    headline = serializers.CharField(allow_blank=True, help_text="One-line summary of the dominant risk.")
    rationale = serializers.CharField(allow_blank=True, help_text="2-3 sentence LLM rationale for the risk score.")
    factors = GitHogRiskScoreFactorSerializer(many=True, help_text="Per-factor breakdown of the composite score.")
    truncated = serializers.BooleanField(help_text="True if the diff was truncated when sent to the LLM.")
    cached = serializers.BooleanField(
        help_text="True if the response was served from cache (no LLM call this request)."
    )
    computed_at = serializers.CharField(
        allow_blank=True, help_text="ISO 8601 timestamp of when this score was computed (empty if not tracked)."
    )


class GitHogPullRequestLayoutItemSerializer(serializers.Serializer):
    i = serializers.CharField(help_text="Widget type identifier (acts as grid item key).")
    x = serializers.IntegerField(min_value=0, help_text="Grid column position (0-based).")
    y = serializers.IntegerField(min_value=0, help_text="Grid row position (0-based).")
    w = serializers.IntegerField(min_value=1, help_text="Width in grid columns.")
    h = serializers.IntegerField(min_value=1, help_text="Height in grid rows.")


class GitHogPullRequestLayoutQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")


class GitHogPullRequestLayoutRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")
    items = GitHogPullRequestLayoutItemSerializer(
        many=True, help_text="Ordered list of widgets with their grid positions and sizes."
    )


class GitHogPullRequestLayoutResponseSerializer(serializers.Serializer):
    repository = serializers.CharField()
    pr_number = serializers.IntegerField()
    items = GitHogPullRequestLayoutItemSerializer(many=True)
    exists = serializers.BooleanField(help_text="True if a saved layout was found; otherwise the default is returned.")


class GitHogPullRequestMessageSerializer(serializers.Serializer):
    """A single PR conversation message rendered for the client."""

    id = serializers.IntegerField(help_text="Server-assigned message id; stable across edits.")
    body = serializers.CharField(help_text="Markdown-flavored message body as authored by the user.")
    author_id = serializers.IntegerField(
        allow_null=True,
        help_text="User id of the author, or null if the author has been deleted.",
    )
    author_name = serializers.CharField(
        allow_blank=True,
        help_text="Display name of the author at send time; empty string if unknown.",
    )
    author_email = serializers.CharField(
        allow_blank=True,
        help_text="Email of the author at send time; empty string if unknown.",
    )
    is_mine = serializers.BooleanField(
        help_text="True if the requesting user authored this message (useful for client-side affordances).",
    )
    edited_at = serializers.DateTimeField(
        allow_null=True,
        help_text="ISO 8601 timestamp of the last edit, or null if never edited.",
    )
    created_at = serializers.DateTimeField(help_text="ISO 8601 timestamp when the message was created.")


class GitHogPullRequestMessageListQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")


class GitHogPullRequestMessageListResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    pr_number = serializers.IntegerField(help_text="Pull request number.")
    messages = GitHogPullRequestMessageSerializer(
        many=True,
        help_text="Conversation messages ordered by created_at ascending (oldest first).",
    )


class GitHogPullRequestMessageCreateRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")
    body = serializers.CharField(
        max_length=10_000,
        trim_whitespace=True,
        help_text="Message body (1-10000 chars after trimming).",
    )

    def validate_body(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Message body cannot be empty.")
        return value


class GitHogPullRequestMessageUpdateRequestSerializer(serializers.Serializer):
    body = serializers.CharField(
        max_length=10_000,
        trim_whitespace=True,
        help_text="New message body (1-10000 chars after trimming).",
    )

    def validate_body(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Message body cannot be empty.")
        return value
