import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FileUploadParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.rate_limit import SymbolSetUploadBurstRateThrottle, SymbolSetUploadSustainedRateThrottle
from posthog.storage import object_storage

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

logger = structlog.get_logger(__name__)

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2
PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT = 60 * 5


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    release = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "last_used", "storage_ptr", "failure_reason", "release"]
        read_only_fields = ["team_id"]

    @extend_schema_field(serializers.DictField(allow_null=True, help_text="Release associated with this symbol set"))
    def get_release(self, obj):
        from products.error_tracking.backend.api.releases import ErrorTrackingReleaseSerializer

        if obj.release:
            return ErrorTrackingReleaseSerializer(obj.release).data
        return None


@dataclass
class SymbolSetUpload:
    chunk_id: str
    release_id: str | None
    content_hash: str | None


class ErrorTrackingSymbolSetUploadSerializer(serializers.Serializer):
    chunk_id = serializers.CharField()
    release_id = serializers.CharField(allow_null=True, default=None)
    content_hash = serializers.CharField(allow_null=True, default=None)


class _SymbolSetDownloadResponseSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Presigned URL to download the source map file")


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer
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

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id).select_related("release")
        params = self.request.GET.dict()
        ref = params.get("ref")
        status = params.get("status")
        order_by = params.get("order_by")

        if ref:
            queryset = queryset.filter(ref=ref)

        if status == "valid":
            queryset = queryset.filter(storage_ptr__isnull=False)
        elif status == "invalid":
            queryset = queryset.filter(storage_ptr__isnull=True)

        if order_by:
            allowed_fields = ["created_at", "-created_at", "ref", "-ref", "last_used", "-last_used"]
            if order_by in allowed_fields:
                queryset = queryset.order_by(order_by)

        return queryset

    def destroy(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        symbol_set.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_delete(self, request, **kwargs):
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(ids, list):
            return Response({"detail": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=ids)
        deleted_count, _ = symbol_sets.delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_200_OK)

    @extend_schema(
        responses={200: _SymbolSetDownloadResponseSerializer},
    )
    @action(methods=["GET"], detail=True, parser_classes=[JSONParser])
    def download(self, request, **kwargs) -> Response:
        """Return a presigned URL for downloading the symbol set's source map."""
        return self._download_symbol_set(self.get_object())

    def _download_symbol_set(self, symbol_set: ErrorTrackingSymbolSet) -> Response:
        if not symbol_set.storage_ptr:
            return Response(
                {"detail": "Symbol set has no uploaded file."},
                status=status.HTTP_404_NOT_FOUND,
            )

        presigned_url = object_storage.get_presigned_url(
            file_key=symbol_set.storage_ptr,
            expiration=3600,
        )

        if not presigned_url:
            return Response(
                {"detail": "Could not generate download URL."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"url": presigned_url}, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Fallback for non-paginated responses
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    # DEPRECATED: newer versions of the CLI use bulk uploads
    def create(self, request, *args, **kwargs) -> Response:
        # pull the symbol set reference from the query params
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

        (storage_ptr, content_hash) = upload_content(bytearray(data))
        create_symbol_set(chunk_id, self.team, release_id, storage_ptr, content_hash)

        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False)
    # DEPRECATED: we should eventually remove this once everyone is using a new enough version of the CLI
    def start_upload(self, request, **kwargs):
        chunk_id = request.query_params.get("chunk_id", None)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "start_upload"},
        )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        file_key = generate_symbol_set_file_key()
        presigned_url = object_storage.get_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        )

        symbol_set = create_symbol_set(chunk_id, self.team, release_id, file_key)

        return Response(
            {"presigned_url": presigned_url, "symbol_set_id": str(symbol_set.pk)}, status=status.HTTP_201_CREATED
        )

    @action(methods=["PUT"], detail=True, parser_classes=[JSONParser])
    def finish_upload(self, request, **kwargs):
        content_hash = request.data.get("content_hash")

        if not content_hash:
            raise ValidationError(
                code="content_hash_required",
                detail="A content hash must be provided to complete symbol set upload.",
            )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        symbol_set = self.get_object()
        s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

        if s3_upload:
            content_length = s3_upload.get("ContentLength")

            if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                symbol_set.delete()

                raise ValidationError(
                    code="file_too_large",
                    detail="The uploaded symbol set file was too large.",
                )
        else:
            raise ValidationError(
                code="file_not_found",
                detail="No file has been uploaded for the symbol set.",
            )

        if not symbol_set.content_hash:
            symbol_set.content_hash = content_hash
            symbol_set.last_used = timezone.now()
            symbol_set.save()

        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_start_upload(self, request, **kwargs):
        if request.user.pk:
            posthoganalytics.identify_context(request.user.pk)
        # Earlier ones send a list of chunk IDs, all associated with one release
        # Extract a list of chunk IDs from the request json
        chunk_ids: list[str] = request.data.get("chunk_ids") or []
        # Grab the release ID from the request json
        release_id: str | None = request.data.get("release_id", None)

        _ = posthoganalytics.capture(
            "error_tracking_symbol_set_upload_started",
            properties={"team_id": self.team.id, "endpoint": "bulk_start_upload"},
            groups=groups(self.team.organization, self.team),
        )

        # Validate symbol_sets using the serializer
        symbol_sets: list[SymbolSetUpload] = []
        if "symbol_sets" in request.data:
            chunk_serializer = ErrorTrackingSymbolSetUploadSerializer(data=request.data["symbol_sets"], many=True)
            _ = chunk_serializer.is_valid(raise_exception=True)
            symbol_sets = [SymbolSetUpload(**data) for data in chunk_serializer.validated_data]

        symbol_sets.extend([SymbolSetUpload(x, release_id, None) for x in chunk_ids])

        # force=True allows overwriting an existing symbol set whose content has changed.
        # Without it, changed-content re-uploads are silently skipped to prevent
        # accidental overwrites of production symbol sets from a local dev machine.
        force: bool = bool(request.data.get("force", False))

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        chunk_id_url_map = bulk_create_symbol_sets(
            symbol_sets, self.team, force=force, distinct_id=str(request.user.pk) if request.user.pk else None
        )
        return Response({"id_map": chunk_id_url_map}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_finish_upload(self, request, **kwargs):
        if request.user.pk:
            posthoganalytics.identify_context(request.user.pk)
        # Get the map of symbol_set_id:content_hashes
        content_hashes = request.data.get("content_hashes", {})
        if content_hashes is None:
            return Response({"detail": "content_hashes are required"}, status=status.HTTP_400_BAD_REQUEST)

        if len(content_hashes) == 0:
            # This can happen if someone re-runs an upload against a directory that's already been
            # uploaded - we'll return no new upload keys, they'll upload nothing, and then
            # we can early exit here.
            return Response({"success": True}, status=status.HTTP_201_CREATED)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        file_count = len(content_hashes)
        symbol_set_ids = content_hashes.keys()
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=symbol_set_ids)

        total_file_size = 0
        try:
            for symbol_set in symbol_sets:
                s3_upload = None
                if symbol_set.storage_ptr:
                    s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

                if s3_upload:
                    content_length = s3_upload.get("ContentLength")
                    if content_length:
                        total_file_size += content_length

                    if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                        symbol_set.delete()

                        raise ValidationError(
                            code="file_too_large",
                            detail="The uploaded symbol set file was too large.",
                        )
                else:
                    raise ValidationError(
                        code="file_not_found",
                        detail="No file has been uploaded for the symbol set.",
                    )

                content_hash = content_hashes[str(symbol_set.id)]
                symbol_set.content_hash = content_hash
                symbol_set.last_used = timezone.now()
            ErrorTrackingSymbolSet.objects.bulk_update(symbol_sets, ["content_hash", "last_used"])
        except Exception as e:
            for id in content_hashes.keys():
                # Try to clean up the symbol sets preemptively if the upload fails
                try:
                    symbol_set = ErrorTrackingSymbolSet.objects.all().filter(id=id, team=self.team).get()
                    symbol_set.delete()
                except Exception:
                    pass

            posthoganalytics.capture(
                "error_tracking_symbol_set_uploaded",
                properties={
                    "file_size": total_file_size,
                    "success": False,
                    "file_count": file_count,
                    "failure_reason": type(e).__name__,
                },
                groups=groups(self.team.organization, self.team),
            )
            raise

        posthoganalytics.capture(
            "error_tracking_symbol_set_uploaded",
            properties={
                "file_size": total_file_size,
                "success": True,
                "file_count": file_count,
            },
            groups=groups(self.team.organization, self.team),
        )

        return Response({"success": True}, status=status.HTTP_201_CREATED)


def create_symbol_set(
    chunk_id: str, team: Team, release_id: str | None, storage_ptr: str, content_hash: str | None = None
):
    if release_id:
        objects = ErrorTrackingRelease.objects.all().filter(team=team, id=release_id)
        if len(objects) < 1:
            raise ValueError(f"Unknown release: {release_id}")
        release = objects[0]
    else:
        release = None

    with transaction.atomic():
        try:
            symbol_set = ErrorTrackingSymbolSet.objects.get(team=team, ref=chunk_id)
            if symbol_set.release is None:
                symbol_set.release = release
            elif symbol_set.release != release:
                raise ValidationError(f"Symbol set has already been uploaded for a different release")
            symbol_set.storage_ptr = storage_ptr
            symbol_set.content_hash = content_hash
            symbol_set.last_used = timezone.now()
            symbol_set.save()

        except ErrorTrackingSymbolSet.DoesNotExist:
            symbol_set = ErrorTrackingSymbolSet.objects.create(
                team=team,
                ref=chunk_id,
                release=release,
                storage_ptr=storage_ptr,
                content_hash=content_hash,
                last_used=timezone.now(),
            )

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set=symbol_set).delete()

        return symbol_set


@posthoganalytics.scoped()
def bulk_create_symbol_sets(
    new_symbol_sets: list[SymbolSetUpload],
    team: Team,
    force: bool = False,
    distinct_id: str | None = None,
) -> dict[str, dict[str, str]]:
    accelerate = bool(
        distinct_id
        and posthoganalytics.feature_enabled(
            "error-tracking-s3-accelerate",
            distinct_id,
            groups={"organization": str(team.organization.id)},
            send_feature_flag_events=False,
        )
    )

    chunk_ids = [x.chunk_id for x in new_symbol_sets]

    # Check for dupes
    duplicates = [x for x in chunk_ids if chunk_ids.count(x) > 1]
    if duplicates:
        raise ValidationError(
            code="invalid_chunk_ids",
            detail=f"Duplicate chunk IDs provided: {', '.join(duplicates)}",
        )

    # Check we're using all valid release IDs
    release_ids = {ss.release_id for ss in new_symbol_sets if ss.release_id}
    fetched_releases = {str(r.id) for r in ErrorTrackingRelease.objects.all().filter(team=team, pk__in=release_ids)}
    for release_id in release_ids:
        if release_id not in fetched_releases:
            raise ValidationError(
                code="invalid_release_id",
                detail=f"Unknown release ID provided: {release_id}",
            )

    id_url_map: dict[str, dict[str, str]] = {}
    new_symbol_set_map = {x.chunk_id: x for x in new_symbol_sets}

    with transaction.atomic():
        existing_symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(team=team, ref__in=chunk_ids))
        existing_symbol_set_refs = [s.ref for s in existing_symbol_sets]
        missing_sets = list(set(chunk_ids) - set(existing_symbol_set_refs))

        symbol_sets_to_be_created = []
        for chunk_id in missing_sets:
            storage_ptr = generate_symbol_set_file_key()
            presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
            id_url_map[chunk_id] = {"presigned_url": presigned_url}
            # Note that on creation, we /do not set/ the content hash. We use content hashes included in
            # the create request only to see if we can skip updated - we set the content hash when we
            # get upload confirmation, during `bulk_finish_upload`, not before
            to_create = ErrorTrackingSymbolSet(
                team=team,
                ref=chunk_id,
                storage_ptr=storage_ptr,
                release_id=new_symbol_set_map[chunk_id].release_id,
                last_used=timezone.now(),
            )
            symbol_sets_to_be_created.append(to_create)

        # create missing symbol sets
        created_symbol_sets = ErrorTrackingSymbolSet.objects.bulk_create(symbol_sets_to_be_created)

        for symbol_set in created_symbol_sets:
            id_url_map[symbol_set.ref]["symbol_set_id"] = str(symbol_set.pk)

        # update existing symbol sets
        to_update = []
        for existing in existing_symbol_sets:
            upload = new_symbol_set_map[existing.ref]
            dirty = False

            # Allow adding an "orphan" symbol set to a release, but not
            # moving symbols sets between releases
            if upload.release_id:
                if existing.release_id is None:
                    existing.release_id = upload.release_id
                    dirty = True
                elif str(existing.release_id) != upload.release_id:
                    raise ValidationError(
                        code="release_id_mismatch",
                        detail=f"Symbol set {existing.ref} already has a release ID",
                    )

            if upload.content_hash is None:
                if existing.content_hash is not None:
                    # Old CLI (no content hash) trying to re-upload a symbol set
                    # that was already fully uploaded. We can't determine safety,
                    # so reject rather than silently overwrite production data.
                    raise ValidationError(
                        code="content_hash_required",
                        detail=f"Symbol set {existing.ref} already has content; provide a content_hash to update it.",
                    )
                # Both sides have no hash: this is a pending upload being restarted.
                # Issue a fresh presigned URL so the client can retry.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                dirty = True
            elif existing.content_hash is None:
                # Existing record has no hash (pending upload or uploaded by old CLI
                # without hash support). Allow the new upload to supply one.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                dirty = True
            elif existing.content_hash == upload.content_hash:
                # Content is identical — no upload needed.
                # (We may still update the release below if it changed.)
                pass
            elif not force:
                # Content has changed but the caller did not pass force=True.
                # Silently skip to prevent accidental overwrites of production
                # symbol sets from a local development machine.
                logger.warning(
                    "symbol_set_content_changed_skipped",
                    ref=existing.ref,
                    team_id=team.id,
                )
            else:
                # force=True: content has changed and the caller explicitly
                # requested an overwrite. Issue a new presigned URL and clear
                # the old content hash so bulk_finish_upload stores the new one.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                existing.content_hash = None  # will be set by bulk_finish_upload
                dirty = True

            if dirty:
                to_update.append(existing)

        # We update only the symbol sets we modified the release of - for all others, this is a no-op (we assume they were uploaded
        # during a prior attempt or something).
        _ = ErrorTrackingSymbolSet.objects.bulk_update(to_update, ["release", "content_hash", "storage_ptr"])

    return id_url_map


def upload_content(content: bytearray) -> tuple[str, str]:
    content_hash = hashlib.sha512(content).hexdigest()

    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    if len(content) > ONE_HUNDRED_MEGABYTES:
        raise ValidationError(
            code="file_too_large", detail="Combined source map and symbol set must be less than 100MB"
        )

    upload_path = generate_symbol_set_file_key()
    object_storage.write(upload_path, bytes(content))
    return (upload_path, content_hash)


def construct_js_data_object(minified: bytes, source_map: bytes) -> bytearray:
    # See rust/cymbal/hacks/js_data.rs
    data = bytearray()
    data.extend(JS_DATA_MAGIC)
    data.extend(JS_DATA_VERSION.to_bytes(4, "little"))
    data.extend((JS_DATA_TYPE_SOURCE_AND_MAP).to_bytes(4, "little"))
    # TODO - this doesn't seem right?
    s_bytes = minified.decode("utf-8").encode("utf-8")
    data.extend(len(s_bytes).to_bytes(8, "little"))
    data.extend(s_bytes)
    sm_bytes = source_map.decode("utf-8").encode("utf-8")
    data.extend(len(sm_bytes).to_bytes(8, "little"))
    data.extend(sm_bytes)
    return data


def generate_symbol_set_file_key():
    return f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"


def generate_symbol_set_upload_presigned_url(file_key: str, *, accelerate: bool = False):
    if accelerate:
        return object_storage.get_accelerated_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
            expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
        )
    return object_storage.get_presigned_post(
        file_key=file_key,
        conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
    )
