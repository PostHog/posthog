import uuid
from copy import deepcopy
from datetime import timedelta
from typing import cast

import posthoganalytics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User

from products.managed_migrations.backend import trial_storage
from products.managed_migrations.backend.models.batch_imports import (
    BatchImport,
    BatchImportConfigBuilder,
    ContentType,
    DateRangeExportSource,
)

TRIAL_RECORD_LIMIT_DEFAULT = 1_000
TRIAL_RECORD_LIMIT_MAX = 50_000


class BatchImportTrialOptionsMixin(serializers.Serializer):
    """Write-only trial options shared by every create serializer."""

    is_trial = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text="Run a trial instead of a real import: parse and transform up to trial_record_limit source records and store browsable results, without ingesting any events.",
    )
    trial_record_limit = serializers.IntegerField(
        write_only=True,
        required=False,
        default=TRIAL_RECORD_LIMIT_DEFAULT,
        min_value=1,
        max_value=TRIAL_RECORD_LIMIT_MAX,
        help_text=f"Maximum number of source records to process in a trial run (1 to {TRIAL_RECORD_LIMIT_MAX}). Ignored unless is_trial is set.",
    )


def _apply_output_sink(config_builder: BatchImportConfigBuilder, validated_data: dict) -> None:
    """Point the job at its output: the trial results bucket for trial runs, capture otherwise."""
    if validated_data.get("is_trial"):
        config_builder.to_trial_output(
            record_limit=validated_data.get("trial_record_limit", TRIAL_RECORD_LIMIT_DEFAULT)
        )
    else:
        config_builder.to_capture(send_rate=1000)


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


class BatchImportS3SourceCreateSerializer(BatchImportTrialOptionsMixin, BatchImportSerializer):
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
            "is_trial",
            "trial_record_limit",
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

        _apply_output_sink(config_builder, validated_data)

        batch_import.save()
        return batch_import


class BatchImportS3GzipSourceCreateSerializer(BatchImportTrialOptionsMixin, BatchImportSerializer):
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
            "is_trial",
            "trial_record_limit",
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

        _apply_output_sink(config_builder, validated_data)

        batch_import.save()
        return batch_import


class BatchImportDateRangeSourceCreateSerializer(BatchImportTrialOptionsMixin, BatchImportSerializer):
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
            "is_trial",
            "trial_record_limit",
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

            _apply_output_sink(config_builder, validated_data)

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
    is_trial = serializers.BooleanField(
        read_only=True, help_text="Whether this job is a trial run (stores browsable results instead of ingesting)."
    )
    trial_record_limit = serializers.SerializerMethodField()

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
            "is_trial",
            "trial_record_limit",
        ]

    @extend_schema_field({"type": "string"})
    def get_source_type(self, obj):
        """Extract source type from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("type", "s3")

    @extend_schema_field({"type": "string", "nullable": True})
    def get_start_date(self, obj):
        """Extract start date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("start")

    @extend_schema_field({"type": "string", "nullable": True})
    def get_end_date(self, obj):
        """Extract end date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("end")

    @extend_schema_field({"type": "string"})
    def get_content_type(self, obj):
        """Extract content type from import_config"""
        data_format = obj.import_config.get("data_format", {})
        content = data_format.get("content", {})
        return content.get("type", "captured")

    @extend_schema_field({"type": "object", "nullable": True})
    def get_created_by(self, obj):
        if obj.created_by_id:
            try:
                user = User.objects.get(id=obj.created_by_id)
                return UserBasicSerializer(user).data
            except User.DoesNotExist:
                return None
        return None

    @extend_schema_field({"type": "string"})
    def get_display_status(self, obj):
        if obj.status == BatchImport.Status.RUNNING and obj.lease_id is None:
            return "waiting_to_start"
        return obj.status

    @extend_schema_field({"type": "integer", "nullable": True})
    def get_trial_record_limit(self, obj):
        """The trial's source-record cap from the sink config; null for real imports."""
        if not obj.is_trial:
            return None
        return obj.import_config.get("sink", {}).get("record_limit")


class TrialRecordsResponseSerializer(serializers.Serializer):
    """One page of trial-run results, proxied from the trial output store."""

    records = serializers.ListField(
        child=serializers.JSONField(),
        help_text="Trial records in source order: each has seq (global index), source (the original source event), outputs (the event(s) it would produce), and error (why it would be dropped, if it would be).",
    )
    page = serializers.IntegerField(help_text="Zero-based index of this page.")
    total_pages = serializers.IntegerField(help_text="Number of result pages written so far.")
    total_records = serializers.IntegerField(help_text="Number of source records processed so far.")
    summary = serializers.JSONField(
        allow_null=True,
        help_text="Running aggregates: output event name counts, error counts, dropped/skipped totals, timestamp range.",
    )


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

    def _running_import_conflict(self, is_trial: bool) -> Response | None:
        """One running job per team and per kind: a trial only conflicts with
        another running trial, a real import only with another real import, so
        users can trial their next migration while one is ingesting.

        The kind check runs in Python (a team has at most a handful of running
        rows): a JSON-path exclude() would silently drop rows whose config has
        no sink key at all, letting a running legacy-shaped import go unnoticed.
        """
        running = BatchImport.objects.filter(team_id=self.team_id, status=BatchImport.Status.RUNNING)
        conflict = next((job for job in running if job.is_trial == is_trial), None)
        if conflict is None:
            return None
        if is_trial:
            return Response(
                {
                    "error": "Cannot create a new trial run while another trial is already running for this project.",
                    "detail": f"Please wait for the current trial (ID: {conflict.id}) to complete before starting a new one.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "error": "Cannot create a new batch import while another import is already running for this organization.",
                "detail": f"Please wait for the current import (ID: {conflict.id}) to complete or pause it before starting a new one.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _capture_batch_import_created(self, request: Request, migration: BatchImport, properties: dict) -> None:
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
                "team_id": self.team_id,
                "is_trial": migration.is_trial,
                "$process_person_profile": False,
                **properties,
            },
        )

    def create(self, request: Request, **kwargs) -> Response:
        """Create a new managed migration/batch import."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        conflict = self._running_import_conflict(is_trial=serializer.validated_data.get("is_trial", False))
        if conflict:
            return conflict

        migration = serializer.save()

        self._capture_batch_import_created(
            request,
            migration,
            {
                "source_type": request.data.get("source_type", "unknown"),
                "content_type": request.data.get("content_type", "unknown"),
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

        batch_import.status = BatchImport.Status.PAUSED
        batch_import.status_message = "Paused by user"
        batch_import.save(update_fields=["status", "status_message", "updated_at"])

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

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "page", int, description="Zero-based results page index (see total_pages in the response)."
            )
        ],
        responses={200: TrialRecordsResponseSerializer},
    )
    @action(methods=["GET"], detail=True)
    def trial_records(self, request: Request, **kwargs) -> Response:
        """Fetch one page of a trial run's results (source event paired with its would-be output events)."""
        batch_import = self.get_object()

        if not batch_import.is_trial:
            return Response({"error": "This import is not a trial run"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            page = int(request.query_params.get("page", "0"))
        except ValueError:
            return Response({"error": "page must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        if page < 0:
            return Response({"error": "page must be non-negative"}, status=status.HTTP_400_BAD_REQUEST)

        trial = batch_import.trial_progress() or {}
        total_pages = trial.get("pages_written", 0)
        if page >= total_pages:
            return Response(
                {"error": f"Page {page} does not exist", "total_pages": total_pages},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            records = trial_storage.read_trial_page(batch_import.team_id, str(batch_import.id), page)
        except trial_storage.TrialResultsUnavailable:
            return Response(
                {"error": "Trial results have expired and are no longer available"},
                status=status.HTTP_410_GONE,
            )

        return Response(
            {
                "records": records,
                "page": page,
                "total_pages": total_pages,
                "total_records": trial.get("records_emitted", 0),
                "summary": trial.get("summary"),
            }
        )

    @extend_schema(request=None, responses={201: BatchImportResponseSerializer})
    @action(methods=["POST"], detail=True)
    def promote(self, request: Request, **kwargs) -> Response:
        """Start the real import from a completed trial run, reusing its source config and credentials."""
        trial = self.get_object()

        if not trial.is_trial:
            return Response({"error": "Only trial runs can be promoted"}, status=status.HTTP_400_BAD_REQUEST)
        if trial.status != BatchImport.Status.COMPLETED:
            return Response({"error": "Only completed trial runs can be promoted"}, status=status.HTTP_400_BAD_REQUEST)

        conflict = self._running_import_conflict(is_trial=False)
        if conflict:
            return conflict

        import_config = deepcopy(trial.import_config)
        import_config["sink"] = {"type": "capture", "send_rate": 1000}

        migration = BatchImport.objects.create(
            team_id=self.team_id,
            created_by_id=cast(User, request.user).pk,
            import_config=import_config,
            secrets=trial.secrets,
        )

        self._capture_batch_import_created(request, migration, {"promoted_from_trial_id": str(trial.id)})

        return Response(BatchImportResponseSerializer(migration).data, status=status.HTTP_201_CREATED)
