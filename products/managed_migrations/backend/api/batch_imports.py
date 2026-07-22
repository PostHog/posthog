import uuid
from datetime import timedelta

import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema_field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User

from products.managed_migrations.backend.models.batch_imports import BatchImport, ContentType, DateRangeExportSource


class BatchImportSerializer(serializers.ModelSerializer):
    """Serializer for BatchImport model"""

    created_by = serializers.SerializerMethodField()

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "created_by",
            "status",
            "display_status_message",
            "import_config",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "display_status_message",
            "import_config",
            "status",
        ]

    def validate_endpoint_url(self, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        # Deferred: batch_export pulls the batch-export Temporal framework, which has no
        # business on this module's import path.
        from products.batch_exports.backend.api.batch_export import resolve_and_validate_url  # noqa: PLC0415

        try:
            resolve_and_validate_url(value)
        except ValueError:
            raise serializers.ValidationError(f"Invalid endpoint URL: '{value}'")
        return value

    def create(self, validated_data: dict) -> BatchImport:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by_id"] = self.context["request"].user.id

        if "import_config" in validated_data:
            validated_data["import_config"] = validated_data.pop("import_config")
        return BatchImport.objects.create(**validated_data)

    @extend_schema_field({"type": "object", "nullable": True})
    def get_created_by(self, obj):
        if obj.created_by_id:
            try:
                user = User.objects.get(id=obj.created_by_id)
                return UserBasicSerializer(user).data
            except User.DoesNotExist:
                return None
        return None


class BatchImportS3SourceCreateSerializer(BatchImportSerializer):
    """Serializer for creating BatchImports with config builder methods"""

    content_type = serializers.ChoiceField(
        choices=["mixpanel", "captured", "amplitude"],
        write_only=True,
        required=True,
    )
    source_type = serializers.ChoiceField(
        choices=["s3"],
        write_only=True,
        required=True,
    )
    s3_bucket = serializers.CharField(write_only=True, required=False)
    s3_prefix = serializers.CharField(write_only=True, required=False, allow_blank=True)
    s3_region = serializers.CharField(write_only=True, required=False)
    access_key = serializers.CharField(write_only=True, required=False)
    secret_key = serializers.CharField(write_only=True, required=False)
    endpoint_url = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        default=None,
        help_text="Custom endpoint URL for S3-compatible storage (e.g. Cloudflare R2, MinIO).",
    )
    import_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_identify_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_group_identify_events = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
            "content_type",
            "source_type",
            "s3_bucket",
            "s3_prefix",
            "s3_region",
            "access_key",
            "secret_key",
            "endpoint_url",
            "import_events",
            "generate_identify_events",
            "generate_group_identify_events",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
        ]

    def create(self, validated_data: dict, **kwargs) -> BatchImport:
        """Create BatchImport using config builder pattern."""
        batch_import = BatchImport(
            team_id=self.context["team_id"],
            created_by_id=self.context["request"].user.id,
        )

        content_type_map = {
            "mixpanel": ContentType.MIXPANEL,
            "amplitude": ContentType.AMPLITUDE,
            "captured": ContentType.CAPTURED,
        }

        content_type = content_type_map[validated_data["content_type"]]

        config_builder = batch_import.config.json_lines(content_type).from_s3(
            bucket=validated_data["s3_bucket"],
            prefix=validated_data.get("s3_prefix", ""),
            region=validated_data["s3_region"],
            access_key_id=validated_data["access_key"],
            secret_access_key=validated_data["secret_key"],
            endpoint_url=validated_data.get("endpoint_url"),
        )

        if content_type == ContentType.AMPLITUDE:
            config_builder = (
                config_builder.with_import_events(validated_data.get("import_events", True))
                .with_generate_identify_events(validated_data.get("generate_identify_events", True))
                .with_generate_group_identify_events(validated_data.get("generate_group_identify_events", False))
            )

        config_builder.to_capture(send_rate=1000)

        batch_import.save()
        return batch_import


class BatchImportS3GzipSourceCreateSerializer(BatchImportSerializer):
    """Serializer for creating BatchImports with S3 gzipped JSONL source"""

    content_type = serializers.ChoiceField(
        choices=["mixpanel", "captured", "amplitude"],
        write_only=True,
        required=True,
    )
    source_type = serializers.ChoiceField(
        choices=["s3_gzip"],
        write_only=True,
        required=True,
    )
    s3_bucket = serializers.CharField(write_only=True, required=False)
    s3_prefix = serializers.CharField(write_only=True, required=False, allow_blank=True)
    s3_region = serializers.CharField(write_only=True, required=False)
    access_key = serializers.CharField(write_only=True, required=False)
    secret_key = serializers.CharField(write_only=True, required=False)
    endpoint_url = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        default=None,
        help_text="Custom endpoint URL for S3-compatible storage (e.g. Cloudflare R2, MinIO).",
    )
    import_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_identify_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_group_identify_events = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
            "content_type",
            "source_type",
            "s3_bucket",
            "s3_prefix",
            "s3_region",
            "access_key",
            "secret_key",
            "endpoint_url",
            "import_events",
            "generate_identify_events",
            "generate_group_identify_events",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
        ]

    def create(self, validated_data: dict, **kwargs) -> BatchImport:
        """Create BatchImport using config builder pattern."""
        batch_import = BatchImport(
            team_id=self.context["team_id"],
            created_by_id=self.context["request"].user.id,
        )

        content_type_map = {
            "mixpanel": ContentType.MIXPANEL,
            "amplitude": ContentType.AMPLITUDE,
            "captured": ContentType.CAPTURED,
        }

        content_type = content_type_map[validated_data["content_type"]]

        config_builder = batch_import.config.json_lines(content_type).from_s3_gzip(
            bucket=validated_data["s3_bucket"],
            prefix=validated_data.get("s3_prefix", ""),
            region=validated_data["s3_region"],
            access_key_id=validated_data["access_key"],
            secret_access_key=validated_data["secret_key"],
            endpoint_url=validated_data.get("endpoint_url"),
        )

        if content_type == ContentType.AMPLITUDE:
            config_builder = (
                config_builder.with_import_events(validated_data.get("import_events", True))
                .with_generate_identify_events(validated_data.get("generate_identify_events", True))
                .with_generate_group_identify_events(validated_data.get("generate_group_identify_events", False))
            )

        config_builder.to_capture(send_rate=1000)

        batch_import.save()
        return batch_import


class BatchImportDateRangeSourceCreateSerializer(BatchImportSerializer):
    """Serializer for creating BatchImports with date range source (mixpanel, amplitude, etc.)"""

    start_date = serializers.DateTimeField(write_only=True, required=True)
    end_date = serializers.DateTimeField(write_only=True, required=True)
    source_type = serializers.ChoiceField(
        choices=["mixpanel", "amplitude"],
        write_only=True,
        required=True,
    )
    content_type = serializers.ChoiceField(
        choices=["mixpanel", "amplitude"],
        write_only=True,
        required=True,
    )
    access_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        default="",
        help_text="Source access key / API key. Required for Amplitude; unused for Mixpanel, which authenticates with the project secret alone.",
    )
    secret_key = serializers.CharField(
        write_only=True,
        required=True,
        help_text="Source secret. For Mixpanel this is the project API secret, found under Project settings → Access keys.",
    )
    is_eu_region = serializers.BooleanField(write_only=True, required=False, default=False)
    import_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_identify_events = serializers.BooleanField(write_only=True, required=False, default=True)
    generate_group_identify_events = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
            "start_date",
            "end_date",
            "source_type",
            "content_type",
            "access_key",
            "secret_key",
            "is_eu_region",
            "import_events",
            "generate_identify_events",
            "generate_group_identify_events",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
        ]

    def validate(self, data):
        """Validate the date range doesn't exceed 1 year"""
        data = super().validate(data)

        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if start_date and end_date:
            if end_date <= start_date:
                raise serializers.ValidationError("End date must be after start date")

            one_year_after_start = start_date + timedelta(days=365)
            if end_date > one_year_after_start:
                raise serializers.ValidationError(
                    "Date range cannot exceed 1 year. Please create multiple migration jobs for longer periods."
                )

            source_type = data.get("source_type")
            if source_type == "amplitude" and (end_date - start_date) < timedelta(hours=1):
                raise serializers.ValidationError("Date range must be at least 1 hour for Amplitude migrations.")

        # For Amplitude, validate required fields and event-type selection
        source_type = data.get("source_type")
        if source_type == "amplitude":
            if not data.get("access_key"):
                raise serializers.ValidationError("Access key is required for Amplitude migrations.")

            import_events = data.get("import_events", True)
            generate_identify_events = data.get("generate_identify_events", True)

            if not import_events and not generate_identify_events:
                raise serializers.ValidationError(
                    "At least one of 'Import events' or 'Generate identify events' must be enabled for Amplitude migrations."
                )

        return data

    def create(self, validated_data: dict, **kwargs) -> BatchImport:
        """Create a new BatchImport from Date Range Source"""
        validated_data["team_id"] = self.context["team_id"]
        source_type = validated_data["source_type"]

        if source_type in ["amplitude", "mixpanel"]:
            batch_import = BatchImport(
                team_id=self.context["team_id"],
                created_by_id=self.context["request"].user.id,
            )

            config_builder = batch_import.config.json_lines(
                ContentType(validated_data["content_type"])
            ).from_date_range(
                start_date=validated_data["start_date"].isoformat(),
                end_date=validated_data["end_date"].isoformat(),
                access_key=validated_data["access_key"],
                secret_key=validated_data["secret_key"],
                export_source=DateRangeExportSource(source_type),
                is_eu_region=validated_data.get("is_eu_region", False),
            )

            # Only apply import_events and generate_identify_events for Amplitude
            if source_type == "amplitude":
                config_builder = (
                    config_builder.with_import_events(validated_data.get("import_events", True))
                    .with_generate_identify_events(validated_data.get("generate_identify_events", True))
                    .with_generate_group_identify_events(validated_data.get("generate_group_identify_events", True))
                )

            config_builder.to_capture(send_rate=1000)

            batch_import.save()
            return batch_import
        else:
            raise serializers.ValidationError("Invalid source type")


class BatchImportResponseSerializer(serializers.ModelSerializer):
    """Serializer for BatchImport responses that matches frontend expectations"""

    created_by = serializers.SerializerMethodField()
    source_type = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    status_message = serializers.CharField(source="display_status_message", allow_null=True)
    display_status = serializers.SerializerMethodField()

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "source_type",
            "content_type",
            "status",
            "display_status",
            "start_date",
            "end_date",
            "created_by",
            "created_at",
            "status_message",
            "state",
        ]

    def get_source_type(self, obj):
        """Extract source type from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("type", "s3")

    def get_start_date(self, obj):
        """Extract start date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("start")

    def get_end_date(self, obj):
        """Extract end date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("end")

    def get_content_type(self, obj):
        """Extract content type from import_config"""
        data_format = obj.import_config.get("data_format", {})
        content = data_format.get("content", {})
        return content.get("type", "captured")

    def get_created_by(self, obj):
        if obj.created_by_id:
            try:
                user = User.objects.get(id=obj.created_by_id)
                return UserBasicSerializer(user).data
            except User.DoesNotExist:
                return None
        return None

    def get_display_status(self, obj):
        if obj.status == BatchImport.Status.RUNNING and obj.lease_id is None:
            return "waiting_to_start"
        return obj.status


class BatchImportViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Viewset for BatchImport model"""

    scope_object = "INTERNAL"
    queryset = BatchImport.objects.all()
    serializer_class = _FallbackSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    search_fields = ["status_message"]
    ordering_fields = ["created_at", "updated_at", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        """Use the correct serializer based on the source type"""
        if self.action == "create":
            source_type = self.request.data.get("source_type")
            if source_type == "s3":
                return BatchImportS3SourceCreateSerializer
            elif source_type == "s3_gzip":
                return BatchImportS3GzipSourceCreateSerializer
            elif source_type in ["mixpanel", "amplitude"]:
                return BatchImportDateRangeSourceCreateSerializer
            elif source_type is not None:
                raise serializers.ValidationError("Invalid source type")
            elif getattr(self, "swagger_fake_view", False):
                return BatchImportSerializer
            else:
                raise serializers.ValidationError("Invalid source type")
        return BatchImportSerializer

    def safely_get_queryset(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return queryset.filter(team_id=self.team_id)

    def list(self, request: Request, **kwargs) -> Response:
        """List managed migrations using the response serializer"""
        queryset = self.safely_get_queryset()
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = BatchImportResponseSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = BatchImportResponseSerializer(queryset, many=True)
        return Response({"results": serializer.data})

    def create(self, request: Request, **kwargs) -> Response:
        """Create a new managed migration/batch import."""
        existing_running_import = BatchImport.objects.filter(
            team_id=self.team_id, status=BatchImport.Status.RUNNING
        ).first()

        if existing_running_import:
            return Response(
                {
                    "error": "Cannot create a new batch import while another import is already running for this organization.",
                    "detail": f"Please wait for the current import (ID: {existing_running_import.id}) to complete or pause it before starting a new one.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        migration = serializer.save()

        source_type = request.data.get("source_type", "unknown")
        content_type = request.data.get("content_type", "unknown")

        distinct_id = (
            request.user.distinct_id
            if request.user.is_authenticated and request.user.distinct_id
            else str(uuid.uuid4())
        )

        posthoganalytics.capture(
            "batch import created",
            distinct_id=distinct_id,
            properties={
                "batch_import_id": migration.id,
                "source_type": source_type,
                "content_type": content_type,
                "team_id": self.team_id,
                "$process_person_profile": False,
            },
        )

        response_serializer = BatchImportResponseSerializer(migration)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True)
    def pause(self, request: Request, **kwargs) -> Response:
        """Pause a running batch import."""
        batch_import = self.get_object()

        if batch_import.status != BatchImport.Status.RUNNING:
            return Response(
                {"error": "only running imports can be paused"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Clear the lease and backoff state so the Rust worker stops owning the row. Without this
        # the worker keeps its lease and its next lease-scoped write flips the status back to
        # running, leaving the job stuck in a paused/running loop the user can't escape.
        batch_import.status = BatchImport.Status.PAUSED
        batch_import.status_message = "Paused by user"
        batch_import.lease_id = None
        batch_import.leased_until = None
        batch_import.backoff_attempt = 0
        batch_import.backoff_until = None
        batch_import.save(
            update_fields=[
                "status",
                "status_message",
                "lease_id",
                "leased_until",
                "backoff_attempt",
                "backoff_until",
                "updated_at",
            ]
        )

        return Response({"status": "paused"})

    @action(methods=["POST"], detail=True)
    def resume(self, request: Request, **kwargs) -> Response:
        """Resume a paused batch import."""
        batch_import = self.get_object()

        if batch_import.status != BatchImport.Status.PAUSED:
            return Response({"error": "Only paused imports can be resumed"}, status=status.HTTP_400_BAD_REQUEST)

        batch_import.status = BatchImport.Status.RUNNING
        batch_import.status_message = "Resumed by user"
        batch_import.lease_id = None
        batch_import.leased_until = None
        batch_import.backoff_attempt = 0
        batch_import.backoff_until = None
        batch_import.save(
            update_fields=[
                "status",
                "status_message",
                "lease_id",
                "leased_until",
                "backoff_attempt",
                "backoff_until",
                "updated_at",
            ]
        )

        return Response({"status": "resumed"})

    @action(methods=["POST"], detail=True)
    def cancel(self, request: Request, **kwargs) -> Response:
        """Cancel a running or paused batch import, moving it to a terminal state."""
        batch_import = self.get_object()

        if batch_import.status not in (BatchImport.Status.RUNNING, BatchImport.Status.PAUSED):
            return Response(
                {"error": "Only running or paused imports can be cancelled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Terminal cancel: clear the lease/backoff state so the Rust worker stops owning the row,
        # and set a status the worker never re-claims (it only picks up 'running' jobs). This frees
        # the org's single-running-import slot so new imports can be created.
        batch_import.status = BatchImport.Status.CANCELLED
        batch_import.status_message = "Cancelled by user"
        batch_import.lease_id = None
        batch_import.leased_until = None
        batch_import.backoff_attempt = 0
        batch_import.backoff_until = None
        batch_import.save(
            update_fields=[
                "status",
                "status_message",
                "lease_id",
                "leased_until",
                "backoff_attempt",
                "backoff_until",
                "updated_at",
            ]
        )

        return Response({"status": "cancelled"})
