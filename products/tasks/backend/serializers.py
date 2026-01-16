from django.core.cache import cache
from django.utils import timezone

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import Integration
from posthog.storage import object_storage

from .models import Task, TaskReference, TaskRun
from .services.title_generator import generate_task_title

PRESIGNED_URL_CACHE_TTL = 55 * 60  # 55 minutes (less than 1 hour URL expiry)


class TaskSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    latest_run = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    reference_count = serializers.SerializerMethodField()

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
            "repository",
            "github_integration",
            "json_schema",
            "latest_run",
            "created_at",
            "updated_at",
            "created_by",
            # Video segment clustering fields
            "relevant_user_count",
            "occurrence_count",
            "last_occurrence_at",
            "reference_count",
        ]
        read_only_fields = [
            "id",
            "task_number",
            "slug",
            "created_at",
            "updated_at",
            "created_by",
            "latest_run",
            "relevant_user_count",
            "occurrence_count",
            "last_occurrence_at",
            "reference_count",
        ]

    def get_latest_run(self, obj):
        latest_run = obj.latest_run
        if latest_run:
            return TaskRunDetailSerializer(latest_run, context=self.context).data
        return None

    def get_reference_count(self, obj) -> int:
        return getattr(obj, "reference_count", 0)

    def validate_github_integration(self, value):
        """Validate that the GitHub integration belongs to the same team"""
        if value and value.team_id != self.context["team"].id:
            raise serializers.ValidationError("Integration must belong to the same team")
        return value

    def validate_repository(self, value):
        """Validate repository configuration"""
        if not value:
            return value

        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise serializers.ValidationError("Repository must be in the format organization/repository")

        return value.lower()

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


class AgentDefinitionSerializer(serializers.Serializer):
    """Serializer for agent definitions"""

    id = serializers.CharField()
    name = serializers.CharField()
    agent_type = serializers.CharField()
    description = serializers.CharField()
    config = serializers.DictField(default=dict)
    is_active = serializers.BooleanField(default=True)


class TaskRunUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["not_started", "queued", "in_progress", "completed", "failed", "cancelled"],
        required=False,
        help_text="Current execution status",
    )
    branch = serializers.CharField(
        required=False, allow_null=True, help_text="Git branch name to associate with the task"
    )
    stage = serializers.CharField(
        required=False, allow_null=True, help_text="Current stage of the run (e.g. research, plan, build)"
    )
    output = serializers.JSONField(required=False, allow_null=True, help_text="Output from the run")
    state = serializers.JSONField(required=False, help_text="State of the run")
    error_message = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, help_text="Error message if execution failed"
    )


class TaskRunArtifactResponseSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Artifact file name")
    type = serializers.CharField(help_text="Artifact classification (plan, context, etc.)")
    size = serializers.IntegerField(required=False, help_text="Artifact size in bytes")
    content_type = serializers.CharField(required=False, allow_blank=True, help_text="Optional MIME type")
    storage_path = serializers.CharField(help_text="S3 object key for the artifact")
    uploaded_at = serializers.CharField(help_text="Timestamp when the artifact was uploaded")


class TaskRunDetailSerializer(serializers.ModelSerializer):
    log_url = serializers.SerializerMethodField(help_text="Presigned S3 URL for log access (valid for 1 hour).")
    artifacts = TaskRunArtifactResponseSerializer(many=True, read_only=True)

    class Meta:
        model = TaskRun
        fields = [
            "id",
            "task",
            "stage",
            "branch",
            "status",
            "environment",
            "log_url",
            "error_message",
            "output",
            "state",
            "artifacts",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "task",
            "log_url",
            "created_at",
            "updated_at",
            "completed_at",
        ]

    def get_log_url(self, obj: TaskRun) -> str | None:
        """Return presigned S3 URL for log access, cached to avoid regeneration."""
        cache_key = f"task_run_log_url:{obj.id}"

        cached_url = cache.get(cache_key)
        if cached_url:
            return cached_url

        presigned_url = object_storage.get_presigned_url(obj.log_url, expiration=3600)

        if presigned_url:
            cache.set(cache_key, presigned_url, timeout=PRESIGNED_URL_CACHE_TTL)

        return presigned_url

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


class TaskRunArtifactUploadSerializer(serializers.Serializer):
    ARTIFACT_TYPE_CHOICES = ["plan", "context", "reference", "output", "artifact"]

    name = serializers.CharField(max_length=255, help_text="File name to associate with the artifact")
    type = serializers.ChoiceField(choices=ARTIFACT_TYPE_CHOICES, help_text="Classification for the artifact")
    content = serializers.CharField(help_text="Raw file contents (UTF-8 string or base64 data)")
    content_type = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="Optional MIME type for the artifact",
    )


class TaskRunArtifactsUploadRequestSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactUploadSerializer(many=True, help_text="Array of artifacts to upload")

    def validate_artifacts(self, value):
        if not value:
            raise serializers.ValidationError("At least one artifact is required")
        return value


class TaskRunArtifactsUploadResponseSerializer(serializers.Serializer):
    artifacts = TaskRunArtifactResponseSerializer(many=True, help_text="Updated list of artifacts on the run")


class TaskRunArtifactPresignRequestSerializer(serializers.Serializer):
    storage_path = serializers.CharField(
        max_length=500,
        help_text="S3 storage path returned in the artifact manifest",
    )


class TaskRunArtifactPresignResponseSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Presigned URL for downloading the artifact")
    expires_in = serializers.IntegerField(help_text="URL expiry in seconds")


class TaskReferenceSerializer(serializers.ModelSerializer):
    """Serializer for references attached to tasks."""

    class Meta:
        model = TaskReference
        fields = [
            "id",
            "session_id",
            "start_time",
            "end_time",
            "distinct_id",
            "content",
            "distance_to_centroid",
            "created_at",
        ]
        read_only_fields = fields


class TaskListQuerySerializer(serializers.Serializer):
    """Query parameters for listing tasks"""

    origin_product = serializers.CharField(required=False, help_text="Filter by origin product")
    stage = serializers.CharField(required=False, help_text="Filter by task run stage")
    organization = serializers.CharField(required=False, help_text="Filter by repository organization")
    repository = serializers.CharField(
        required=False, help_text="Filter by repository name (can include org/repo format)"
    )
    created_by = serializers.IntegerField(required=False, help_text="Filter by creator user ID")
