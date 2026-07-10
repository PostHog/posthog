from django.utils import timezone

import structlog
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from rest_framework import filters, request, response, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission, IsStaffUser

from products.managed_migrations.backend.models.batch_import_utils import (
    extract_batch_import_info,
    get_batch_import_created_by_info,
)
from products.managed_migrations.backend.models.batch_imports import BatchImport

logger = structlog.get_logger(__name__)

DISPLAY_STATUSES = ["waiting_to_start", "running", "paused", "failed", "completed"]


@extend_schema_field({"type": "object", "nullable": True})
class RawJSONField(serializers.JSONField):
    """JSON blob passed through untyped: the shape is owned by the Rust batch-import worker."""


class BatchImportPartsProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField(
        help_text="Number of finished parts (a part is done when its committed byte offset has reached its known total size)."
    )
    total = serializers.IntegerField(help_text="Total number of parts the worker has planned for this import.")
    inflight_key = serializers.CharField(
        allow_null=True,
        help_text="Key (file/date-range identifier) of the first unfinished part - the one in flight or next up. Null when all parts are done or the worker has not started.",
    )
    inflight_offset = serializers.IntegerField(
        allow_null=True,
        help_text="Committed byte offset (decompressed) within the in-flight part. Null when there is no in-flight part.",
    )
    inflight_total_size = serializers.IntegerField(
        allow_null=True,
        help_text="Total decompressed size in bytes of the in-flight part, or null if the worker has not measured it yet.",
    )


class BatchImportSupportListSerializer(serializers.ModelSerializer):
    """Compact cross-team diagnostics view of a batch import job for PostHog support staff.

    Excludes the raw `state` / `import_config` blobs (see the detail serializer) and never
    exposes the encrypted `secrets` column.
    """

    team_id = serializers.IntegerField(help_text="ID of the team (project) the import belongs to.")
    team_name = serializers.CharField(source="team.name", help_text="Name of the team the import belongs to.")
    display_status = serializers.SerializerMethodField(
        help_text="Effective status: 'waiting_to_start' when the job is running but no worker has claimed it yet (lease_id is null), otherwise the raw status."
    )
    parts_progress = serializers.SerializerMethodField(
        help_text="Worker part progress summary derived from the raw state blob."
    )
    lease_expired = serializers.SerializerMethodField(
        help_text="True when the job holds a lease whose expiry is in the past. On a running job this means the worker died or the row is claimable again; the next poll can re-claim it."
    )
    source_type = serializers.SerializerMethodField(
        help_text="Source the job imports from (e.g. s3, mixpanel, amplitude, urls, folder), or 'unknown' if unset."
    )
    content_type = serializers.SerializerMethodField(
        help_text="Format of the source events (e.g. mixpanel, amplitude, captured), or 'unknown' if unset."
    )
    source_start_date = serializers.SerializerMethodField(
        help_text="Start of the source date range for date-range sources (Mixpanel/Amplitude), else null."
    )
    source_end_date = serializers.SerializerMethodField(
        help_text="End of the source date range for date-range sources (Mixpanel/Amplitude), else null."
    )
    sink_type = serializers.SerializerMethodField(
        help_text="Where imported events are written (normally 'capture'; 'kafka'/'noop' for internal use), or null if unset."
    )
    sink_send_rate = serializers.SerializerMethodField(
        help_text="Configured sink send rate in events per second, or null if unset."
    )

    class Meta:
        model = BatchImport
        # `secrets` is deliberately absent: an explicit field list is the structural guarantee
        # that the encrypted credentials column can never serialize into a support response.
        fields = [
            "id",
            "team_id",
            "team_name",
            "status",
            "display_status",
            "status_message",
            "display_status_message",
            "parts_progress",
            "source_type",
            "content_type",
            "source_start_date",
            "source_end_date",
            "sink_type",
            "sink_send_rate",
            "lease_id",
            "leased_until",
            "lease_expired",
            "backoff_attempt",
            "backoff_until",
            "created_by_id",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "UUID of the batch import job."},
            "status": {"help_text": "Raw persisted status of the job."},
            "status_message": {
                "help_text": "Developer-facing status message written by the worker or an operator - the primary debugging signal. Not shown to the customer."
            },
            "display_status_message": {"help_text": "Customer-facing status message shown in the PostHog UI."},
            "lease_id": {
                "help_text": "Lease token of the worker currently holding the job, or null when unclaimed. Claims lease for 30 minutes; the running heartbeat renews for 5 minutes."
            },
            "leased_until": {"help_text": "When the current worker lease expires."},
            "backoff_attempt": {"help_text": "Consecutive transient-failure retries so far (0 = healthy)."},
            "backoff_until": {
                "help_text": "When the worker will retry after a transient failure. A future value means the job is in a retry loop, not stuck."
            },
            "created_by_id": {"help_text": "ID of the user who created the import, if any."},
            "created_at": {"help_text": "When the import was created."},
            "updated_at": {"help_text": "Last write to the row - the worker heartbeats this while processing."},
        }

    @extend_schema_field(serializers.ChoiceField(choices=DISPLAY_STATUSES))
    def get_display_status(self, obj: BatchImport) -> str:
        if obj.status == BatchImport.Status.RUNNING and obj.lease_id is None:
            return "waiting_to_start"
        return obj.status

    @extend_schema_field(BatchImportPartsProgressSerializer)
    def get_parts_progress(self, obj: BatchImport) -> dict:
        done, total, inflight = obj.parts_progress()
        return {
            "done": done,
            "total": total,
            "inflight_key": inflight.get("key") if inflight else None,
            "inflight_offset": inflight.get("current_offset") if inflight else None,
            "inflight_total_size": inflight.get("total_size") if inflight else None,
        }

    def get_lease_expired(self, obj: BatchImport) -> bool:
        return obj.lease_id is not None and obj.leased_until is not None and obj.leased_until < timezone.now()

    def get_source_type(self, obj: BatchImport) -> str:
        source_type, _content_type, _start, _end = extract_batch_import_info(obj)
        return source_type

    def get_content_type(self, obj: BatchImport) -> str:
        _source_type, content_type, _start, _end = extract_batch_import_info(obj)
        return content_type

    def get_source_start_date(self, obj: BatchImport) -> str | None:
        _source_type, _content_type, start, _end = extract_batch_import_info(obj)
        return start

    def get_source_end_date(self, obj: BatchImport) -> str | None:
        _source_type, _content_type, _start, end = extract_batch_import_info(obj)
        return end

    def get_sink_type(self, obj: BatchImport) -> str | None:
        return ((obj.import_config or {}).get("sink") or {}).get("type")

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_sink_send_rate(self, obj: BatchImport) -> int | None:
        return ((obj.import_config or {}).get("sink") or {}).get("send_rate")


class BatchImportSupportDetailSerializer(BatchImportSupportListSerializer):
    """Full diagnostics view: adds the raw worker `state` and `import_config` blobs.

    `import_config` holds secret key *names* only - secret values live exclusively in the
    encrypted `secrets` column, which no support serializer exposes.
    """

    state = RawJSONField(
        read_only=True,
        help_text="Raw worker progress blob: {'parts': [{'key', 'current_offset', 'total_size'}]}. A part is done when current_offset >= total_size; parts are processed in order.",
    )
    import_config = RawJSONField(
        read_only=True,
        help_text="Source/format/sink configuration of the job. References secrets by key name only; secret values are never returned.",
    )
    created_by_email = serializers.SerializerMethodField(
        help_text="Email of the user who created the import, if known."
    )

    class Meta(BatchImportSupportListSerializer.Meta):
        fields = [*BatchImportSupportListSerializer.Meta.fields, "state", "import_config", "created_by_email"]

    def get_created_by_email(self, obj: BatchImport) -> str | None:
        _id, email, _name = get_batch_import_created_by_info(obj)
        return email


@extend_schema_view(
    list=extend_schema(
        description="List batch import (managed migration) jobs across all teams. PostHog staff only.",
    ),
    retrieve=extend_schema(
        description="Get one batch import job with its raw worker state and import config. PostHog staff only.",
    ),
)
class BatchImportSupportViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Staff-only, cross-team diagnostics for batch import (managed migration) jobs.

    Unlike BatchImportViewSet (membership-scoped via TeamAndOrgViewSetMixin), support staff
    need to inspect jobs on teams they do not belong to, so this is registered on the root
    router. Read-only on purpose; mutations (resume/pause) stay in Django admin for now.
    Exposes the same data Django admin's BatchImportAdmin already shows staff un-redacted.

    Access requires ALL of:
    - a staff user (`is_staff`) - enforced for both session and personal-API-key auth, since
      PersonalAPIKeyAuthentication authenticates as the key's real user;
    - for token auth, a personal API key explicitly carrying `batch_import_support:read`.
      The scope is OAuth-hidden (grantable to a PAT, never via OAuth consent) and
      `scope_object = "INTERNAL"` blocks full-access (`*`) keys, so only a deliberately
      minted key works. Browser sessions bypass the scope layer and rely on `is_staff`.

    To mint a key (the scope is hidden from the PAT UI picker), while logged in as staff:
    `POST /api/personal_api_keys/ {"label": "migrations support", "scopes": ["batch_import_support:read"]}`.
    The key must be unscoped - keys with scoped_teams/scoped_organizations are rejected on
    root-level endpoints.
    """

    scope_object = "INTERNAL"
    required_scopes = ["batch_import_support:read"]
    permission_classes = [IsAuthenticated, IsStaffUser, APIScopePermission]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    queryset = BatchImport.objects.select_related("team").order_by("-created_at")
    serializer_class = BatchImportSupportListSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "team_id"]
    # No `id` search (icontains is unsupported on a native Postgres uuid column) - exact id
    # lookups are what `retrieve` is for.
    search_fields = ["status_message", "team__name"]
    ordering_fields = ["created_at", "updated_at", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self) -> type[BatchImportSupportListSerializer]:
        if self.action == "retrieve":
            return BatchImportSupportDetailSerializer
        return BatchImportSupportListSerializer

    def finalize_response(
        self, request: request.Request, response: response.Response, *args, **kwargs
    ) -> response.Response:
        # Staff reads of customer data should leave a trail.
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            logger.info(
                "batch_import_support_api_request",
                staff_user_id=user.id,
                action=self.action,
                query_params=dict(request.query_params),
                object_id=self.kwargs.get("pk"),
            )
        return super().finalize_response(request, response, *args, **kwargs)
