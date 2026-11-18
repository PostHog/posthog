from rest_framework import serializers


class TaskReviewQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, max_value=100, default=1, help_text="Page of changed files.")


class TaskReviewFileSerializer(serializers.Serializer):
    filename = serializers.CharField(help_text="Repository-relative path.")
    status = serializers.CharField(help_text="Change type reported by GitHub.")
    additions = serializers.IntegerField(help_text="Added lines.")
    deletions = serializers.IntegerField(help_text="Removed lines.")
    patch = serializers.CharField(allow_blank=True, help_text="Unified diff, limited to 20,000 characters per file.")
    truncated = serializers.BooleanField(help_text="Open GitHub to read the complete or binary change.")


class TaskReviewSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="GitHub pull request URL.")
    title = serializers.CharField(help_text="Pull request title.")
    state = serializers.CharField(help_text="Pull request state.")
    ci_status = serializers.CharField(help_text="Combined check result.")
    head_sha = serializers.CharField(help_text="Head commit used for the check result.")
    files = TaskReviewFileSerializer(many=True, help_text="Changed files on this page.")
    has_more = serializers.BooleanField(help_text="Whether another file page is available.")
