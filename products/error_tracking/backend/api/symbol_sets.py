import hashlib
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

import structlog
import posthoganalytics
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FileUploadParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.storage import object_storage

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

logger = structlog.get_logger(__name__)

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2
PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT = 60 * 5


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "storage_ptr", "failure_reason"]
        read_only_fields = ["team_id"]


@dataclass
class SymbolSetUpload:
    chunk_id: str
    release_id: str | None
    content_hash: str | None


class ErrorTrackingSymbolSetUploadSerializer(serializers.Serializer):
    chunk_id = serializers.CharField()
    release_id = serializers.CharField(allow_null=True, default=None)
    content_hash = serializers.CharField(allow_null=True, default=None)


class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer
    parser_classes = [MultiPartParser, FileUploadParser]
    scope_object_write_actions = [
        "bulk_start_upload",
        "bulk_finish_upload",
        "start_upload",
        "finish_upload",
        "destroy",
        "update",
        "create",
    ]

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id)
        params = self.request.GET.dict()
        status = params.get("status")
        order_by = params.get("order_by")

        if status == "valid":
            queryset = queryset.filter(storage_ptr__isnull=False)
        elif status == "invalid":
            queryset = queryset.filter(storage_ptr__isnull=True)

        if order_by:
            allowed_fields = ["created_at", "-created_at", "ref", "-ref"]
            if order_by in allowed_fields:
                queryset = queryset.order_by(order_by)

        return queryset

    def destroy(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        symbol_set.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def update(self, request, *args, **kwargs) -> Response:
        symbol_set = self.get_object()
        # TODO: delete file from s3
        minified = request.FILES["minified"]
        source_map = request.FILES["source_map"]
        (storage_ptr, content_hash) = upload_symbol_set(minified, source_map)
        symbol_set.storage_ptr = storage_ptr
        symbol_set.content_hash = content_hash
        symbol_set.failure_reason = None
        symbol_set.save()
        ErrorTrackingStackFrame.objects.filter(team=self.team, symbol_set=symbol_set).delete()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

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

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        chunk_id_url_map = bulk_create_symbol_sets(symbol_sets, self.team)
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

        symbol_set_ids = content_hashes.keys()
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=symbol_set_ids)

        try:
            for symbol_set in symbol_sets:
                s3_upload = None
                if symbol_set.storage_ptr:
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

                content_hash = content_hashes[str(symbol_set.id)]
                symbol_set.content_hash = content_hash
            ErrorTrackingSymbolSet.objects.bulk_update(symbol_sets, ["content_hash"])
        except Exception:
            for id in content_hashes.keys():
                # Try to clean up the symbol sets preemptively if the upload fails
                try:
                    symbol_set = ErrorTrackingSymbolSet.objects.all().filter(id=id, team=self.team).get()
                    symbol_set.delete()
                except Exception:
                    pass

            raise

        _ = posthoganalytics.capture(
            "error_tracking_symbol_set_uploaded",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"success": True}, status=status.HTTP_201_CREATED)


def create_symbol_set(
    chunk_id: str, team: Team, release_id: str | None, storage_ptr: str, content_hash: Optional[str] = None
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
            symbol_set.save()

        except ErrorTrackingSymbolSet.DoesNotExist:
            symbol_set = ErrorTrackingSymbolSet.objects.create(
                team=team,
                ref=chunk_id,
                release=release,
                storage_ptr=storage_ptr,
                content_hash=content_hash,
            )

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set=symbol_set).delete()

        return symbol_set


@posthoganalytics.scoped()
def bulk_create_symbol_sets(
    new_symbol_sets: list[SymbolSetUpload],
    team: Team,
) -> dict[str, dict[str, str]]:
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
            presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr)
            id_url_map[chunk_id] = {"presigned_url": presigned_url}
            # Note that on creation, we /do not set/ the content hash. We use content hashes included in
            # the create request only to see if we can skip updated - we set the content hash when we
            # get upload confirmation, during `bulk_finish_upload`, not before
            to_create = ErrorTrackingSymbolSet(
                team=team,
                ref=chunk_id,
                storage_ptr=storage_ptr,
                release_id=new_symbol_set_map[chunk_id].release_id,
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

            if existing.content_hash is not None and existing.content_hash != upload.content_hash:
                # If this symbol set already has a content hash, and they differ, raise. We do not support changing
                # the content of a symbol set once it's been uploaded - callers should inject a new chunk_id instead.
                # Note - this will also return an error if the upload's content hash is None. This is
                # intentional - we can't tell whether its safe to overwrite the existing content hash
                # here. This will only be the case for older CLI versions, which we expect to misbehave
                # in this code path anyway.
                raise ValidationError(
                    code="content_hash_mismatch",
                    detail=f"Symbol set {existing.ref} already exists, with different content.",
                )
            elif existing.content_hash is None:
                # If the existing set doesn't have a content hash, we can set it up for an upload, and return it
                # so the CLI will send the data to s3
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                dirty = True
            else:
                # No-op with respect to the client - the upload was done already, and the content hash matches.
                # Called out explicitly for clarity. Note we may still update this record, if the release has changed.
                pass

            if dirty:
                to_update.append(existing)

        # We update only the symbol sets we modified the release of - for all others, this is a no-op (we assume they were uploaded
        # during a prior attempt or something).
        _ = ErrorTrackingSymbolSet.objects.bulk_update(to_update, ["release", "content_hash", "storage_ptr"])

    return id_url_map


def upload_symbol_set(minified: UploadedFile, source_map: UploadedFile) -> tuple[str, str]:
    js_data = construct_js_data_object(minified.read(), source_map.read())
    return upload_content(js_data)


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


def generate_symbol_set_upload_presigned_url(file_key: str):
    return object_storage.get_presigned_post(
        file_key=file_key,
        conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
    )
