import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import pagination, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FileUploadParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.rate_limit import SymbolSetUploadBurstRateThrottle, SymbolSetUploadSustainedRateThrottle

from products.error_tracking.backend.facade import (
    contracts,
    symbol_sets as symbol_sets_facade,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade


class ErrorTrackingSymbolSetSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.ErrorTrackingSymbolSet


class ErrorTrackingSymbolSetUploadSerializer(serializers.Serializer):
    chunk_id = serializers.CharField(help_text="Symbol set reference to upload.")
    release_id = serializers.CharField(
        allow_null=True,
        default=None,
        help_text="Optional error tracking release ID associated with this symbol set.",
    )
    content_hash = serializers.CharField(
        allow_null=True,
        default=None,
        help_text="Optional hash of the symbol set content, used to skip unchanged uploads.",
    )


class ErrorTrackingSymbolSetFinishUploadSerializer(serializers.Serializer):
    content_hash = serializers.CharField(help_text="Hash of the uploaded symbol set content.")


class ErrorTrackingSymbolSetBulkDeleteSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Symbol set IDs to delete.",
    )


class ErrorTrackingSymbolSetBulkStartUploadSerializer(serializers.Serializer):
    chunk_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Legacy list of symbol set references to upload, all associated with `release_id`.",
    )
    release_id = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional error tracking release ID used with `chunk_ids`.",
    )
    symbol_sets = ErrorTrackingSymbolSetUploadSerializer(
        many=True,
        required=False,
        help_text="Symbol sets to upload with per-symbol release IDs and content hashes.",
    )
    force = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to overwrite uploaded symbol sets whose content hash changed.",
    )
    skip_on_conflict = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to skip uploaded symbol sets whose content hash changed instead of failing.",
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("force") and attrs.get("skip_on_conflict"):
            raise ValidationError(
                code="invalid_conflict_handling",
                detail="Use either force or skip_on_conflict, not both.",
            )
        return attrs


class ErrorTrackingSymbolSetBulkFinishUploadSerializer(serializers.Serializer):
    content_hashes = serializers.DictField(
        child=serializers.CharField(),
        help_text="Map of symbol set ID to uploaded content hash.",
    )


class ErrorTrackingSymbolSetListQuerySerializer(serializers.Serializer):
    ref = serializers.CharField(
        required=False,
        help_text="Exact symbol set reference to filter by.",
    )
    search = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring search across reference, release version, release project, and release commit SHA.",
    )
    status = serializers.ChoiceField(
        required=False,
        default="all",
        choices=["all", "valid", "invalid"],
        help_text="Upload status filter: `valid` has an uploaded file, `invalid` is missing a file, `all` returns both.",
    )
    order_by = serializers.ChoiceField(
        required=False,
        choices=["created_at", "-created_at", "ref", "-ref", "last_used", "-last_used"],
        help_text="Sort order for symbol sets. Prefix with `-` for descending order.",
    )


class _SymbolSetDownloadResponseSerializer(serializers.Serializer):
    url = serializers.URLField(
        help_text="Presigned URL to download the source map file. Use immediately; expires after one hour."
    )


class ErrorTrackingSymbolSetPagination(pagination.LimitOffsetPagination):
    max_limit = 100


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSymbolSetSerializer
    pagination_class = ErrorTrackingSymbolSetPagination
    parser_classes = [MultiPartParser, FileUploadParser]
    throttle_classes = [SymbolSetUploadBurstRateThrottle, SymbolSetUploadSustainedRateThrottle]
    scope_object_read_actions = ["list", "retrieve", "download"]
    scope_object_write_actions = [
        "bulk_start_upload",
        "bulk_finish_upload",
        "start_upload",
        "finish_upload",
        "destroy",
        "bulk_delete",
        "create",
    ]

    @extend_schema(parameters=[ErrorTrackingSymbolSetListQuerySerializer])
    def list(self, request: Request, *args, **kwargs) -> Response:
        query = ErrorTrackingSymbolSetListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = dict(query.validated_data)
        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: symbol_sets_facade.list_symbol_sets(
                self.team.id,
                ref=params.get("ref"),
                search=params.get("search"),
                symbol_set_status=params.get("status"),
                order_by=params.get("order_by"),
                limit=limit,
                offset=offset,
            ),
        )

    def retrieve(self, request: Request, *args, pk=None, **kwargs) -> Response:
        symbol_set = symbol_sets_facade.get_symbol_set(self.team.id, pk)
        if symbol_set is None:
            raise NotFound()
        return Response(self.get_serializer(symbol_set).data)

    # The serializer is entirely read-only, so PUT/PATCH cannot change anything. Keep the routes
    # (a client may still call them) but hide them from the spec so generated clients don't surface
    # unusable methods.
    @extend_schema(exclude=True)
    def update(self, request: Request, *args, pk=None, **kwargs) -> Response:
        return self._retrieve_unchanged(pk)

    @extend_schema(exclude=True)
    def partial_update(self, request: Request, *args, pk=None, **kwargs) -> Response:
        return self._retrieve_unchanged(pk)

    def _retrieve_unchanged(self, pk) -> Response:
        symbol_set = symbol_sets_facade.get_symbol_set(self.team.id, pk)
        if symbol_set is None:
            raise NotFound()
        return Response(self.get_serializer(symbol_set).data)

    def destroy(self, request: Request, *args, pk=None, **kwargs) -> Response:
        if not symbol_sets_facade.delete_symbol_set(self.team.id, pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=ErrorTrackingSymbolSetBulkDeleteSerializer)
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_delete(self, request: Request, **kwargs) -> Response:
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(ids, list):
            return Response({"detail": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        deleted_count = symbol_sets_facade.bulk_delete_symbol_sets(self.team.id, ids)
        return Response({"deleted": deleted_count}, status=status.HTTP_200_OK)

    @extend_schema(responses={200: _SymbolSetDownloadResponseSerializer})
    @action(methods=["GET"], detail=True, parser_classes=[JSONParser])
    def download(self, request: Request, *args, pk=None, **kwargs) -> Response:
        """Return a presigned URL for downloading the symbol set's source map."""
        try:
            result = symbol_sets_facade.get_download(self.team.id, pk)
        except symbol_sets_facade.SymbolSetNotFoundError:
            raise NotFound()

        if not result.has_file:
            return Response({"detail": "Symbol set has no uploaded file."}, status=status.HTTP_404_NOT_FOUND)
        if not result.url:
            return Response(
                {"detail": "Could not generate download URL."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response({"url": result.url}, status=status.HTTP_200_OK)

    @extend_schema(exclude=True)  # deprecated; serializer has no settable fields, hidden from typed clients
    def create(self, request: Request, *args, **kwargs) -> Response:
        chunk_id = request.query_params.get("chunk_id", None)
        multipart = request.query_params.get("multipart", False)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "create"},
        )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        if multipart:
            data = bytearray()
            for chunk in request.FILES["file"].chunks():
                data.extend(chunk)
        else:
            # legacy: older versions of the CLI did not use multipart uploads
            # file added to the request data by the FileUploadParser
            data = request.data["file"].read()

        symbol_sets_facade.create_deprecated_symbol_set(self.team, chunk_id, release_id, bytearray(data))

        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    # DEPRECATED: we should eventually remove this once everyone is using a new enough version of the CLI
    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False)
    def start_upload(self, request: Request, **kwargs) -> Response:
        chunk_id = request.query_params.get("chunk_id", None)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "start_upload"},
        )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        presigned_url, symbol_set_id = symbol_sets_facade.start_deprecated_upload(self.team, chunk_id, release_id)

        return Response(
            {"presigned_url": presigned_url, "symbol_set_id": symbol_set_id}, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=ErrorTrackingSymbolSetFinishUploadSerializer)
    @action(methods=["PUT"], detail=True, parser_classes=[JSONParser])
    def finish_upload(self, request: Request, *args, pk=None, **kwargs) -> Response:
        content_hash = request.data.get("content_hash")

        if not content_hash:
            raise ValidationError(
                code="content_hash_required",
                detail="A content hash must be provided to complete symbol set upload.",
            )

        try:
            symbol_sets_facade.finish_upload(self.team.id, pk, content_hash)
        except symbol_sets_facade.SymbolSetNotFoundError:
            raise NotFound()

        return Response({"success": True}, status=status.HTTP_200_OK)

    @extend_schema(request=ErrorTrackingSymbolSetBulkStartUploadSerializer)
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_start_upload(self, request: Request, **kwargs) -> Response:
        if request.user.pk:
            posthoganalytics.identify_context(str(request.user.pk))

        upload_serializer = ErrorTrackingSymbolSetBulkStartUploadSerializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        upload_data = upload_serializer.validated_data

        force: bool = upload_data["force"]
        skip_on_conflict: bool = upload_data["skip_on_conflict"]

        posthoganalytics.capture(
            "error_tracking_symbol_set_upload_started",
            properties={
                "team_id": self.team.id,
                "endpoint": "bulk_start_upload",
                "force": force,
                "skip_on_conflict": skip_on_conflict,
            },
            groups=groups(self.team.organization, self.team),
        )

        id_map = symbol_sets_facade.bulk_start_upload(
            self.team,
            symbol_sets=list(upload_data.get("symbol_sets", [])),
            chunk_ids=list(upload_data.get("chunk_ids") or []),
            release_id=upload_data.get("release_id", None),
            force=force,
            skip_on_conflict=skip_on_conflict,
        )
        return Response({"id_map": id_map}, status=status.HTTP_201_CREATED)

    @extend_schema(request=ErrorTrackingSymbolSetBulkFinishUploadSerializer)
    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_finish_upload(self, request: Request, **kwargs) -> Response:
        if request.user.pk:
            posthoganalytics.identify_context(str(request.user.pk))
        content_hashes = request.data.get("content_hashes", {})
        if content_hashes is None:
            return Response({"detail": "content_hashes are required"}, status=status.HTTP_400_BAD_REQUEST)

        if len(content_hashes) == 0:
            # This can happen if someone re-runs an upload against a directory that's already been
            # uploaded - we'll return no new upload keys, they'll upload nothing, and then
            # we can early exit here.
            return Response({"success": True}, status=status.HTTP_201_CREATED)

        symbol_sets_facade.bulk_finish_upload(self.team, content_hashes)

        return Response({"success": True}, status=status.HTTP_201_CREATED)
