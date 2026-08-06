from __future__ import annotations

import os
from uuid import UUID

import structlog

from posthog.storage import object_storage

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import TaskArtifact, TaskArtifactVersion, TaskRun

logger = structlog.get_logger(__name__)

EDITABLE_ARTIFACT_MAX_BYTES = 500_000
TEXT_APPLICATION_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/sql",
        "application/toml",
        "application/xml",
        "application/x-yaml",
        "application/yaml",
    }
)
TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".conf",
        ".cpp",
        ".css",
        ".csv",
        ".go",
        ".h",
        ".htm",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".log",
        ".markdown",
        ".md",
        ".mdx",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsv",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def is_editable_text_artifact(entry: dict) -> bool:
    size = entry.get("size")
    if not isinstance(size, int) or size > EDITABLE_ARTIFACT_MAX_BYTES:
        return False
    content_type = str(entry.get("content_type") or "").split(";", 1)[0].strip().lower()
    extension = os.path.splitext(str(entry.get("name") or ""))[1].lower()
    return content_type.startswith("text/") or content_type in TEXT_APPLICATION_TYPES or extension in TEXT_EXTENSIONS


def manifest_entry_for_version(version: TaskArtifactVersion) -> dict | None:
    for entry in version.task_run.artifacts or []:
        if isinstance(entry, dict) and str(entry.get("id") or "") == version.run_artifact_id:
            return entry
    return None


def current_stored_version(artifact: TaskArtifact) -> TaskArtifactVersion | None:
    return (
        TaskArtifactVersion.objects.for_team(artifact.team_id)
        .filter(artifact_id=artifact.id, version=artifact.current_version)
        .select_related("task_run", "created_by")
        .first()
    )


def register_uploaded_artifact_version(
    *,
    run: TaskRun,
    entry: dict,
    logical_artifact_id: UUID | None,
    expected_current_version_id: UUID | None,
    request_id: UUID | None,
    created_by_id: int | None,
) -> TaskArtifactVersion | None:
    if entry.get("type") != "output" or entry.get("source") != "agent_output":
        if logical_artifact_id is not None:
            raise ValueError("Only agent output artifacts can create artifact versions")
        return None

    run_artifact_id = str(entry.get("id") or "")
    if not run_artifact_id:
        raise ValueError("Uploaded artifact is missing its id")

    existing_source = (
        TaskArtifactVersion.objects.for_team(run.team_id)
        .filter(task_run_id=run.id, run_artifact_id=run_artifact_id)
        .first()
    )
    if existing_source is not None:
        if logical_artifact_id is not None and existing_source.artifact_id != logical_artifact_id:
            raise ValueError("Uploaded artifact is already assigned to another artifact")
        return existing_source

    if logical_artifact_id is None:
        try:
            artifact_id = UUID(run_artifact_id)
        except ValueError:
            return None
        artifact = TaskArtifact.objects.for_team(run.team_id).select_for_update().filter(id=artifact_id).first()
        if artifact is None:
            artifact = TaskArtifact.objects.for_team(run.team_id).create(
                id=artifact_id,
                team_id=run.team_id,
                task_id=run.task_id,
                task_run_id=run.id,
                created_by_id=created_by_id,
                name=str(entry.get("name") or "artifact"),
                artifact_type=TaskArtifact.ArtifactType.FILE,
                adapter=TaskArtifact.Adapter.OBJECT_STORAGE,
                status=TaskArtifact.Status.ACTIVE,
                location=_artifact_location(run, entry),
                metadata=_artifact_metadata(entry),
                versions=[],
                current_version=1,
            )
        elif artifact.adapter != TaskArtifact.Adapter.OBJECT_STORAGE or artifact.task_id != run.task_id:
            raise ValueError("Artifact id is already in use")
        existing_version = current_stored_version(artifact)
        if existing_version is not None:
            return existing_version
        version_number = 1
    else:
        artifact = (
            TaskArtifact.objects.for_team(run.team_id)
            .select_for_update()
            .filter(id=logical_artifact_id, task_id=run.task_id, adapter=TaskArtifact.Adapter.OBJECT_STORAGE)
            .first()
        )
        if artifact is None:
            raise ValueError("Artifact not found")
        if request_id is not None:
            repeated = (
                TaskArtifactVersion.objects.for_team(run.team_id)
                .filter(artifact_id=artifact.id, request_id=request_id)
                .first()
            )
            if repeated is not None:
                if repeated.task_run_id == run.id and repeated.run_artifact_id == run_artifact_id:
                    return repeated
                raise ValueError("Artifact version request id was already used for another upload")
        current = current_stored_version(artifact)
        current_id = current.id if current is not None else None
        if current_id != expected_current_version_id:
            raise contracts.TaskArtifactVersionConflict(current_id)
        if str(entry.get("name") or "") != artifact.name:
            raise ValueError("Artifact versions must keep the original file name")
        prior_metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
        if is_editable_text_artifact(
            {
                "name": artifact.name,
                "content_type": prior_metadata.get("content_type"),
                "size": prior_metadata.get("size"),
            }
        ) and not is_editable_text_artifact(entry):
            raise ValueError("Editable text artifact versions cannot exceed 500 KB or change to a binary type")
        version_number = artifact.current_version + 1

    version = TaskArtifactVersion.objects.for_team(run.team_id).create(
        team_id=run.team_id,
        artifact_id=artifact.id,
        task_run_id=run.id,
        run_artifact_id=run_artifact_id,
        version=version_number,
        request_id=request_id,
        created_by_id=created_by_id,
    )
    artifact.current_version = version_number
    artifact.location = _artifact_location(run, entry)
    artifact.metadata = _artifact_metadata(entry)
    artifact.status = TaskArtifact.Status.ACTIVE
    artifact.save(update_fields=["current_version", "location", "metadata", "status", "updated_at"])
    return version


def preserve_version_object(*, team_id: int, storage_path: str) -> None:
    try:
        object_storage.tag(storage_path, {"team_id": str(team_id)})
    except Exception:
        logger.warning("task_artifact.version_preserve_tag_failed", storage_path=storage_path, exc_info=True)


def expire_uncommitted_object(*, team_id: int, storage_path: str) -> None:
    try:
        object_storage.tag(storage_path, {"ttl_days": "1", "team_id": str(team_id)})
    except Exception:
        logger.warning("task_artifact.version_cleanup_tag_failed", storage_path=storage_path, exc_info=True)


def get_artifact(*, team_id: int, task_id: UUID, artifact_id: UUID) -> TaskArtifact | None:
    return (
        TaskArtifact.objects.for_team(team_id)
        .filter(id=artifact_id, task_id=task_id, adapter=TaskArtifact.Adapter.OBJECT_STORAGE)
        .first()
    )


def list_versions(
    *, artifact: TaskArtifact, limit: int, before_version: int | None
) -> tuple[list[TaskArtifactVersion], int | None]:
    queryset = TaskArtifactVersion.objects.for_team(artifact.team_id).filter(artifact_id=artifact.id)
    if before_version is not None:
        queryset = queryset.filter(version__lt=before_version)
    versions = list(queryset.select_related("artifact", "task_run", "created_by").order_by("-version")[: limit + 1])
    has_more = len(versions) > limit
    versions = versions[:limit]
    next_before_version = versions[-1].version if has_more and versions else None
    return versions, next_before_version


def get_version(*, artifact: TaskArtifact, version_id: UUID | None) -> TaskArtifactVersion | None:
    queryset = TaskArtifactVersion.objects.for_team(artifact.team_id).filter(artifact_id=artifact.id)
    if version_id is None:
        queryset = queryset.filter(version=artifact.current_version)
    else:
        queryset = queryset.filter(id=version_id)
    return queryset.select_related("artifact", "task_run", "created_by").first()


def read_version_content(
    *, version: TaskArtifactVersion, content_offset: int, content_limit: int
) -> tuple[str, bool, int | None]:
    entry = manifest_entry_for_version(version)
    if entry is None or not is_editable_text_artifact(entry):
        raise ValueError("Artifact version is not editable text")
    storage_path = str(entry.get("storage_path") or "")
    if not storage_path:
        raise ValueError("Artifact version content is unavailable")
    raw = object_storage.read_bytes(storage_path, missing_ok=True)
    if raw is None:
        raise ValueError("Artifact version content is unavailable")
    if len(raw) > EDITABLE_ARTIFACT_MAX_BYTES or b"\x00" in raw:
        raise ValueError("Artifact version is not editable text")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Artifact version is not editable text") from error
    if content_offset > len(raw):
        raise ValueError("Content offset is past the end of the artifact")
    end = min(len(raw), content_offset + content_limit)
    while True:
        try:
            chunk = raw[content_offset:end].decode("utf-8")
            break
        except UnicodeDecodeError as error:
            if error.reason != "unexpected end of data" or end >= len(raw):
                raise ValueError("Content offset must start at a UTF-8 character boundary") from error
            end += 1
    next_offset = end if end < len(raw) else None
    return chunk, next_offset is not None, next_offset


def attach_version_metadata(entry: dict, version: TaskArtifactVersion | None) -> dict:
    if version is None:
        return dict(entry)
    return {
        **entry,
        "logical_artifact_id": str(version.artifact_id),
        "artifact_version_id": str(version.id),
        "artifact_version": version.version,
    }


def _artifact_location(run: TaskRun, entry: dict) -> dict:
    return {
        "kind": TaskArtifact.Adapter.OBJECT_STORAGE,
        "run_id": str(run.id),
        "run_artifact_id": str(entry.get("id") or ""),
        "storage_path": str(entry.get("storage_path") or ""),
    }


def _artifact_metadata(entry: dict) -> dict:
    return {
        "content_type": str(entry.get("content_type") or ""),
        "size": entry.get("size"),
    }
