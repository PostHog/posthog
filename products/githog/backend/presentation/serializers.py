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
    url = serializers.CharField(help_text="GitHub URL for this pull request.")
    state = serializers.CharField(help_text="Pull request state: open or closed.")
    head_branch = serializers.CharField(help_text="Source branch name.")
    base_branch = serializers.CharField(help_text="Target branch name.")
    created_at = serializers.CharField(help_text="ISO 8601 creation timestamp.")
    updated_at = serializers.CharField(help_text="ISO 8601 last-updated timestamp.")


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


class GitHogConversationMessageSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Message ID.")
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
