"""
DRF serializers for githog.
"""

from rest_framework import serializers


class GitHogRepositorySerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="GitHub repository ID.")
    name = serializers.CharField(help_text="Repository name without owner.")
    full_name = serializers.CharField(help_text="Repository full name in owner/name format.")
    owner = serializers.CharField(help_text="Repository owner login.")
    integration_id = serializers.IntegerField(help_text="PostHog integration ID for this repository.")


class GitHogRepositoryListResponseSerializer(serializers.Serializer):
    repositories = GitHogRepositorySerializer(many=True, help_text="Connected repositories.")


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
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    state = serializers.ChoiceField(
        choices=["open", "closed", "all"],
        default="open",
        required=False,
        help_text="Pull request state to filter by.",
    )


class GitHogPullRequestListResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    pull_requests = GitHogPullRequestSerializer(many=True, help_text="Pull requests matching the filter.")


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
    label = serializers.CharField(help_text="Short human title for the step.")  # type: ignore[assignment]
    file = serializers.CharField(allow_blank=True, help_text="Relative file path this node lives in, or empty.")
    detail = serializers.CharField(allow_blank=True, help_text="One sentence describing what happens at this node.")
    kind = serializers.CharField(help_text="entry | step | side_effect | return.")


class GitHogFlowEdgeSerializer(serializers.Serializer):
    source = serializers.CharField(help_text="Source FlowNode.id.")  # type: ignore[assignment]
    target = serializers.CharField(help_text="Target FlowNode.id.")
    label = serializers.CharField(allow_blank=True, help_text="Optional edge label.")  # type: ignore[assignment]


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
    label = serializers.CharField(help_text="Human-readable factor name.")  # type: ignore[assignment]
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


class GitHogConversationMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Message ID.")
    author_name = serializers.CharField(help_text="Display name of the message author.")
    author_email = serializers.CharField(help_text="Email of the message author.")
    body = serializers.CharField(help_text="Message body text.")
    created_at = serializers.DateTimeField(help_text="When the message was posted.")


class GitHogConversationListQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/name format.")
    number = serializers.IntegerField(help_text="Pull request number.")


class GitHogConversationListResponseSerializer(serializers.Serializer):
    messages = GitHogConversationMessageSerializer(many=True, help_text="Conversation messages in chronological order.")


class GitHogCreateMessageSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/name format.")
    number = serializers.IntegerField(help_text="Pull request number.")
    body = serializers.CharField(help_text="Message body text.")


class GitHogCreateMessageResponseSerializer(serializers.Serializer):
    message = GitHogConversationMessageSerializer(help_text="The newly created message.")
