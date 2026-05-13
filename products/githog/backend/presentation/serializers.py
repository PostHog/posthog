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
    repository = serializers.CharField(help_text="Repository in owner/repo format")
    number = serializers.IntegerField(help_text="Pull request number")


class GitHogPullRequestFileSerializer(serializers.Serializer):
    filename = serializers.CharField()
    status = serializers.CharField()
    additions = serializers.IntegerField()
    deletions = serializers.IntegerField()
    changes = serializers.IntegerField()
    patch = serializers.CharField(allow_null=True, allow_blank=True, required=False)


class GitHogPullRequestDetailSerializer(serializers.Serializer):
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


class GitHogPullRequestDetailResponseSerializer(serializers.Serializer):
    repository = serializers.CharField()
    pull_request = GitHogPullRequestDetailSerializer()
    files = GitHogPullRequestFileSerializer(many=True)
    diff = serializers.CharField(allow_null=True, allow_blank=True)
