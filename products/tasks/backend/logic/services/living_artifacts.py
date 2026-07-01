from __future__ import annotations

import io
import os
import json
import uuid
import zipfile
import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import requests
import structlog
from slack_sdk.errors import SlackApiError

from posthog.storage import object_storage

from products.tasks.backend.models import TaskArtifact, TaskRun

logger = structlog.get_logger(__name__)

SLACK_CANVAS_SCOPE = "canvases:write"
SLACK_FILE_SCOPE = "files:write"
LIVING_ARTIFACT_TTL_DAYS = "30"
DEFAULT_DOCUMENT_CONTENT_TYPE = "text/markdown; charset=utf-8"
DEFAULT_BINARY_CONTENT_TYPE = "application/octet-stream"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_EXTENSION = ".xlsx"


@dataclass(frozen=True)
class ArtifactContent:
    title: str
    body: str
    content_type: str
    content_bytes: bytes | None = None
    source_artifact: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactCommit:
    adapter: str
    location: dict[str, Any]
    metadata: dict[str, Any]
    version: dict[str, Any]


class DocumentConnectorUnavailable(Exception):
    """Raised when a configured document connector cannot write this artifact."""

    pass


def build_living_artifact_storage_path(run: TaskRun, artifact_id: str, version: int, name: str) -> str:
    safe_name = os.path.basename(name).strip() or "artifact.md"
    base, ext = os.path.splitext(safe_name)
    if not ext:
        ext = ".md"
    versioned_name = f"{base}.v{version}{ext}"
    return f"{run.get_artifact_s3_prefix()}/living/{artifact_id}/{versioned_name}"


def serialize_task_artifact(artifact: TaskArtifact) -> dict[str, Any]:
    return {
        "id": str(artifact.id),
        "task_id": str(artifact.task_id),
        "run_id": str(artifact.task_run_id),
        "team_id": artifact.team_id,
        "name": artifact.name,
        "artifact_type": artifact.artifact_type,
        "adapter": artifact.adapter,
        "status": artifact.status,
        "location": artifact.location or {},
        "metadata": artifact.metadata or {},
        "current_version": artifact.current_version,
        "versions": artifact.versions or [],
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def create_living_artifact(
    *,
    run: TaskRun,
    name: str,
    artifact_type: str,
    adapter: str | None = None,
    content: str | None = None,
    content_bytes: bytes | None = None,
    content_type: str | None = None,
    source_artifact_id: str | None = None,
    source_storage_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskArtifact:
    content_payload = resolve_artifact_content(
        run=run,
        name=name,
        content=content,
        content_bytes=content_bytes,
        content_type=content_type,
        source_artifact_id=source_artifact_id,
        source_storage_path=source_storage_path,
    )
    name, content_payload = _normalize_spreadsheet_artifact_name_and_type(
        name=name,
        artifact_type=artifact_type,
        content=content_payload,
    )
    selected_adapter = _resolve_adapter(run, adapter, artifact_type)
    artifact_id = uuid.uuid4()
    commit = selected_adapter.create(
        run=run, name=name, artifact_type=artifact_type, content=content_payload, artifact_id=str(artifact_id)
    )

    with transaction.atomic():
        artifact = TaskArtifact.objects.for_team(run.team_id).create(
            id=artifact_id,
            team=run.team,
            task=run.task,
            task_run=run,
            created_by=run.task.created_by,
            name=name,
            artifact_type=artifact_type,
            adapter=commit.adapter,
            status=TaskArtifact.Status.ACTIVE,
            location=commit.location,
            metadata={
                **(metadata or {}),
                **commit.metadata,
                "requested_adapter": adapter,
                "source_artifact_id": source_artifact_id,
                "source_storage_path": source_storage_path,
            },
            versions=[commit.version],
            current_version=1,
        )
    return artifact


def edit_living_artifact(
    *,
    artifact: TaskArtifact,
    content: str | None = None,
    content_bytes: bytes | None = None,
    content_type: str | None = None,
    source_artifact_id: str | None = None,
    source_storage_path: str | None = None,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskArtifact:
    run = artifact.task_run
    selected_adapter = _adapter_for_existing_artifact(artifact)
    next_version = int(artifact.current_version or 0) + 1
    next_name = name or artifact.name
    content_payload = resolve_artifact_content(
        run=run,
        name=next_name,
        content=content,
        content_bytes=content_bytes,
        content_type=content_type,
        source_artifact_id=source_artifact_id,
        source_storage_path=source_storage_path,
    )
    next_name, content_payload = _normalize_spreadsheet_artifact_name_and_type(
        name=next_name,
        artifact_type=artifact.artifact_type,
        content=content_payload,
    )
    existing_content = selected_adapter.open(artifact)
    next_content = selected_adapter.apply_edit(existing_content, content_payload.body)
    commit = selected_adapter.commit(
        artifact=artifact,
        run=run,
        name=next_name,
        content=next_content,
        content_bytes=content_payload.content_bytes,
        version=next_version,
        content_type=content_payload.content_type,
        source_artifact=content_payload.source_artifact,
    )

    with transaction.atomic():
        locked = TaskArtifact.objects.for_team(artifact.team_id).select_for_update().get(pk=artifact.pk)
        versions = list(locked.versions or [])
        versions.append(commit.version)
        locked.name = next_name
        locked.adapter = commit.adapter
        locked.location = commit.location
        locked.metadata = {**(locked.metadata or {}), **(metadata or {}), **commit.metadata}
        locked.versions = versions
        locked.current_version = next_version
        locked.status = TaskArtifact.Status.ACTIVE
        locked.save(
            update_fields=[
                "name",
                "adapter",
                "location",
                "metadata",
                "versions",
                "current_version",
                "status",
                "updated_at",
            ]
        )
        return locked


def resolve_artifact_content(
    *,
    run: TaskRun,
    name: str,
    content: str | None,
    content_bytes: bytes | None = None,
    content_type: str | None = None,
    source_artifact_id: str | None = None,
    source_storage_path: str | None = None,
) -> ArtifactContent:
    if content_bytes is not None:
        resolved_content_type = content_type or _guess_content_type(name)
        body = (
            content_bytes.decode("utf-8", errors="replace")
            if _is_textual_name_and_type(name, resolved_content_type)
            else name
        )
        return ArtifactContent(
            title=name,
            body=body,
            content_type=resolved_content_type,
            content_bytes=content_bytes,
        )

    if content is not None:
        resolved_content_type = content_type or DEFAULT_DOCUMENT_CONTENT_TYPE
        return ArtifactContent(
            title=name,
            body=content,
            content_type=resolved_content_type,
            content_bytes=content.encode("utf-8"),
        )

    source_artifact = _find_source_artifact(
        run, source_artifact_id=source_artifact_id, source_storage_path=source_storage_path
    )
    if source_artifact is None:
        raise ValueError("A content value or valid source artifact is required")

    storage_path = str(source_artifact.get("storage_path") or "")
    source_content_type = str(source_artifact.get("content_type") or "")
    resolved_content_type = (
        content_type or source_content_type or _guess_content_type(str(source_artifact.get("name") or name))
    )
    raw = object_storage.read_bytes(storage_path, missing_ok=True)
    if raw is None:
        raise ValueError("Source artifact content not found")

    if _is_textual_content(source_artifact):
        return ArtifactContent(
            title=str(source_artifact.get("name") or name),
            body=raw.decode("utf-8", errors="replace"),
            content_type=resolved_content_type,
            content_bytes=raw,
            source_artifact=source_artifact,
        )

    url = object_storage.get_presigned_url(storage_path)
    body = f"[{source_artifact.get('name') or name}]({url})" if url else str(source_artifact.get("name") or name)
    return ArtifactContent(
        title=str(source_artifact.get("name") or name),
        body=body,
        content_type=resolved_content_type,
        content_bytes=raw,
        source_artifact=source_artifact,
    )


def _normalize_spreadsheet_artifact_name_and_type(
    *,
    name: str,
    artifact_type: str,
    content: ArtifactContent,
) -> tuple[str, ArtifactContent]:
    if artifact_type != TaskArtifact.ArtifactType.SPREADSHEET:
        return name, content
    if not _is_xlsx_artifact(name, content.content_type, content.content_bytes):
        return name, content

    normalized_name = _with_xlsx_extension(name)
    normalized_body = normalized_name if content.body == name else content.body
    return normalized_name, replace(
        content,
        title=normalized_name,
        body=normalized_body,
        content_type=XLSX_CONTENT_TYPE,
    )


def _is_xlsx_artifact(name: str, content_type: str, content_bytes: bytes | None) -> bool:
    normalized_content_type = str(content_type or "").split(";")[0].strip().lower()
    if normalized_content_type == XLSX_CONTENT_TYPE:
        return True
    if name.lower().endswith(XLSX_EXTENSION):
        return True
    return _is_xlsx_payload(content_bytes)


def _is_xlsx_payload(content_bytes: bytes | None) -> bool:
    if not content_bytes or not content_bytes.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names


def _with_xlsx_extension(name: str) -> str:
    safe_name = os.path.basename(name).strip() or "artifact"
    if safe_name.lower().endswith(XLSX_EXTENSION):
        return safe_name
    base, ext = os.path.splitext(safe_name)
    if not base:
        base = safe_name.removesuffix(ext) or "artifact"
    return f"{base}{XLSX_EXTENSION}"


def get_task_artifacts_for_run(run: TaskRun) -> list[TaskArtifact]:
    return list(TaskArtifact.objects.for_team(run.team_id).filter(task_run=run).order_by("-updated_at"))


def get_task_artifact_for_run(run: TaskRun, artifact_id: str | UUID) -> TaskArtifact | None:
    return TaskArtifact.objects.for_team(run.team_id).filter(task_run=run, id=artifact_id).first()


def open_task_artifact(artifact: TaskArtifact) -> str | None:
    return _adapter_for_existing_artifact(artifact).open(artifact)


def _artifact_type_from_manifest(manifest_entry: dict[str, Any]) -> str:
    raw_type = str(manifest_entry.get("type") or "")
    content_type = str(manifest_entry.get("content_type") or "").lower()
    name = str(manifest_entry.get("name") or "").lower()
    if raw_type in {choice for choice, _label in TaskArtifact.ArtifactType.choices}:
        return raw_type
    if _is_spreadsheet_name_or_type(name, content_type):
        return TaskArtifact.ArtifactType.SPREADSHEET
    if content_type.startswith("text/") or name.endswith((".md", ".txt", ".html")):
        return TaskArtifact.ArtifactType.DOCUMENT
    return TaskArtifact.ArtifactType.FILE


def _find_source_artifact(
    run: TaskRun,
    *,
    source_artifact_id: str | None,
    source_storage_path: str | None,
) -> dict[str, Any] | None:
    for candidate_run in reversed(run.get_resume_chain()):
        for artifact in candidate_run.artifacts or []:
            if source_artifact_id and str(artifact.get("id")) == str(source_artifact_id):
                return artifact
            if source_storage_path and artifact.get("storage_path") == source_storage_path:
                return artifact
    return None


def _is_textual_content(source_artifact: dict[str, Any]) -> bool:
    content_type = str(source_artifact.get("content_type") or "").split(";")[0].strip().lower()
    name = str(source_artifact.get("name") or "").lower()
    return _is_textual_name_and_type(name, content_type)


def _is_textual_name_and_type(name: str, content_type: str) -> bool:
    normalized_content_type = str(content_type or "").split(";")[0].strip().lower()
    normalized_name = name.lower()
    return (
        normalized_content_type.startswith("text/")
        or normalized_content_type in {"application/json", "application/xml", "application/xhtml+xml"}
        or normalized_name.endswith((".md", ".txt", ".csv", ".json", ".html", ".xml"))
    )


def _is_spreadsheet_name_or_type(name: str, content_type: str) -> bool:
    normalized_content_type = str(content_type or "").split(";")[0].strip().lower()
    normalized_name = name.lower()
    return normalized_content_type in {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
    } or normalized_name.endswith((".csv", ".xls", ".xlsx"))


def _guess_content_type(name: str) -> str:
    guessed, _encoding = mimetypes.guess_type(name)
    return guessed or DEFAULT_BINARY_CONTENT_TYPE


def _resolve_adapter(run: TaskRun, adapter: str | None, artifact_type: str) -> LivingArtifactAdapter:
    if adapter == TaskArtifact.Adapter.SLACK_MESSAGE or artifact_type == TaskArtifact.ArtifactType.SLACK_MESSAGE:
        return SlackMessageArtifactAdapter()
    if adapter == TaskArtifact.Adapter.SLACK_CANVAS or artifact_type == TaskArtifact.ArtifactType.SLACK_CANVAS:
        return SlackCanvasArtifactAdapter()
    if adapter == TaskArtifact.Adapter.SLACK_FILE:
        return SlackFileArtifactAdapter()
    if adapter == TaskArtifact.Adapter.DOCUMENT_CONNECTOR:
        return DocumentConnectorArtifactAdapter()
    if _get_slack_mapping(run, raise_if_missing=False) is not None:
        if artifact_type in {TaskArtifact.ArtifactType.SPREADSHEET, TaskArtifact.ArtifactType.FILE}:
            return SlackFileArtifactAdapter()
        if artifact_type in {TaskArtifact.ArtifactType.DOCUMENT, TaskArtifact.ArtifactType.DASHBOARD}:
            return SlackCanvasArtifactAdapter()
    if artifact_type in {TaskArtifact.ArtifactType.DOCUMENT, TaskArtifact.ArtifactType.SPREADSHEET}:
        return DocumentConnectorArtifactAdapter()
    raise ValueError("No external artifact adapter is available for this task run")


def _adapter_for_existing_artifact(artifact: TaskArtifact) -> LivingArtifactAdapter:
    if artifact.adapter == TaskArtifact.Adapter.SLACK_MESSAGE:
        return SlackMessageArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.SLACK_CANVAS:
        return SlackCanvasArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.SLACK_FILE:
        return SlackFileArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.DOCUMENT_CONNECTOR:
        return DocumentConnectorArtifactAdapter()
    raise ValueError(f"Unsupported living artifact adapter: {artifact.adapter}")


class LivingArtifactAdapter(ABC):
    adapter: str

    def create(
        self,
        *,
        run: TaskRun,
        name: str,
        artifact_type: str,
        content: ArtifactContent,
        artifact_id: str | None = None,
    ) -> ArtifactCommit:
        return self.commit(
            artifact=None,
            run=run,
            name=name,
            content=content.body,
            version=1,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content_type=content.content_type,
            content_bytes=content.content_bytes,
            source_artifact=content.source_artifact,
        )

    @abstractmethod
    def open(self, artifact: TaskArtifact) -> str | None:
        raise NotImplementedError

    def apply_edit(self, existing_content: str | None, replacement_content: str) -> str:
        return replacement_content

    @abstractmethod
    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        raise NotImplementedError


def _document_connector_adapter_for_run(run: TaskRun) -> LivingArtifactAdapter | None:
    """Return a writable actor-token document adapter for this run, when connected."""

    return None


class DocumentConnectorArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.DOCUMENT_CONNECTOR

    def open(self, artifact: TaskArtifact) -> str | None:
        connector = _document_connector_adapter_for_run(artifact.task_run)
        if connector is None:
            return None
        return connector.open(artifact)

    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        connector = _document_connector_adapter_for_run(run)
        if connector is not None:
            try:
                commit = connector.commit(
                    artifact=artifact,
                    run=run,
                    name=name,
                    content=content,
                    version=version,
                    artifact_id=artifact_id,
                    artifact_type=artifact_type,
                    content_type=content_type,
                    content_bytes=content_bytes,
                    source_artifact=source_artifact,
                )
            except DocumentConnectorUnavailable as exc:
                logger.info("task_run.document_connector_unavailable", run_id=str(run.id))
                raise DocumentConnectorUnavailable(str(exc) or "External document connector is unavailable") from exc
            else:
                return ArtifactCommit(
                    adapter=self.adapter,
                    location=commit.location,
                    metadata={**commit.metadata, "document_connector_status": "connected"},
                    version={**commit.version, "adapter": self.adapter, "document_connector_status": "connected"},
                )

        raise DocumentConnectorUnavailable("No external document connector is available for this task run")


class SlackMessageArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.SLACK_MESSAGE

    def open(self, artifact: TaskArtifact) -> str | None:
        return (artifact.versions or [])[-1].get("content") if artifact.versions else None

    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        text = content.strip() or name
        if artifact is None:
            response = _slack_client_for_mapping(mapping).chat_postMessage(
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            message_ts = response.get("ts")
            if not message_ts:
                raise ValueError("Slack message delivery did not return a message timestamp")
        else:
            message_ts = (artifact.location or {}).get("message_ts")
            if not message_ts:
                raise ValueError("Slack message artifact is missing a message timestamp")
            _slack_client_for_mapping(mapping).chat_update(channel=mapping.channel, ts=message_ts, text=text)
        location = {
            "kind": "slack_message",
            "integration_id": mapping.integration_id,
            "channel": mapping.channel,
            "thread_ts": mapping.thread_ts,
            "message_ts": message_ts,
        }
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={"slack_workspace_id": mapping.slack_workspace_id},
            version=_version_payload(
                version=version,
                run=run,
                adapter=self.adapter,
                location=location,
                content_type=content_type or "text/plain",
                source_artifact=source_artifact,
                content=text,
            ),
        )


class SlackCanvasArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.SLACK_CANVAS

    def open(self, artifact: TaskArtifact) -> str | None:
        return (artifact.versions or [])[-1].get("content") if artifact.versions else None

    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        slack_integration = _slack_integration_for_mapping(mapping)
        missing_scopes = slack_integration.missing_scopes(frozenset({SLACK_CANVAS_SCOPE}))
        if missing_scopes:
            raise ValueError("Slack canvas delivery requires the canvases:write Slack scope")
        slack = slack_integration.client
        markdown = content.strip() or name
        if artifact is None:
            response = slack.api_call(
                "canvases.create",
                json={
                    "title": name[:255],
                    "channel_id": mapping.channel,
                    "document_content": {"type": "markdown", "markdown": markdown},
                },
            )
            canvas_id = str(response.get("canvas_id") or "")
            if not canvas_id:
                raise ValueError("Slack canvas delivery did not return a canvas id")
            canvas_url = _slack_canvas_url(response, mapping.slack_workspace_id, canvas_id)
            _post_canvas_created_message(slack, mapping, name, canvas_id, canvas_url)
        else:
            canvas_id = str((artifact.location or {}).get("canvas_id") or "")
            if not canvas_id:
                raise ValueError("Slack canvas artifact is missing a canvas id")
            canvas_url = (artifact.location or {}).get("url") or _slack_canvas_url(
                None, mapping.slack_workspace_id, canvas_id
            )
            slack.api_call(
                "canvases.edit",
                json={
                    "canvas_id": canvas_id,
                    "changes": [
                        {
                            "operation": "replace",
                            "document_content": {"type": "markdown", "markdown": markdown},
                        }
                    ],
                },
            )
        location = {
            "kind": "slack_canvas",
            "integration_id": mapping.integration_id,
            "channel": mapping.channel,
            "thread_ts": mapping.thread_ts,
            "canvas_id": canvas_id,
        }
        if canvas_url:
            location["url"] = canvas_url
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={
                "slack_workspace_id": mapping.slack_workspace_id,
                **({"slack_canvas_url": canvas_url} if canvas_url else {}),
            },
            version=_version_payload(
                version=version,
                run=run,
                adapter=self.adapter,
                location=location,
                content_type=content_type or DEFAULT_DOCUMENT_CONTENT_TYPE,
                source_artifact=source_artifact,
                content=markdown,
            ),
        )


class SlackFileArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.SLACK_FILE

    def open(self, artifact: TaskArtifact) -> str | None:
        return None

    def commit(
        self,
        *,
        artifact: TaskArtifact | None,
        run: TaskRun,
        name: str,
        content: str,
        version: int,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        content_type: str | None = None,
        content_bytes: bytes | None = None,
        source_artifact: dict[str, Any] | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        slack_integration = _slack_integration_for_mapping(mapping)
        missing_scopes = slack_integration.missing_scopes(frozenset({SLACK_FILE_SCOPE}))
        if missing_scopes:
            raise ValueError("Slack file delivery requires the files:write Slack scope")

        resolved_content_type = content_type or _guess_content_type(name)
        payload = content_bytes if content_bytes is not None else content.encode("utf-8")
        artifact_key = str(artifact.id) if artifact is not None else artifact_id or uuid.uuid4().hex
        storage_path = build_living_artifact_storage_path(run, artifact_key, version, name)
        object_storage.write(storage_path, payload, {"ContentType": resolved_content_type})
        _tag_living_artifact_object(run, storage_path)
        location = {
            "kind": "slack_file",
            "integration_id": mapping.integration_id,
            "channel": mapping.channel,
            "thread_ts": mapping.thread_ts,
            "content_type": resolved_content_type,
            "storage_path": storage_path,
            "delivery_status": "pending",
        }
        version_payload = _version_payload(
            version=version,
            run=run,
            adapter=self.adapter,
            location=location,
            content_type=resolved_content_type,
            source_artifact=source_artifact,
            size=len(payload),
        )
        version_payload["delivery_status"] = "pending"
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={
                "slack_workspace_id": mapping.slack_workspace_id,
                "delivery_status": "pending",
                "size": len(payload),
            },
            version=version_payload,
        )


def has_pending_slack_file_artifacts(run: TaskRun) -> bool:
    artifacts = TaskArtifact.objects.for_team(run.team_id).filter(
        task_run=run,
        adapter=TaskArtifact.Adapter.SLACK_FILE,
        status=TaskArtifact.Status.ACTIVE,
    )
    return any(_pending_slack_file_version(artifact) is not None for artifact in artifacts)


def deliver_pending_slack_file_artifacts(run: TaskRun, *, initial_comment: str) -> int:
    mapping = _get_slack_mapping(run, raise_if_missing=False)
    if mapping is None:
        return 0

    slack_integration = _slack_integration_for_mapping(mapping)
    missing_scopes = slack_integration.missing_scopes(frozenset({SLACK_FILE_SCOPE}))
    if missing_scopes:
        logger.warning(
            "task_artifact.slack_file_delivery_missing_scope",
            task_run_id=str(run.id),
            missing_scopes=sorted(missing_scopes),
        )
        return 0

    artifacts = list(
        TaskArtifact.objects.for_team(run.team_id)
        .filter(
            task_run=run,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            status=TaskArtifact.Status.ACTIVE,
        )
        .order_by("created_at", "id")
    )
    slack = slack_integration.client
    delivered_count = 0
    next_initial_comment = initial_comment.strip()
    for artifact in artifacts:
        pending = _pending_slack_file_version(artifact)
        if pending is None:
            continue

        _version_index, version_payload = pending
        location = version_payload.get("location") if isinstance(version_payload.get("location"), dict) else {}
        storage_path = str(location.get("storage_path") or (artifact.location or {}).get("storage_path") or "")
        if not storage_path:
            logger.warning("task_artifact.slack_file_missing_storage_path", artifact_id=str(artifact.id))
            continue

        payload = object_storage.read_bytes(storage_path, missing_ok=True)
        if payload is None:
            logger.warning(
                "task_artifact.slack_file_pending_content_missing",
                artifact_id=str(artifact.id),
                storage_path=storage_path,
            )
            continue

        content_type = str(
            version_payload.get("content_type")
            or location.get("content_type")
            or (artifact.location or {}).get("content_type")
            or _guess_content_type(artifact.name)
        )
        try:
            file_id, file_response = _upload_slack_file(
                slack,
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                name=artifact.name,
                content=payload,
                content_type=content_type,
                initial_comment=next_initial_comment,
            )
        except Exception:
            logger.warning("task_artifact.slack_file_delivery_failed", artifact_id=str(artifact.id), exc_info=True)
            continue

        next_initial_comment = ""
        if _mark_slack_file_artifact_delivered(
            artifact=artifact,
            version_number=int(version_payload.get("version") or artifact.current_version or 0),
            file_id=file_id,
            file_response=file_response,
        ):
            delivered_count += 1

    return delivered_count


def _pending_slack_file_version(artifact: TaskArtifact) -> tuple[int, dict[str, Any]] | None:
    versions = artifact.versions or []
    current_version = int(artifact.current_version or 0)
    fallback: tuple[int, dict[str, Any]] | None = None
    for index, version in enumerate(versions):
        if not isinstance(version, dict):
            continue
        fallback = (index, version)
        if int(version.get("version") or 0) == current_version:
            return _pending_version_if_undelivered(index, version)

    if fallback is None:
        return None
    return _pending_version_if_undelivered(fallback[0], fallback[1])


def _pending_version_if_undelivered(index: int, version: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    if version.get("slack_file_id") or version.get("delivery_status") == "delivered":
        return None
    location = version.get("location") if isinstance(version.get("location"), dict) else {}
    if not location.get("storage_path"):
        return None
    return index, version


def _mark_slack_file_artifact_delivered(
    *,
    artifact: TaskArtifact,
    version_number: int,
    file_id: str,
    file_response: dict[str, Any],
) -> bool:
    with transaction.atomic():
        locked = TaskArtifact.objects.for_team(artifact.team_id).select_for_update().get(pk=artifact.pk)
        pending = _pending_slack_file_version(locked)
        if pending is None:
            return False

        version_index, version_payload = pending
        if int(version_payload.get("version") or 0) != version_number:
            return False

        file_title = str(file_response.get("title") or locked.name)
        file_permalink = file_response.get("permalink")
        delivered_location = {
            **(locked.location or {}),
            "file_id": file_id,
            "delivery_status": "delivered",
        }
        delivered_version = {
            **version_payload,
            "slack_file_id": file_id,
            "slack_file_title": file_title,
            "delivery_status": "delivered",
        }
        delivered_metadata = {
            **(locked.metadata or {}),
            "slack_file_id": file_id,
            "slack_file_title": file_title,
            "delivery_status": "delivered",
        }
        if file_permalink:
            delivered_version["slack_file_permalink"] = file_permalink
            delivered_metadata["slack_file_permalink"] = file_permalink

        versions = list(locked.versions or [])
        versions[version_index] = delivered_version
        locked.location = delivered_location
        locked.metadata = delivered_metadata
        locked.versions = versions
        locked.save(update_fields=["location", "metadata", "versions", "updated_at"])
        return True


def _version_payload(
    *,
    version: int,
    run: TaskRun,
    adapter: str,
    location: dict[str, Any],
    content_type: str,
    source_artifact: dict[str, Any] | None = None,
    content: str | None = None,
    size: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": version,
        "run_id": str(run.id),
        "adapter": adapter,
        "location": location,
        "content_type": content_type,
        "created_at": timezone.now().isoformat(),
    }
    if source_artifact is not None:
        payload["source_artifact_id"] = source_artifact.get("id")
        payload["source_storage_path"] = source_artifact.get("storage_path")
    if size is not None:
        payload["size"] = size
    if content is not None:
        payload["content"] = content
    return payload


def _tag_living_artifact_object(run: TaskRun, storage_path: str) -> None:
    try:
        object_storage.tag(storage_path, {"ttl_days": LIVING_ARTIFACT_TTL_DAYS, "team_id": str(run.team_id)})
    except Exception:
        logger.warning(
            "task_artifact.s3_tag_failed",
            task_run_id=str(run.id),
            storage_path=storage_path,
            exc_info=True,
        )


def _get_slack_mapping(run: TaskRun, *, raise_if_missing: bool = True):
    from products.slack_app.backend.models import SlackThreadTaskMapping  # noqa: PLC0415

    mapping = SlackThreadTaskMapping.objects.filter(task_run=run).first()
    if mapping is None:
        if not raise_if_missing:
            return None
        raise ValueError("Task run is not mapped to a Slack thread")
    return mapping


def _slack_client_for_mapping(mapping: Any):
    return _slack_integration_for_mapping(mapping).client


def _slack_integration_for_mapping(mapping: Any):
    from posthog.models.integration import SlackIntegration  # noqa: PLC0415

    return SlackIntegration(mapping.integration)


def _upload_slack_file(
    slack: Any,
    *,
    channel: str,
    thread_ts: str,
    name: str,
    content: bytes,
    content_type: str,
    initial_comment: str | None = None,
) -> tuple[str, dict[str, Any]]:
    upload_response = slack.api_call(
        "files.getUploadURLExternal",
        data={"filename": name, "length": str(len(content))},
    )
    upload_url = upload_response.get("upload_url")
    file_id = upload_response.get("file_id")
    if not upload_url or not file_id:
        raise ValueError("Slack file upload did not return an upload URL and file id")

    response = requests.post(
        upload_url,
        data=content,
        headers={"Content-Type": content_type or DEFAULT_BINARY_CONTENT_TYPE},
        timeout=30,
    )
    response.raise_for_status()

    complete_payload = {
        "files": json.dumps([{"id": file_id, "title": name}]),
        "channel_id": channel,
        "thread_ts": thread_ts,
    }
    if initial_comment:
        complete_payload["initial_comment"] = initial_comment

    complete_response = slack.api_call("files.completeUploadExternal", data=complete_payload)
    files = complete_response.get("files") or []
    file_response = files[0] if files and isinstance(files[0], dict) else {"id": file_id, "title": name}
    completed_file_id = str(file_response.get("id") or file_id)
    return completed_file_id, file_response


def _slack_canvas_url(response: dict[str, Any] | None, workspace_id: str | None, canvas_id: str | None) -> str | None:
    if response:
        for key in ("url", "permalink", "canvas_url"):
            url = response.get(key)
            if isinstance(url, str) and url.startswith("https://"):
                return url
        canvas = response.get("canvas")
        if isinstance(canvas, dict):
            for key in ("url", "permalink", "canvas_url"):
                url = canvas.get(key)
                if isinstance(url, str) and url.startswith("https://"):
                    return url
    if workspace_id and canvas_id:
        return f"https://app.slack.com/docs/{workspace_id}/{canvas_id}"
    return None


def _escape_slack_mrkdwn_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _post_canvas_created_message(
    slack: Any, mapping: Any, name: str, canvas_id: str | None, canvas_url: str | None
) -> None:
    if not canvas_id:
        return
    escaped_name = _escape_slack_mrkdwn_text(name).replace("|", " ")
    escaped_canvas_id = _escape_slack_mrkdwn_text(canvas_id)
    canvas_reference = f"<{canvas_url}|{escaped_name}>" if canvas_url else f"*{escaped_name}*"
    try:
        slack.chat_postMessage(
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            text=f"Created Slack canvas {canvas_reference} (`{escaped_canvas_id}`).",
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError:
        logger.warning("task_artifact.canvas_notice_failed", task_run_id=str(mapping.task_run_id), exc_info=True)
