"""
DRF serializers for githog.
"""

from rest_framework import serializers


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


class GitHogPullRequestDetailQuerySerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    number = serializers.IntegerField(help_text="Pull request number.")


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
    title = serializers.CharField(help_text="Short imperative phrase for this step.")
    file = serializers.CharField(help_text="Relative file path this step lives in.", allow_blank=True)
    detail = serializers.CharField(help_text="One sentence describing what happens in this step.", allow_blank=True)


class GitHogDataFlowResponseSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository in owner/repo format.")
    pr_number = serializers.IntegerField(help_text="Pull request number.")
    head_sha = serializers.CharField(help_text="Commit SHA at the PR head when the flow was computed.")
    base_sha = serializers.CharField(help_text="Commit SHA at the PR base when the flow was computed.")
    mermaid_before = serializers.CharField(
        help_text="Mermaid sequenceDiagram representing the execution flow BEFORE the change.",
        allow_blank=True,
    )
    mermaid_after = serializers.CharField(
        help_text="Mermaid sequenceDiagram representing the execution flow AFTER the change.",
        allow_blank=True,
    )
    steps_before = GitHogDataFlowStepSerializer(many=True, help_text="Ordered execution-flow steps BEFORE the change.")
    steps_after = GitHogDataFlowStepSerializer(many=True, help_text="Ordered execution-flow steps AFTER the change.")
    summary = serializers.CharField(help_text="LLM-generated summary of how the flow changed.", allow_blank=True)
    truncated = serializers.BooleanField(help_text="True if file content was truncated for the LLM prompt.")
    cached = serializers.BooleanField(
        help_text="True if the response was served from cache (no LLM call this request)."
    )
    computed_at = serializers.DateTimeField(help_text="When this data-flow row was last (re)computed.")
