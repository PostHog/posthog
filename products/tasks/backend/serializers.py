from rest_framework import serializers

from posthog.models.integration import Integration

from .models import AgentDefinition, Task, TaskWorkflow, WorkflowStage


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
            "origin_product",
            "position",
            # Workflow fields
            "workflow",
            "current_stage",
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
            "primary_repository",
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
            default_integration = Integration.objects.filter(team=self.context["team"], kind="github").first()
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


class WorkflowStageSerializer(serializers.ModelSerializer):
    """Serializer for workflow stages"""

    task_count = serializers.SerializerMethodField()
    agent_name = serializers.CharField(source="agent.name", read_only=True)

    class Meta:
        model = WorkflowStage
        fields = [
            "id",
            "workflow",
            "name",
            "key",
            "position",
            "color",
            "agent",
            "agent_name",
            "is_manual_only",
            "is_archived",
            "fallback_stage",
            "task_count",
        ]
        read_only_fields = ["id", "task_count", "agent_name"]

    def get_task_count(self, obj):
        """Get number of tasks currently in this stage"""
        return Task.objects.filter(current_stage=obj).count()

    def validate_workflow(self, value):
        """Validate that the workflow exists and belongs to the current team"""
        if "team" in self.context and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Workflow must belong to the same team")
        return value


class AgentDefinitionSerializer(serializers.ModelSerializer):
    """Serializer for agent definitions"""

    class Meta:
        model = AgentDefinition
        fields = ["id", "name", "agent_type", "description", "config", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class TaskWorkflowSerializer(serializers.ModelSerializer):
    """Serializer for task workflows"""

    stages = WorkflowStageSerializer(many=True, read_only=True)
    task_count = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = TaskWorkflow
        fields = [
            "id",
            "name",
            "description",
            "color",
            "is_default",
            "is_active",
            "version",
            "stages",
            "task_count",
            "can_delete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "stages", "task_count", "can_delete", "created_at", "updated_at"]

    def get_task_count(self, obj):
        """Get number of tasks using this workflow"""
        return obj.get_tasks_in_workflow().count()

    def get_can_delete(self, obj):
        """Check if workflow can be safely deleted"""
        can_delete, reason = obj.can_delete()
        return {"can_delete": can_delete, "reason": reason}

    def create(self, validated_data):
        from django.db import IntegrityError

        validated_data["team"] = self.context["team"]
        try:
            return super().create(validated_data)
        except IntegrityError as e:
            if "posthog_task_workflow_team_id_name" in str(e):
                raise serializers.ValidationError({"name": "A workflow with this name already exists for this team."})
            raise

    def validate(self, data):
        """Validate workflow data"""
        # Only one default workflow per team
        if data.get("is_default", False):
            team = self.context["team"]
            qs = TaskWorkflow.objects.filter(team=team, is_default=True, is_active=True)
            instance = self.instance
            # self.instance may be a sequence according to DRF typing; ensure we only access .id on a single instance
            if isinstance(instance, TaskWorkflow) and getattr(instance, "id", None):
                qs = qs.exclude(id=instance.id)
            existing_default = qs.exists()

            if existing_default:
                raise serializers.ValidationError("Only one default workflow allowed per team")

        return data


class WorkflowConfigurationSerializer(serializers.Serializer):
    """Serializer for complete workflow configuration (workflow + stages)"""

    workflow = TaskWorkflowSerializer()
    stages = WorkflowStageSerializer(many=True)

    def create(self, validated_data):
        """Create a complete workflow with stages"""
        from django.db import IntegrityError, transaction

        try:
            with transaction.atomic():
                workflow_data = validated_data["workflow"]
                stages_data = validated_data["stages"]

                # Create workflow
                workflow_serializer = TaskWorkflowSerializer(data=workflow_data, context=self.context)
                workflow_serializer.is_valid(raise_exception=True)
                workflow = workflow_serializer.save()

                # Create stages
                for stage_data in stages_data:
                    stage_data["workflow"] = workflow.id
                    stage_serializer = WorkflowStageSerializer(data=stage_data, context=self.context)
                    stage_serializer.is_valid(raise_exception=True)
                    stage_serializer.save(workflow=workflow)

                return workflow
        except IntegrityError as e:
            if "posthog_task_workflow_team_id_name" in str(e):
                raise serializers.ValidationError(
                    {"workflow": {"name": "A workflow with this name already exists for this team."}}
                )
            raise
