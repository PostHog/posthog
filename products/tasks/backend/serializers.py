from django.utils import timezone

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration

from .models import Task, TaskRun
from .services.title_generator import generate_task_title


class TaskSerializer(serializers.ModelSerializer):
    # Computed fields for repository information
    repository_list = serializers.SerializerMethodField()
    primary_repository = serializers.SerializerMethodField()
    latest_run = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)

    title = serializers.CharField(max_length=255, required=False, allow_blank=True)

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
            # Repository fields
            "github_integration",
            "repository_config",
            # Computed fields
            "repository_list",
            "primary_repository",
            "latest_run",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "task_number",
            "slug",
            "created_at",
            "updated_at",
            "created_by",
            "repository_list",
            "primary_repository",
            "latest_run",
        ]

    def get_repository_list(self, obj):
        return obj.repository_list

    def get_primary_repository(self, obj):
        return obj.primary_repository

    def get_latest_run(self, obj):
        latest_run = obj.latest_run
        if latest_run:
            return TaskRunDetailSerializer(latest_run, context=self.context).data
        return None

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

        # Auto-generate title from description if not provided or empty
        title = validated_data.get("title", "").strip()
        if not title and validated_data.get("description"):
            validated_data["title"] = generate_task_title(validated_data["description"])

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


class AgentDefinitionSerializer(serializers.Serializer):
    """Serializer for agent definitions"""

    id = serializers.CharField()
    name = serializers.CharField()
    agent_type = serializers.CharField()
    description = serializers.CharField()
    config = serializers.DictField(default=dict)
    is_active = serializers.BooleanField(default=True)


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


class TaskRunResponseSerializer(serializers.Serializer):
    has_run = serializers.BooleanField(help_text="Whether run information is available")
    id = serializers.UUIDField(required=False, help_text="Run ID")
    status = serializers.ChoiceField(
        choices=["started", "in_progress", "completed", "failed"],
        required=False,
        help_text="Current execution status",
    )
    stage = serializers.CharField(required=False, help_text="Current stage of the run")
    branch = serializers.CharField(required=False, help_text="Branch name for the run")
    created_at = serializers.DateTimeField(required=False, help_text="When run was created")
    updated_at = serializers.DateTimeField(required=False, help_text="When run was last updated")
    completed_at = serializers.DateTimeField(required=False, help_text="When run was completed")
    log = serializers.ListField(
        required=False, child=serializers.DictField(), help_text="Live output from Claude Code execution"
    )
    error_message = serializers.CharField(required=False, help_text="Error message if run failed")
    output = serializers.JSONField(required=False, help_text="Output from the run")
    state = serializers.JSONField(required=False, help_text="State of the run")


class TaskRunUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Run ID")
    status = serializers.ChoiceField(
        choices=["started", "in_progress", "completed", "failed"], help_text="Current execution status"
    )
    log = serializers.ListField(child=serializers.DictField(), help_text="Live output from Claude Code execution")
    error_message = serializers.CharField(help_text="Error message if run failed")
    output = serializers.JSONField(help_text="Output from the run")
    state = serializers.JSONField(help_text="State of the run")
    updated_at = serializers.DateTimeField(help_text="When run was last updated")


class TaskRunStreamResponseSerializer(serializers.Serializer):
    progress_updates = TaskRunUpdateSerializer(many=True, help_text="Array of recent progress updates")
    server_time = serializers.DateTimeField(help_text="Current server time in ISO format")


class TaskSetBranchRequestSerializer(serializers.Serializer):
    branch = serializers.CharField(help_text="Git branch name to associate with the task")


class TaskAttachPullRequestRequestSerializer(serializers.Serializer):
    pr_url = serializers.URLField(help_text="Pull request URL")
    branch = serializers.CharField(required=False, allow_blank=True, help_text="Optional branch name")


class TaskRunDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskRun
        fields = [
            "id",
            "task",
            "stage",
            "branch",
            "status",
            "log",
            "error_message",
            "output",
            "state",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "task",
            "created_at",
            "updated_at",
            "completed_at",
        ]

    def validate_task(self, value):
        team = self.context.get("team")
        if team and value.team_id != team.id:
            raise serializers.ValidationError("Task must belong to the same team")
        return value

    def create(self, validated_data):
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Never allow task reassignment through updates
        validated_data.pop("task", None)

        status = validated_data.get("status")
        if status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED] and not validated_data.get("completed_at"):
            validated_data["completed_at"] = timezone.now()
        return super().update(instance, validated_data)


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Error message")


class AgentListResponseSerializer(serializers.Serializer):
    results = AgentDefinitionSerializer(many=True, help_text="Array of available agent definitions")


class TaskRunAppendLogRequestSerializer(serializers.Serializer):
    entries = serializers.ListField(
        child=serializers.DictField(),
        help_text="Array of log entry dictionaries to append",
    )

    def validate_entries(self, value):
        """Validate that entries is a non-empty list of dicts"""
        if not value:
            raise serializers.ValidationError("At least one log entry is required")
        return value
