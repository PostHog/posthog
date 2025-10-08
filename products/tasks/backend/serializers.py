from django.db import IntegrityError, transaction

from rest_framework import serializers

from posthog.models.integration import Integration

from .agents import get_agent_dict_by_id
from .models import Task, TaskWorkflow, WorkflowStage


class TaskSerializer(serializers.ModelSerializer):
    # Computed fields for repository information
    repository_list = serializers.SerializerMethodField()
    primary_repository = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "task_number",
            "slug",
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
            "task_number",
            "slug",
            "created_at",
            "updated_at",
            "github_branch",
            "github_pr_url",
            "repository_list",
            "primary_repository",
        ]

    def get_repository_list(self, obj):
        return obj.repository_list

    def get_primary_repository(self, obj):
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

        if "request" in self.context and hasattr(self.context["request"], "user"):
            validated_data["created_by"] = self.context["request"].user

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
    agent = serializers.SerializerMethodField()
    agent_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)

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
        read_only_fields = ["id", "task_count", "agent"]

    def get_task_count(self, obj):
        """Get number of tasks currently in this stage"""
        return Task.objects.filter(current_stage=obj).count()

    def get_agent(self, obj):
        """Get the agent object for this stage"""
        if hasattr(obj, "agent_name") and obj.agent_name:
            return get_agent_dict_by_id(obj.agent_name)
        return None

    def validate_workflow(self, value):
        """Validate that the workflow exists and belongs to the current team"""
        if "team" in self.context and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Workflow must belong to the same team")
        return value

    def validate_agent_name(self, value):
        """Validate that the agent name is valid"""
        if value:
            from .agents import get_agent_by_id

            if not get_agent_by_id(value):
                raise serializers.ValidationError(f"Invalid agent name: {value}")
        return value


class AgentDefinitionSerializer(serializers.Serializer):
    """Serializer for agent definitions"""

    id = serializers.CharField()
    name = serializers.CharField()
    agent_type = serializers.CharField()
    description = serializers.CharField()
    config = serializers.DictField(default=dict)
    is_active = serializers.BooleanField(default=True)


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
        return obj.tasks.count()

    def get_can_delete(self, obj):
        """Check if workflow can be safely deleted"""
        can_delete, reason = obj.can_delete()
        return {"can_delete": can_delete, "reason": reason}

    def create(self, validated_data):
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


class TaskUpdateStageRequestSerializer(serializers.Serializer):
    current_stage = serializers.UUIDField(help_text="UUID of the workflow stage to move the task to")


class TaskUpdatePositionRequestSerializer(serializers.Serializer):
    position = serializers.IntegerField(help_text="New position for the task")


class TaskBulkReorderRequestSerializer(serializers.Serializer):
    columns = serializers.DictField(
        child=serializers.ListField(child=serializers.UUIDField()),
        help_text="Object mapping stage keys to arrays of task UUIDs in the desired order",
    )


class TaskBulkReorderResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField(help_text="Number of tasks that were updated")
    tasks = serializers.ListField(
        child=serializers.DictField(), help_text="Array of updated tasks with their new positions and stages"
    )


class TaskProgressResponseSerializer(serializers.Serializer):
    has_progress = serializers.BooleanField(help_text="Whether progress information is available")
    id = serializers.UUIDField(required=False, help_text="Progress record ID")
    status = serializers.ChoiceField(
        choices=["started", "in_progress", "completed", "failed"],
        required=False,
        help_text="Current execution status",
    )
    current_step = serializers.CharField(required=False, help_text="Description of current step being executed")
    completed_steps = serializers.IntegerField(required=False, help_text="Number of completed steps")
    total_steps = serializers.IntegerField(required=False, help_text="Total number of steps")
    progress_percentage = serializers.FloatField(required=False, help_text="Progress percentage (0-100)")
    output_log = serializers.CharField(required=False, help_text="Live output from Claude Code execution")
    error_message = serializers.CharField(required=False, help_text="Error message if execution failed")
    created_at = serializers.DateTimeField(required=False, help_text="When progress tracking started")
    updated_at = serializers.DateTimeField(required=False, help_text="When progress was last updated")
    completed_at = serializers.DateTimeField(required=False, help_text="When execution completed")
    workflow_id = serializers.CharField(required=False, help_text="Temporal workflow ID")
    workflow_run_id = serializers.CharField(required=False, help_text="Temporal workflow run ID")
    message = serializers.CharField(required=False, help_text="Message when no progress is available")


class TaskProgressUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Progress record ID")
    status = serializers.ChoiceField(
        choices=["started", "in_progress", "completed", "failed"], help_text="Current execution status"
    )
    current_step = serializers.CharField(help_text="Description of current step being executed")
    completed_steps = serializers.IntegerField(help_text="Number of completed steps")
    total_steps = serializers.IntegerField(help_text="Total number of steps")
    progress_percentage = serializers.FloatField(help_text="Progress percentage (0-100)")
    output_log = serializers.CharField(help_text="Live output from Claude Code execution")
    error_message = serializers.CharField(help_text="Error message if execution failed")
    updated_at = serializers.DateTimeField(help_text="When progress was last updated")
    workflow_id = serializers.CharField(help_text="Temporal workflow ID")


class TaskProgressStreamResponseSerializer(serializers.Serializer):
    progress_updates = TaskProgressUpdateSerializer(many=True, help_text="Array of recent progress updates")
    server_time = serializers.DateTimeField(help_text="Current server time in ISO format")


class WorkflowStageArchiveResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Success message")


class WorkflowDeactivateResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Success message")


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Error message")


class AgentListResponseSerializer(serializers.Serializer):
    results = AgentDefinitionSerializer(many=True, help_text="Array of available agent definitions")
