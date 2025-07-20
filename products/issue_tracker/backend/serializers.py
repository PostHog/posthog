from rest_framework import serializers
from .models import Issue, GitHubIntegration


class IssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Issue
        fields = [
            "id",
            "title",
            "description",
            "status",
            "origin_product",
            "position",
            "github_branch",
            "github_pr_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "github_branch", "github_pr_url"]

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class GitHubIntegrationSerializer(serializers.ModelSerializer):
    github_token = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = GitHubIntegration
        fields = [
            "id",
            "repo_url",
            "repo_owner",
            "repo_name",
            "default_branch",
            "branch_prefix",
            "auto_create_pr",
            "github_token",
            "github_app_installation_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)

    def validate_repo_url(self, value):
        """Validate and parse GitHub repo URL"""
        import re
        pattern = r'https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
        match = re.match(pattern, value)
        if not match:
            raise serializers.ValidationError(
                "Invalid GitHub URL. Expected format: https://github.com/owner/repo"
            )
        return value

    def validate(self, attrs):
        """Extract owner/repo from URL and validate consistency"""
        if 'repo_url' in attrs:
            import re
            pattern = r'https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
            match = re.match(pattern, attrs['repo_url'])
            if match:
                url_owner, url_repo = match.groups()

                # Auto-populate owner/repo if not provided
                if 'repo_owner' not in attrs:
                    attrs['repo_owner'] = url_owner
                if 'repo_name' not in attrs:
                    attrs['repo_name'] = url_repo

                # Validate consistency if provided
                if attrs.get('repo_owner') != url_owner:
                    raise serializers.ValidationError(
                        f"Repo owner '{attrs['repo_owner']}' doesn't match URL owner '{url_owner}'"
                    )
                if attrs.get('repo_name') != url_repo:
                    raise serializers.ValidationError(
                        f"Repo name '{attrs['repo_name']}' doesn't match URL repo '{url_repo}'"
                    )

        return attrs
