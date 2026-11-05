"""Uploaded files of push device tokens, imported into one push channel by a background task."""

import io
import csv
import json
import time
import uuid
import zlib
from datetime import datetime, timedelta
from typing import TypedDict

from django.db import IntegrityError, transaction
from django.utils import timezone

from structlog import get_logger

from posthog.api.integration_push_tokens import (
    MAX_DISTINCT_ID_BYTES,
    MAX_SUBSCRIPTIONS_PER_REQUEST,
    TOKEN_SUFFIX_LENGTH,
    PushTokenImportFailure,
    PushTokenImportFailureReason,
    import_push_tokens,
    push_channel_app_id,
)
from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.storage import object_storage

from products.workflows.backend.facade.contracts import (
    PushTokenImportInvalid,
    PushTokenImportNotFound,
    PushTokenImportRecord,
    PushTokenImportRowFailure,
)
from products.workflows.backend.facade.enums import PushTokenImportRowFailureReason, PushTokenImportStatus
from products.workflows.backend.models.push_token_import import PushTokenImport

logger = get_logger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024
BATCH_SIZE = MAX_SUBSCRIPTIONS_PER_REQUEST
# One task run sends this many batches and then queues the next run, so a worker restart loses little.
BATCHES_PER_TASK = 20
# The result lists this many failed lines. The counts cover every line.
MAX_STORED_FAILURES = 1000
# Devices of people who don't exist yet stay stored this long, so they can be imported with new persons.
UNKNOWN_PERSON_DEVICES_KEPT_FOR = timedelta(hours=24)
# Counted from the upload, so it covers the time the import itself takes.
EXPIRY_MARGIN = timedelta(hours=1)
# A task run takes seconds, so this much quiet means the worker stopped, for example in a deploy.
STALL_CHECK_EVERY = timedelta(minutes=5)
DELETE_RETRY_AFTER = timedelta(hours=1)
NOT_STORED_ATTEMPTS = 3
NOT_STORED_RETRY_SECONDS = 2
STALLED_AFTER = timedelta(minutes=5)
MAX_RESUMES = 3

# Blank lines are a byte each, so this bounds the work a file within the size limit can cause.
MAX_FILE_LINES = 400_000
MAX_DEVICE_TOKEN_LENGTH = 4096
_DISTINCT_ID_COLUMN = "distinct_id"
_DEVICE_TOKEN_COLUMN = "device_token"
_STORAGE_FOLDER = "workflows_push_token_imports"
_PUSH_KINDS = ("apns", "firebase")


class StagedDevice(TypedDict):
    line: int
    distinct_id: str
    device_token: str


@frozen
class ParsedPushTokenFile:
    devices: list[StagedDevice]
    rejected: list[PushTokenImportRowFailure]
    rejected_lines: int
    duplicate_lines: int


@frozen
class _Columns:
    distinct_id: int
    device_token: int


class _DeviceCipher(EncryptedFieldMixin):
    pass


def parse_push_token_csv(content: bytes) -> ParsedPushTokenFile:
    """Reads a CSV with a header row into devices. Raises `PushTokenImportInvalid` when the file can't be used."""
    # Decoding while reading keeps a second, wider copy of the whole file out of memory.
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(content), encoding="utf-8-sig", newline=""), strict=True)
    devices: list[StagedDevice] = []
    rejected: list[PushTokenImportRowFailure] = []
    rejected_lines = 0
    seen: set[tuple[str, str]] = set()
    duplicate_lines = 0
    has_data = False
    columns: _Columns | None = None
    try:
        for cells in reader:
            # A quoted value can span lines, so the record's line is where it started.
            line = reader.line_num - sum(cell.count("\n") for cell in cells)
            if reader.line_num > MAX_FILE_LINES:
                raise PushTokenImportInvalid(
                    f"This file has more than {MAX_FILE_LINES:,} lines. "
                    "Split it into smaller files and import them one at a time."
                )
            if columns is None:
                columns = _columns(cells)
                continue
            if all(not cell.strip() for cell in cells):
                continue
            has_data = True
            distinct_id = _cell(cells, columns.distinct_id)
            device_token = _cell(cells, columns.device_token)
            if problem := _row_problem(distinct_id, device_token):
                rejected_lines += 1
                if len(rejected) < MAX_STORED_FAILURES:
                    rejected.append(
                        PushTokenImportRowFailure(
                            line=line,
                            distinct_id=distinct_id.replace("\x00", ""),
                            device_token_suffix=device_token[-TOKEN_SUFFIX_LENGTH:].replace("\x00", ""),
                            reason=PushTokenImportRowFailureReason.INVALID_ROW,
                            detail=problem,
                        )
                    )
                continue
            key = (distinct_id, device_token)
            if key in seen:
                duplicate_lines += 1
                continue
            seen.add(key)
            devices.append({"line": line, "distinct_id": distinct_id, "device_token": device_token})
    except UnicodeDecodeError:
        raise PushTokenImportInvalid('This file isn\'t saved as UTF-8. Save it as "CSV UTF-8" and upload it again.')
    except csv.Error as error:
        raise PushTokenImportInvalid(f"Line {reader.line_num} of the file can't be read: {error}.")
    if columns is None:
        raise PushTokenImportInvalid("The file is empty.")
    if not has_data:
        raise PushTokenImportInvalid("The file has no devices in it, only the column names.")
    return ParsedPushTokenFile(
        devices=devices, rejected=rejected, rejected_lines=rejected_lines, duplicate_lines=duplicate_lines
    )


def _columns(header: list[str]) -> _Columns:
    columns = [cell.strip().lower() for cell in header]
    if _DISTINCT_ID_COLUMN not in columns or _DEVICE_TOKEN_COLUMN not in columns:
        raise PushTokenImportInvalid(
            "The first line of the file must name the columns, and it needs a distinct_id column and a device_token column."
        )
    return _Columns(distinct_id=columns.index(_DISTINCT_ID_COLUMN), device_token=columns.index(_DEVICE_TOKEN_COLUMN))


def start_push_token_import(
    *,
    team: Team,
    user: User | None,
    integration_id: int,
    content: bytes,
    create_missing_persons: bool,
) -> PushTokenImportRecord:
    _push_channel(team.id, integration_id)
    if len(content) > MAX_FILE_BYTES:
        raise PushTokenImportInvalid(
            f"This file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
            "Split it into smaller files and import them one at a time."
        )
    parsed = parse_push_token_csv(content)
    if not parsed.devices:
        raise PushTokenImportInvalid(
            "None of the lines in the file can be imported. Fix them and upload the file again."
        )
    return _create_import(
        team=team,
        user=user,
        integration_id=integration_id,
        devices=parsed.devices,
        create_missing_persons=create_missing_persons,
        rejected=parsed.rejected,
        rejected_lines=parsed.rejected_lines,
        duplicate_lines=parsed.duplicate_lines,
    )


def import_unknown_persons(*, team: Team, user: User | None, import_id: uuid.UUID) -> PushTokenImportRecord:
    """Starts a second import of the devices whose distinct ID had no person, creating those persons."""
    previous = _get(team.id, import_id)
    if not _can_import_unknown_persons(previous):
        raise PushTokenImportInvalid(
            "These devices can't be imported again. Upload the file again to import them with new persons."
        )
    storage_key = previous.storage_key
    unknown_lines = set(previous.unknown_person_lines)
    devices = [device for device in _read_devices(storage_key) if device["line"] in unknown_lines]
    if not devices:
        raise PushTokenImportInvalid(
            "These devices can't be imported again. Upload the file again to import them with new persons."
        )
    # Only one import per channel runs at a time, so a second click fails here instead of importing twice.
    record = _create_import(
        team=team,
        user=user,
        integration_id=previous.integration_id,
        devices=devices,
        create_missing_persons=True,
        rejected=[],
        rejected_lines=0,
        duplicate_lines=0,
    )
    # Cleared before the delete, so a failed delete can't let these devices be imported a second time.
    PushTokenImport.objects.for_team(team.id).filter(id=import_id).update(
        unknown_person_lines=[], updated_at=timezone.now()
    )
    _release_devices(team.id, import_id, storage_key)
    return record


def get_push_token_import(team_id: int, import_id: uuid.UUID) -> PushTokenImportRecord:
    return _record(_get(team_id, import_id))


def latest_push_token_import(team_id: int, integration_id: int) -> PushTokenImportRecord | None:
    latest = PushTokenImport.objects.for_team(team_id).filter(integration_id=integration_id).order_by("-created_at")
    found = latest.first()
    return _record(found) if found else None


def cancel_push_token_import(team_id: int, import_id: uuid.UUID) -> PushTokenImportRecord:
    """Stops a running import after the batch it is sending. Devices already sent stay imported.

    The task sets `finished_at` once that batch is counted, so the import reads as stopping until then.
    """
    PushTokenImport.objects.for_team(team_id).filter(id=import_id, status=PushTokenImportStatus.RUNNING).update(
        status=PushTokenImportStatus.CANCELLED, updated_at=timezone.now()
    )
    return get_push_token_import(team_id, import_id)


def run_push_token_import_batches(team_id: int, import_id: uuid.UUID) -> bool:
    """Sends the next batches of a running import. Returns True when batches are left for another run."""
    job = PushTokenImport.objects.for_team(team_id).filter(id=import_id).first()
    if job is None:
        return False
    if job.status != PushTokenImportStatus.RUNNING:
        _end_stopped(job)
        return False
    try:
        integration = _push_channel(team_id, job.integration_id)
    except PushTokenImportInvalid as error:
        fail_push_token_import(team_id, import_id, str(error))
        return False
    api_token = Team.objects.only("api_token").get(id=team_id).api_token
    devices = _read_devices(job.storage_key)
    if not devices:
        fail_push_token_import(
            team_id,
            import_id,
            "PostHog couldn't read the stored devices, so the import stopped. Upload the file again.",
        )
        return False

    for _ in range(BATCHES_PER_TASK):
        start = job.processed_devices
        if start >= len(devices):
            _finish(job)
            return False
        batch = devices[start : start + BATCH_SIZE]
        imported, failed = _send_batch(
            integration,
            batch,
            api_token,
            create_missing_persons=job.create_missing_persons,
            # A batch sent again after a worker restart reuses its event IDs, so its copies can be deduplicated.
            import_id=uuid.uuid5(job.id, str(start)),
            timestamp=job.created_at,
        )
        for device, failure in failed:
            line = device["line"]
            if failure.reason == PushTokenImportFailureReason.UNKNOWN_PERSON:
                job.unknown_person_lines.append(line)
            if len(job.failures) < MAX_STORED_FAILURES:
                job.failures.append(
                    _failure_json(
                        PushTokenImportRowFailure(
                            line=line,
                            distinct_id=failure.distinct_id,
                            device_token_suffix=failure.device_token_suffix,
                            reason=PushTokenImportRowFailureReason(failure.reason),
                            detail=failure.detail,
                        )
                    )
                )
        job.processed_devices = start + len(batch)
        job.imported_devices += imported
        job.failed_devices += len(failed)
        # Matching the progress read at the start means a cancel or a second worker stops this one.
        saved = (
            PushTokenImport.objects.for_team(team_id)
            .filter(id=import_id, status=PushTokenImportStatus.RUNNING, processed_devices=start)
            .update(
                processed_devices=job.processed_devices,
                imported_devices=job.imported_devices,
                failed_devices=job.failed_devices,
                failures=job.failures,
                unknown_person_lines=job.unknown_person_lines,
                updated_at=timezone.now(),
            )
        )
        if not saved:
            # A stop that lands mid-batch leaves the batch's devices stored, so the stopped import still counts them.
            PushTokenImport.objects.for_team(team_id).filter(
                id=import_id, status=PushTokenImportStatus.CANCELLED, processed_devices=start
            ).update(
                processed_devices=job.processed_devices,
                imported_devices=job.imported_devices,
                failed_devices=job.failed_devices,
                failures=job.failures,
                unknown_person_lines=job.unknown_person_lines,
                updated_at=timezone.now(),
            )
            job.refresh_from_db()
            _end_stopped(job)
            return False
    if job.processed_devices >= len(devices):
        _finish(job)
        return False
    return True


def _send_batch(
    integration: IntegrationRecord,
    batch: list[StagedDevice],
    api_token: str,
    *,
    create_missing_persons: bool,
    import_id: uuid.UUID,
    timestamp: datetime,
) -> tuple[int, list[tuple[StagedDevice, PushTokenImportFailure]]]:
    """Sends one batch, and sends again the devices ingestion did not store, so a short outage loses nothing."""
    pending = batch
    imported = 0
    failed: list[tuple[StagedDevice, PushTokenImportFailure]] = []
    for attempt in range(NOT_STORED_ATTEMPTS):
        if attempt:
            time.sleep(NOT_STORED_RETRY_SECONDS * attempt)
        result = import_push_tokens(
            integration,
            [{"distinct_id": device["distinct_id"], "device_token": device["device_token"]} for device in pending],
            api_token,
            create_missing_persons=create_missing_persons,
            import_id=import_id,
            timestamp=timestamp,
        )
        imported += result.imported
        retry: list[StagedDevice] = []
        for failure in result.failed:
            device = pending[failure.index]
            if failure.reason == PushTokenImportFailureReason.NOT_STORED and attempt + 1 < NOT_STORED_ATTEMPTS:
                retry.append(device)
            else:
                failed.append((device, failure))
        if not retry:
            break
        pending = retry
    return imported, failed


def fail_push_token_import(
    team_id: int, import_id: uuid.UUID, error: str, *, unless_updated_since: datetime | None = None
) -> bool:
    """Returns False when the import was not running, or made progress after `unless_updated_since`."""
    running = PushTokenImport.objects.for_team(team_id).filter(id=import_id, status=PushTokenImportStatus.RUNNING)
    if unless_updated_since is not None:
        running = running.filter(updated_at=unless_updated_since)
    updated = running.update(
        status=PushTokenImportStatus.FAILED, error=error, finished_at=timezone.now(), updated_at=timezone.now()
    )
    job = PushTokenImport.objects.for_team(team_id).filter(id=import_id).first()
    if job is not None:
        _discard_devices_of_stopped(job)
        if updated:
            _report_finished(job)
    return bool(updated)


def check_stalled_push_token_import(team_id: int, import_id: uuid.UUID) -> bool:
    """Resumes an import that stopped making progress, then fails it. Returns True while it still runs."""
    job = PushTokenImport.objects.for_team(team_id).filter(id=import_id).first()
    if job is None or job.finished_at is not None:
        return False
    if timezone.now() - job.updated_at < STALLED_AFTER:
        return True
    if job.status == PushTokenImportStatus.CANCELLED:
        _end_stopped(job)
        return False
    logger.warning("push_token_import_stalled", team_id=team_id, import_id=str(import_id))
    if job.resumed_times < MAX_RESUMES:
        # Progress is saved after each batch and a batch sent again keeps its event IDs, so resuming is safe.
        resumed = (
            PushTokenImport.objects.for_team(team_id)
            .filter(id=import_id, status=PushTokenImportStatus.RUNNING, updated_at=job.updated_at)
            .update(resumed_times=job.resumed_times + 1, updated_at=timezone.now())
        )
        if resumed:
            # The task module imports this one, so a module-level import would be circular.
            from products.workflows.backend.tasks.push_token_import import run_push_token_import  # noqa: PLC0415

            run_push_token_import.delay(team_id=team_id, import_id=str(import_id))
        return True
    failed = fail_push_token_import(
        team_id,
        import_id,
        f"The import stopped after {job.processed_devices:,} of {job.total_devices:,} devices. "
        "Upload the file again to import the rest. Devices already imported are not stored twice.",
        unless_updated_since=job.updated_at,
    )
    return not failed


def expire_unknown_person_devices(team_id: int, import_id: uuid.UUID) -> bool:
    """Deletes the devices an import kept. Returns True when the import still runs, so the check comes back later."""
    job = PushTokenImport.objects.for_team(team_id).filter(id=import_id).exclude(storage_key="").first()
    if job is None:
        return False
    if job.status == PushTokenImportStatus.RUNNING:
        return True
    _release_devices(team_id, import_id, job.storage_key)
    return False


def _create_import(
    *,
    team: Team,
    user: User | None,
    integration_id: int,
    devices: list[StagedDevice],
    create_missing_persons: bool,
    rejected: list[PushTokenImportRowFailure],
    rejected_lines: int,
    duplicate_lines: int,
) -> PushTokenImportRecord:
    # The task module imports this one, so a module-level import would be circular.
    from products.workflows.backend.tasks.push_token_import import (  # noqa: PLC0415
        check_push_token_import_stalled,
        expire_push_token_import_devices,
        run_push_token_import,
    )

    import_id = uuid.uuid4()
    storage_key = f"{_STORAGE_FOLDER}/team-{team.id}/{import_id}.json"
    object_storage.write(storage_key, _encrypt_devices(devices))
    try:
        with transaction.atomic():
            job = PushTokenImport.objects.for_team(team.id).create(
                id=import_id,
                team_id=team.id,
                integration_id=integration_id,
                create_missing_persons=create_missing_persons,
                total_devices=len(devices),
                failed_devices=rejected_lines,
                duplicate_lines=duplicate_lines,
                failures=[_failure_json(failure) for failure in rejected[:MAX_STORED_FAILURES]],
                storage_key=storage_key,
                created_by=user,
            )
    except IntegrityError:
        _delete_object(storage_key)
        raise PushTokenImportInvalid(
            "An import into this channel is already running. Wait for it to finish, or stop it, and try again."
        )
    except Exception:
        # No import row exists yet, so nothing else would ever delete the stored devices.
        _delete_object(storage_key)
        raise
    try:
        run_push_token_import.delay(team_id=team.id, import_id=str(job.id))
        check_push_token_import_stalled.apply_async(
            kwargs={"team_id": team.id, "import_id": str(job.id)}, countdown=int(STALL_CHECK_EVERY.total_seconds())
        )
        # Scheduled with the import, so devices kept for unknown people can't outlive it if a later step fails.
        expire_push_token_import_devices.apply_async(
            kwargs={"team_id": team.id, "import_id": str(job.id)},
            countdown=int((UNKNOWN_PERSON_DEVICES_KEPT_FOR + EXPIRY_MARGIN).total_seconds()),
        )
    except Exception:
        fail_push_token_import(team.id, job.id, "The import couldn't start. Try again.")
        raise
    return _record(job)


def _finish(job: PushTokenImport) -> None:
    keep_unknown = bool(job.unknown_person_lines) and not job.create_missing_persons
    storage_key = job.storage_key
    finished = (
        PushTokenImport.objects.for_team(job.team_id)
        .filter(id=job.id, status=PushTokenImportStatus.RUNNING)
        .update(
            status=PushTokenImportStatus.COMPLETED,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
    )
    if not finished:
        return
    job.refresh_from_db()
    if not keep_unknown:
        _release_devices(job.team_id, job.id, storage_key)
    _report_finished(job)


def _end_stopped(job: PushTokenImport) -> None:
    """Marks a stopped import as ended once no batch of it is being sent any more."""
    if job.status == PushTokenImportStatus.CANCELLED and job.finished_at is None:
        if (
            PushTokenImport.objects.for_team(job.team_id)
            .filter(id=job.id, finished_at__isnull=True)
            .update(finished_at=timezone.now(), updated_at=timezone.now())
        ):
            job.refresh_from_db()
            _report_finished(job)
    _discard_devices_of_stopped(job)


def _discard_devices_of_stopped(job: PushTokenImport) -> None:
    if job.status == PushTokenImportStatus.RUNNING or not job.storage_key or _can_import_unknown_persons(job):
        return
    _release_devices(job.team_id, job.id, job.storage_key)


def _report_finished(job: PushTokenImport) -> None:
    user = User.objects.filter(id=job.created_by_id).only("distinct_id").first() if job.created_by_id else None
    if user is None:
        return
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(user.distinct_id),
                event="workflows push token import finished",
                properties={
                    "status": job.status,
                    "devices": job.total_devices,
                    "imported": job.imported_devices,
                    "failed": job.failed_devices,
                    "unknown_persons": len(job.unknown_person_lines),
                    "create_missing_persons": job.create_missing_persons,
                },
            )
    except Exception:
        logger.exception("push_token_import_report_failed", import_id=str(job.id))


def _push_channel(team_id: int, integration_id: int) -> IntegrationRecord:
    try:
        integration = IntegrationManager.kinds(*_PUSH_KINDS).get(team_id, integration_id)
    except IntegrationNotFound:
        raise PushTokenImportInvalid("This push channel no longer exists.")
    if not push_channel_app_id(integration):
        raise PushTokenImportInvalid("This push channel has no app set up, so devices can't be imported into it.")
    return integration


def _get(team_id: int, import_id: uuid.UUID) -> PushTokenImport:
    job = PushTokenImport.objects.for_team(team_id).filter(id=import_id).first()
    if job is None:
        raise PushTokenImportNotFound(str(import_id))
    return job


def _can_import_unknown_persons(job: PushTokenImport) -> bool:
    return (
        job.status == PushTokenImportStatus.COMPLETED
        and not job.create_missing_persons
        and bool(job.unknown_person_lines)
        and bool(job.storage_key)
    )


def _read_devices(storage_key: str) -> list[StagedDevice]:
    content = object_storage.read_bytes(storage_key, missing_ok=True) if storage_key else None
    return json.loads(zlib.decompress(_DeviceCipher().f.decrypt(content))) if content else []


def _encrypt_devices(devices: list[StagedDevice]) -> bytes:
    # Compressing first keeps the copies the cipher makes of a full-size file small.
    return _DeviceCipher().f.encrypt(zlib.compress(json.dumps(devices, separators=(",", ":")).encode(), 1))


def _release_devices(team_id: int, import_id: uuid.UUID, storage_key: str) -> None:
    """Deletes the stored devices, and forgets the key only once they are gone, so a failed delete is tried again."""
    if not _delete_object(storage_key):
        # The task module imports this one, so a module-level import would be circular.
        from products.workflows.backend.tasks.push_token_import import expire_push_token_import_devices  # noqa: PLC0415

        expire_push_token_import_devices.apply_async(
            kwargs={"team_id": team_id, "import_id": str(import_id)}, countdown=int(DELETE_RETRY_AFTER.total_seconds())
        )
        return
    PushTokenImport.objects.for_team(team_id).filter(id=import_id, storage_key=storage_key).update(
        storage_key="", updated_at=timezone.now()
    )


def _delete_object(storage_key: str) -> bool:
    try:
        object_storage.delete(storage_key)
    except Exception:
        logger.exception("push_token_import_cleanup_failed", storage_key=storage_key)
        return False
    return True


def _cell(cells: list[str], column: int) -> str:
    return cells[column].strip() if column < len(cells) else ""


def _row_problem(distinct_id: str, device_token: str) -> str | None:
    if "\x00" in distinct_id or "\x00" in device_token:
        return "The line has a NUL character in it"
    if not distinct_id:
        return "No distinct ID"
    if not device_token:
        return "No device token"
    if len(distinct_id.encode()) > MAX_DISTINCT_ID_BYTES:
        return f"Distinct ID is longer than {MAX_DISTINCT_ID_BYTES} bytes"
    if len(device_token) > MAX_DEVICE_TOKEN_LENGTH:
        return f"Device token is longer than {MAX_DEVICE_TOKEN_LENGTH} characters"
    return None


def _failure_json(failure: PushTokenImportRowFailure) -> dict[str, str | int]:
    return {
        "line": failure.line,
        "distinct_id": failure.distinct_id,
        "device_token_suffix": failure.device_token_suffix,
        "reason": str(failure.reason),
        "detail": failure.detail,
    }


def _record(job: PushTokenImport) -> PushTokenImportRecord:
    return PushTokenImportRecord(
        id=job.id,
        integration_id=job.integration_id,
        status=PushTokenImportStatus(job.status),
        create_missing_persons=job.create_missing_persons,
        total_devices=job.total_devices,
        processed_devices=job.processed_devices,
        imported_devices=job.imported_devices,
        failed_devices=job.failed_devices,
        unknown_person_devices=len(job.unknown_person_lines),
        duplicate_lines=job.duplicate_lines,
        failures=tuple(
            PushTokenImportRowFailure(
                line=int(failure["line"]),
                distinct_id=str(failure["distinct_id"]),
                device_token_suffix=str(failure["device_token_suffix"]),
                reason=PushTokenImportRowFailureReason(failure["reason"]),
                detail=str(failure["detail"]),
            )
            for failure in sorted(job.failures, key=lambda failure: int(failure["line"]))
        ),
        can_import_unknown_persons=_can_import_unknown_persons(job),
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )
