import re

from rest_framework import serializers

REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}")
GITHUB_BUSY = "GitHub is busy or unavailable, try again."


class GitHubBrandErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error category.")
    code = serializers.CharField(help_text="Machine-readable error code.")
    detail = serializers.CharField(help_text="Human-readable error description.")
    attr = serializers.CharField(allow_null=True, required=False, help_text="Invalid field, when applicable.")


class GitHubBrandRequestSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        min_value=1, help_text="GitHub integration in this environment that can read the repository."
    )
    repository = serializers.CharField(
        max_length=140, trim_whitespace=False, help_text="Repository to read, formatted as owner/repo."
    )

    def validate_repository(self, repository: str) -> str:
        if not REPOSITORY.fullmatch(repository):
            raise serializers.ValidationError("Enter the repository as owner/repo.")
        return repository


class GitHubBrandSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Repository the brand was detected from, formatted as owner/repo.")
    name = serializers.CharField(allow_null=True, help_text="Detected brand name, or null if none was found.")
    primary_color = serializers.CharField(
        allow_null=True, help_text="Detected primary color as #rrggbb, or null if none was found."
    )
    logo_url = serializers.URLField(
        allow_null=True, help_text="Public URL of the stored raster logo, or null if none was found."
    )
