from rest_framework import serializers
from posthog.models.integration import Integration
from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    # Computed fields for repository information
    repository_list = serializers.SerializerMethodField()
    primary_repository = serializers.SerializerMethodField()
    
    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "status",
            "origin_product",
            "position",
            # Repository fields
            "github_integration",
            "repository_config",
            # Computed fields
            "repository_list",
            "primary_repository",
            # Legacy GitHub fields
            "github_branch",
            "github_pr_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", 
            "created_at", 
            "updated_at", 
            "github_branch", 
            "github_pr_url",
            "repository_list",
            "primary_repository"
        ]

    def get_repository_list(self, obj):
        """Get the list of repositories this task can work with"""
        return obj.repository_list
    
    def get_primary_repository(self, obj):
        """Get the primary repository for this task"""
        return obj.primary_repository
    
    def validate_github_integration(self, value):
        """Validate that the GitHub integration belongs to the same team"""
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Integration must belong to the same team")
        return value
    
    def validate_repository_config(self, value):
        """Validate repository configuration"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Repository config must be a dictionary")
        
        # If repository_config is empty, that's fine for new tasks
        if not value:
            return value
        
        # If organization is provided, repository must also be provided (and vice versa)
        has_org = bool(value.get("organization"))
        has_repo = bool(value.get("repository"))
        
        if has_org and not has_repo:
            raise serializers.ValidationError("'repository' is required when 'organization' is specified")
        if has_repo and not has_org:
            raise serializers.ValidationError("'organization' is required when 'repository' is specified")
        
        return value
    
    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        
        # Set default GitHub integration if not provided
        if not validated_data.get("github_integration"):
            default_integration = Integration.objects.filter(
                team=self.context["team"],
                kind="github"
            ).first()
            if default_integration:
                validated_data["github_integration"] = default_integration
        
        return super().create(validated_data)


class RepositoryConfigSerializer(serializers.Serializer):
    """Serializer for repository configuration"""
    
    integration_id = serializers.IntegerField(required=False)
    organization = serializers.CharField(max_length=255)
    repository = serializers.CharField(max_length=255)
    
    def validate_integration_id(self, value):
        """Validate that the integration exists and is a GitHub integration"""
        if value:
            try:
                integration = Integration.objects.get(id=value, kind="github")
                if "team" in self.context and integration.team_id != self.context["team"].id:
                    raise serializers.ValidationError("Integration must belong to the same team")
                return value
            except Integration.DoesNotExist:
                raise serializers.ValidationError("GitHub integration not found")
        return value
