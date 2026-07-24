"""Symbol set storage, ORM and upload operations for error tracking.

These encapsulate the object-storage interactions, transaction boundaries and upload
analytics that previously lived in the presentation layer, so the views can stay thin
(parse -> facade -> serialize). The DRF ``ValidationError`` codes raised here are part of
the CLI-facing upload contract and are surfaced verbatim by the views.
"""

import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Q

import structlog
import posthoganalytics
from rest_framework.exceptions import ValidationError

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.storage import object_storage

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

logger = structlog.get_logger(__name__)

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT = 60 * 5


class SymbolSetNotFoundError(Exception):
    pass


@dataclass
class SymbolSetUpload:
    chunk_id: str
    release_id: str | None
    content_hash: str | None


def _extract_failure_code(error_codes: object) -> str | None:
    if isinstance(error_codes, str):
        return error_codes

    if isinstance(error_codes, list):
        for error_code in error_codes:
            failure_code = _extract_failure_code(error_code)
            if failure_code:
                return failure_code

    if isinstance(error_codes, dict):
        for error_code in error_codes.values():
            failure_code = _extract_failure_code(error_code)
            if failure_code:
                return failure_code

    return None


def _get_failure_code(exception: Exception) -> str | None:
    if isinstance(exception, ValidationError):
        return _extract_failure_code(exception.get_codes())

    return None


def generate_symbol_set_file_key() -> str:
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


def create_symbol_set(
    chunk_id: str, team: Team, release_id: str | None, storage_ptr: str, content_hash: str | None = None
) -> ErrorTrackingSymbolSet:
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
                raise ValidationError("Symbol set has already been uploaded for a different release")
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


@posthoganalytics.scoped(capture_exceptions=False)
def bulk_create_symbol_sets(
    new_symbol_sets: list[SymbolSetUpload],
    team: Team,
    force: bool = False,
    skip_on_conflict: bool = False,
    distinct_id: str | None = None,
    skip_release_on_conflict: bool = False,
) -> dict[str, dict[str, str]]:
    try:
        return _bulk_create_symbol_sets(
            new_symbol_sets,
            team,
            force=force,
            skip_on_conflict=skip_on_conflict,
            distinct_id=distinct_id,
            skip_release_on_conflict=skip_release_on_conflict,
        )
    except ValidationError as e:
        # Upload-contract rejections are expected 400s the CLI knows how to handle;
        # track them as analytics instead of capturing them as exceptions.
        posthoganalytics.capture(
            "error_tracking_symbol_set_upload_rejected",
            properties={
                "file_count": len(new_symbol_sets),
                "failure_code": _get_failure_code(e),
            },
            groups=groups(team.organization, team),
        )
        raise
    except Exception as e:
        posthoganalytics.capture_exception(e)
        raise


def _bulk_create_symbol_sets(
    new_symbol_sets: list[SymbolSetUpload],
    team: Team,
    force: bool,
    skip_on_conflict: bool,
    distinct_id: str | None,
    skip_release_on_conflict: bool,
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

            # Allow adding an "orphan" symbol set to a release, but never move a
            # symbol set between releases - that would re-attribute existing stack
            # traces. When the conflict is benign (identical content, e.g. an
            # unchanged artifact rebuilt under a new release) or the caller opted
            # in, keep the existing association instead of failing the whole batch.
            if upload.release_id:
                if existing.release_id is None:
                    existing.release_id = upload.release_id
                    dirty = True
                elif str(existing.release_id) != upload.release_id:
                    content_unchanged = upload.content_hash is not None and existing.content_hash == upload.content_hash
                    if content_unchanged or skip_release_on_conflict:
                        logger.warning(
                            "symbol_set_release_conflict_skipped",
                            ref=existing.ref,
                            team_id=team.id,
                        )
                    else:
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
            elif force:
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
            elif skip_on_conflict:
                # Content has changed, but the caller explicitly asked to keep
                # the already-uploaded symbol set.
                logger.warning(
                    "symbol_set_content_changed_skipped",
                    ref=existing.ref,
                    team_id=team.id,
                )
            else:
                raise ValidationError(
                    code="content_hash_mismatch",
                    detail=f"Symbol set {existing.ref} already exists with different content.",
                )

            if dirty:
                to_update.append(existing)

        # We update only the symbol sets we modified the release of - for all others, this is a no-op (we assume they were uploaded
        # during a prior attempt or something).
        ErrorTrackingSymbolSet.objects.bulk_update(to_update, ["release", "content_hash", "storage_ptr"])

    return id_url_map


def list_symbol_sets(
    team_id: int,
    *,
    ref: str | None,
    search: str | None,
    symbol_set_status: str | None,
    order_by: str | None,
    limit: int | None,
    offset: int,
) -> tuple[list[ErrorTrackingSymbolSet], int]:
    queryset = ErrorTrackingSymbolSet.objects.filter(team_id=team_id).select_related("release")

    if ref:
        queryset = queryset.filter(ref=ref)

    if search:
        queryset = queryset.filter(
            Q(ref__icontains=search)
            | Q(release__version__icontains=search)
            | Q(release__project__icontains=search)
            | Q(release__metadata__git__commit_id__icontains=search)
        )

    if symbol_set_status == "valid":
        queryset = queryset.filter(storage_ptr__isnull=False)
    elif symbol_set_status == "invalid":
        queryset = queryset.filter(storage_ptr__isnull=True)

    if order_by:
        queryset = queryset.order_by(order_by)

    total = queryset.count()
    rows = queryset if limit is None else queryset[offset : offset + limit]
    return list(rows), total


def get_symbol_set(team_id: int, symbol_set_id: str) -> ErrorTrackingSymbolSet | None:
    return ErrorTrackingSymbolSet.objects.filter(team_id=team_id, id=symbol_set_id).select_related("release").first()


def _get_or_raise(team_id: int, symbol_set_id: str) -> ErrorTrackingSymbolSet:
    symbol_set = (
        ErrorTrackingSymbolSet.objects.filter(team_id=team_id, id=symbol_set_id).select_related("release").first()
    )
    if symbol_set is None:
        raise SymbolSetNotFoundError
    return symbol_set


def delete_symbol_set(team_id: int, symbol_set_id: str) -> bool:
    symbol_set = ErrorTrackingSymbolSet.objects.filter(team_id=team_id, id=symbol_set_id).first()
    if symbol_set is None:
        return False
    symbol_set.delete()
    return True


def bulk_delete_symbol_sets(team_id: int, ids: list[str]) -> int:
    deleted_count, _ = ErrorTrackingSymbolSet.objects.filter(team_id=team_id, id__in=ids).delete()
    return deleted_count


def get_download_url(team_id: int, symbol_set_id: str) -> tuple[bool, str | None]:
    """Returns ``(has_file, presigned_url)`` for a team-scoped symbol set.

    Raises ``SymbolSetNotFoundError`` if the symbol set does not exist for the team.
    ``has_file`` is False when no source map has been uploaded; ``presigned_url`` is None
    when the URL could not be generated.
    """
    symbol_set = _get_or_raise(team_id, symbol_set_id)
    if not symbol_set.storage_ptr:
        return False, None
    presigned_url = object_storage.get_presigned_url(file_key=symbol_set.storage_ptr, expiration=3600)
    return True, presigned_url


def create_deprecated_symbol_set(team: Team, chunk_id: str, release_id: str | None, data: bytearray) -> None:
    (storage_ptr, content_hash) = upload_content(data)
    create_symbol_set(chunk_id, team, release_id, storage_ptr, content_hash)


def start_deprecated_upload(team: Team, chunk_id: str, release_id: str | None) -> tuple[object, str]:
    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    file_key = generate_symbol_set_file_key()
    presigned_url = object_storage.get_presigned_post(
        file_key=file_key,
        conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
    )

    symbol_set = create_symbol_set(chunk_id, team, release_id, file_key)
    return presigned_url, str(symbol_set.pk)


def finish_upload(team_id: int, symbol_set_id: str, content_hash: str) -> None:
    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    symbol_set = _get_or_raise(team_id, symbol_set_id)
    s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr) if symbol_set.storage_ptr else None

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


def bulk_start_upload(
    team: Team,
    *,
    symbol_sets: list[dict],
    chunk_ids: list[str],
    release_id: str | None,
    force: bool,
    skip_on_conflict: bool,
    distinct_id: str | None,
    skip_release_on_conflict: bool = False,
) -> dict[str, dict[str, str]]:
    uploads = [SymbolSetUpload(**data) for data in symbol_sets]
    uploads.extend([SymbolSetUpload(chunk_id, release_id, None) for chunk_id in chunk_ids])

    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    return bulk_create_symbol_sets(
        uploads,
        team,
        force=force,
        skip_on_conflict=skip_on_conflict,
        distinct_id=distinct_id,
        skip_release_on_conflict=skip_release_on_conflict,
    )


def bulk_finish_upload(team: Team, content_hashes: dict[str, str]) -> None:
    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    file_count = len(content_hashes)
    symbol_set_ids = set(content_hashes.keys())
    total_file_size = 0
    try:
        symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(team=team, id__in=symbol_set_ids))
        found_symbol_set_ids = {str(symbol_set.id) for symbol_set in symbol_sets}
        missing_symbol_set_ids = symbol_set_ids - found_symbol_set_ids
        if missing_symbol_set_ids:
            raise ValidationError(
                code="symbol_set_not_found",
                detail=f"Unknown symbol set IDs: {', '.join(sorted(missing_symbol_set_ids))}",
            )

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
        ErrorTrackingSymbolSet.objects.bulk_update(symbol_sets, ["content_hash"])
    except Exception as e:
        posthoganalytics.capture(
            "error_tracking_symbol_set_uploaded",
            properties={
                "file_size": total_file_size,
                "success": False,
                "file_count": file_count,
                "failure_reason": type(e).__name__,
                "failure_code": _get_failure_code(e),
            },
            groups=groups(team.organization, team),
        )
        raise

    posthoganalytics.capture(
        "error_tracking_symbol_set_uploaded",
        properties={
            "file_size": total_file_size,
            "success": True,
            "file_count": file_count,
        },
        groups=groups(team.organization, team),
    )
