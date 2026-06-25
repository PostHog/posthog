from __future__ import annotations

import os
import json
import uuid
import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass
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


def register_s3_manifest_artifact(run: TaskRun, manifest_entry: dict[str, Any]) -> TaskArtifact:
    artifact_id = str(manifest_entry.get("id") or "")
    name = str(manifest_entry.get("name") or "artifact")
    storage_path = str(manifest_entry.get("storage_path") or "")
    if not storage_path:
        raise ValueError("S3 artifact registration requires a storage_path")
    location = {
        "kind": "s3",
        "storage_path": storage_path,
        "content_type": manifest_entry.get("content_type") or "",
    }
    version = {
        "version": 1,
        "run_id": str(run.id),
        "adapter": TaskArtifact.Adapter.S3,
        "location": location,
        "content_type": manifest_entry.get("content_type") or "",
        "size": manifest_entry.get("size"),
        "source_artifact_id": artifact_id,
        "created_at": manifest_entry.get("uploaded_at") or timezone.now().isoformat(),
    }
    defaults = {
        "team": run.team,
        "task": run.task,
        "task_run": run,
        "created_by": run.task.created_by,
        "name": name,
        "artifact_type": _artifact_type_from_manifest(manifest_entry),
        "adapter": TaskArtifact.Adapter.S3,
        "status": TaskArtifact.Status.ACTIVE,
        "location": location,
        "metadata": {
            "source": manifest_entry.get("source") or "",
            "source_artifact_id": artifact_id,
            "raw_manifest_entry": manifest_entry,
        },
        "versions": [version],
        "current_version": 1,
    }
    with transaction.atomic():
        artifact = (
            TaskArtifact.objects.for_team(run.team_id)
            .select_for_update()
            .filter(task_run=run, metadata__source_artifact_id=artifact_id)
            .first()
        )
        if artifact is None:
            artifact = (
                TaskArtifact.objects.for_team(run.team_id)
                .select_for_update()
                .filter(task_run=run, location__storage_path=storage_path)
                .first()
            )
        if artifact is None:
            return TaskArtifact.objects.for_team(run.team_id).create(**defaults)

        for key, value in defaults.items():
            setattr(artifact, key, value)
        artifact.save(
            update_fields=[
                "team",
                "task",
                "task_run",
                "created_by",
                "name",
                "artifact_type",
                "adapter",
                "status",
                "location",
                "metadata",
                "versions",
                "current_version",
                "updated_at",
            ]
        )
        return artifact


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
    selected_adapter = _resolve_adapter(adapter, artifact_type)
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
    content_payload = resolve_artifact_content(
        run=run,
        name=name or artifact.name,
        content=content,
        content_bytes=content_bytes,
        content_type=content_type,
        source_artifact_id=source_artifact_id,
        source_storage_path=source_storage_path,
    )
    existing_content = selected_adapter.open(artifact)
    next_content = selected_adapter.apply_edit(existing_content, content_payload.body)
    commit = selected_adapter.commit(
        artifact=artifact,
        run=run,
        name=name or artifact.name,
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
        locked.name = name or locked.name
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


def _resolve_adapter(adapter: str | None, artifact_type: str) -> LivingArtifactAdapter:
    if adapter == TaskArtifact.Adapter.SLACK_MESSAGE or artifact_type == TaskArtifact.ArtifactType.SLACK_MESSAGE:
        return SlackMessageArtifactAdapter()
    if adapter == TaskArtifact.Adapter.SLACK_CANVAS or artifact_type == TaskArtifact.ArtifactType.SLACK_CANVAS:
        return SlackCanvasArtifactAdapter()
    if adapter == TaskArtifact.Adapter.SLACK_FILE:
        return SlackFileArtifactAdapter()
    if adapter == TaskArtifact.Adapter.DOCUMENT_CONNECTOR:
        return DocumentConnectorArtifactAdapter()
    if adapter == TaskArtifact.Adapter.S3:
        return S3ArtifactAdapter()
    if artifact_type in {TaskArtifact.ArtifactType.DOCUMENT, TaskArtifact.ArtifactType.SPREADSHEET}:
        return DocumentConnectorArtifactAdapter()
    return S3ArtifactAdapter()


def _adapter_for_existing_artifact(artifact: TaskArtifact) -> LivingArtifactAdapter:
    if artifact.adapter == TaskArtifact.Adapter.SLACK_MESSAGE:
        return SlackMessageArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.SLACK_CANVAS:
        return SlackCanvasArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.SLACK_FILE:
        return SlackFileArtifactAdapter()
    if artifact.adapter == TaskArtifact.Adapter.DOCUMENT_CONNECTOR:
        return DocumentConnectorArtifactAdapter()
    return S3ArtifactAdapter()


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


class S3ArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.S3

    def open(self, artifact: TaskArtifact) -> str | None:
        storage_path = (artifact.location or {}).get("storage_path")
        if not storage_path:
            return None
        content_type = str((artifact.location or {}).get("content_type") or "")
        if not _is_textual_name_and_type(artifact.name, content_type):
            return None
        return object_storage.read(storage_path, missing_ok=True)

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
        artifact_key = str(artifact.id) if artifact is not None else artifact_id or uuid.uuid4().hex
        storage_path = build_living_artifact_storage_path(run, artifact_key, version, name)
        content_type = content_type or DEFAULT_DOCUMENT_CONTENT_TYPE
        payload = content_bytes if content_bytes is not None else content.encode("utf-8")
        object_storage.write(storage_path, payload, {"ContentType": content_type})
        _tag_living_artifact_object(run, storage_path)
        location = {"kind": "s3", "storage_path": storage_path, "content_type": content_type}
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={"storage": "object_storage"},
            version=_version_payload(
                version=version,
                run=run,
                adapter=self.adapter,
                location=location,
                content_type=content_type,
                source_artifact=source_artifact,
                size=len(payload),
            ),
        )


class DocumentConnectorArtifactAdapter(LivingArtifactAdapter):
    adapter = TaskArtifact.Adapter.DOCUMENT_CONNECTOR

    def open(self, artifact: TaskArtifact) -> str | None:
        if (artifact.location or {}).get("kind") == "s3":
            return S3ArtifactAdapter().open(artifact)

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
        fallback_reason = "no_user_connector"
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
            except DocumentConnectorUnavailable:
                fallback_reason = "connector_unavailable"
                logger.info("task_run.document_connector_unavailable", run_id=str(run.id))
            else:
                return ArtifactCommit(
                    adapter=self.adapter,
                    location=commit.location,
                    metadata={**commit.metadata, "document_connector_status": "connected"},
                    version={**commit.version, "adapter": self.adapter, "document_connector_status": "connected"},
                )

        commit = S3ArtifactAdapter().commit(
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
        return ArtifactCommit(
            adapter=self.adapter,
            location=commit.location,
            metadata={
                **commit.metadata,
                "document_connector_status": "fallback_s3",
                "document_connector_fallback_reason": fallback_reason,
            },
            version={
                **commit.version,
                "adapter": self.adapter,
                "document_connector_status": "fallback_s3",
                "document_connector_fallback_reason": fallback_reason,
            },
        )


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
            canvas_id = response.get("canvas_id")
            if not canvas_id:
                raise ValueError("Slack canvas delivery did not return a canvas id")
            _post_canvas_created_message(slack, mapping, name, canvas_id)
        else:
            canvas_id = (artifact.location or {}).get("canvas_id")
            if not canvas_id:
                raise ValueError("Slack canvas artifact is missing a canvas id")
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
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={"slack_workspace_id": mapping.slack_workspace_id},
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
        slack = slack_integration.client
        file_id, file_response = _upload_slack_file(
            slack,
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            name=name,
            content=payload,
            content_type=resolved_content_type,
            initial_comment=_slack_file_initial_comment(name, version),
        )
        location = {
            "kind": "slack_file",
            "integration_id": mapping.integration_id,
            "channel": mapping.channel,
            "thread_ts": mapping.thread_ts,
            "file_id": file_id,
            "content_type": resolved_content_type,
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
        version_payload["slack_file_id"] = file_id
        return ArtifactCommit(
            adapter=self.adapter,
            location=location,
            metadata={
                "slack_workspace_id": mapping.slack_workspace_id,
                "slack_file_id": file_id,
                "slack_file_title": file_response.get("title") or name,
                "slack_file_permalink": file_response.get("permalink"),
                "size": len(payload),
            },
            version=version_payload,
        )


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


def _get_slack_mapping(run: TaskRun):
    from products.slack_app.backend.models import SlackThreadTaskMapping  # noqa: PLC0415

    mapping = SlackThreadTaskMapping.objects.filter(task_run=run).first()
    if mapping is None:
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
    initial_comment: str,
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

    complete_response = slack.api_call(
        "files.completeUploadExternal",
        data={
            "files": json.dumps([{"id": file_id, "title": name}]),
            "channel_id": channel,
            "thread_ts": thread_ts,
            "initial_comment": initial_comment,
        },
    )
    files = complete_response.get("files") or []
    file_response = files[0] if files and isinstance(files[0], dict) else {"id": file_id, "title": name}
    completed_file_id = str(file_response.get("id") or file_id)
    return completed_file_id, file_response


def _slack_file_initial_comment(name: str, version: int) -> str:
    if version <= 1:
        return f"Uploaded *{name}*."
    return f"Uploaded version {version} of *{name}*."


def _post_canvas_created_message(slack: Any, mapping: Any, name: str, canvas_id: str | None) -> None:
    if not canvas_id:
        return
    try:
        slack.chat_postMessage(
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            text=f"Created Slack canvas *{name}* (`{canvas_id}`).",
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError:
        logger.warning("task_artifact.canvas_notice_failed", task_run_id=str(mapping.task_run_id), exc_info=True)
