from __future__ import annotations

import io
import os
import json
import time
import uuid
import zipfile
import mimetypes
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import requests
import structlog
from slack_sdk.errors import SlackApiError

from posthog.event_usage import groups
from posthog.ph_client import ph_scoped_capture
from posthog.storage import object_storage
from posthog.utils import absolute_uri

from products.exports.backend.facade.api import get_delivery_image_url
from products.slack_app.backend.services.slack_messages import post_slack_thread_reply, slack_message_exists
from products.tasks.backend.models import TaskArtifact, TaskRun

logger = structlog.get_logger(__name__)

# Both scopes are approved (see posthog/helpers/slack_scopes.py), so the canvas and file adapters
# stay behind the slack-app-canvas-file-artifacts flag: scope checks alone would turn the feature
# on for every install that has them, with no rollout control.
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
    export_asset_id: int | None = None,
) -> TaskArtifact:
    _require_living_artifacts_enabled(run)
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
        run=run,
        name=name,
        artifact_type=artifact_type,
        content=content_payload,
        artifact_id=str(artifact_id),
        export_asset_id=export_asset_id,
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
            export_asset_id=export_asset_id,
        )
    return artifact


def edit_living_artifact(
    *,
    artifact: TaskArtifact,
    run: TaskRun | None = None,
    content: str | None = None,
    content_bytes: bytes | None = None,
    content_type: str | None = None,
    source_artifact_id: str | None = None,
    source_storage_path: str | None = None,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskArtifact:
    # `run` is the run performing the edit — a follow-up run editing a prior run's artifact
    # must resolve Slack mappings (repointed to the latest run) and storage paths as itself,
    # not as the run that originally created the artifact.
    run = run or artifact.task_run
    _require_living_artifacts_enabled(run)
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
        # The export only depicts the version it was rendered from, and an edit replaces the
        # content — so drop the link rather than let the new version deliver the old picture.
        locked.export_asset_id = None
        locked.versions = versions
        locked.current_version = next_version
        locked.status = TaskArtifact.Status.ACTIVE
        locked.save(
            update_fields=[
                "name",
                "adapter",
                "location",
                "metadata",
                "export_asset_id",
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


# Artifact ids are stable across a task's runs: Slack follow-ups resume a task with a fresh
# run, and the agent in that run must still see and edit deliverables produced by earlier
# runs. Lookups are therefore task-scoped, not run-scoped.
def get_task_artifacts_for_run(run: TaskRun) -> list[TaskArtifact]:
    return list(TaskArtifact.objects.for_team(run.team_id).filter(task_id=run.task_id).order_by("-updated_at"))


def get_task_artifact_for_run(run: TaskRun, artifact_id: str | UUID) -> TaskArtifact | None:
    return TaskArtifact.objects.for_team(run.team_id).filter(task_id=run.task_id, id=artifact_id).first()


def open_task_artifact(artifact: TaskArtifact) -> str | None:
    return _adapter_for_existing_artifact(artifact).open(artifact)


def _find_source_artifact(
    run: TaskRun,
    *,
    source_artifact_id: str | None,
    source_storage_path: str | None,
) -> dict[str, Any] | None:
    for candidate_run in reversed(run.get_resume_chain()):
        for artifact in candidate_run.artifacts or []:
            if source_artifact_id and str(artifact.get("id")) == str(source_artifact_id):
                return _require_shareable_source_artifact(artifact)
            if source_storage_path and artifact.get("storage_path") == source_storage_path:
                return _require_shareable_source_artifact(artifact)
    return None


def _require_shareable_source_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    # Run manifests also carry internal state (plans, context, tree snapshots, user
    # uploads). Living artifacts are deliverables that leave PostHog, so only files
    # the agent explicitly uploaded as run outputs may be used as a content source.
    if artifact.get("type") != "output" or artifact.get("source") != "agent_output":
        raise ValueError(
            "Source artifact is not a shareable run output: only files uploaded as type=output run artifacts "
            "can be delivered. Upload the file as an output artifact first, or pass content or content_base64."
        )
    return artifact


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
        export_asset_id: int | None = None,
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
            export_asset_id=export_asset_id,
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
        export_asset_id: int | None = None,
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
        export_asset_id: int | None = None,
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
                    export_asset_id=export_asset_id,
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
        export_asset_id: int | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        text = content.strip() or name
        if artifact is None:
            response = post_slack_thread_reply(
                _slack_client_for_mapping(mapping),
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            if response is None:
                raise ValueError("Slack message artifact has no thread left to deliver into")
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
        export_asset_id: int | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        if not _canvas_file_artifacts_enabled(mapping):
            raise ValueError(
                "Slack canvas delivery is not enabled for this workspace: you do not have this capability. "
                "Use adapter=slack_message and deliver the content as text instead."
            )
        slack_integration = _slack_integration_for_mapping(mapping)
        missing_scopes = slack_integration.missing_scopes(frozenset({SLACK_CANVAS_SCOPE}))
        if missing_scopes:
            raise ValueError(
                "Slack canvas delivery is unavailable: the Slack integration is missing the canvases:write scope, "
                "so you do not have this capability. Use adapter=slack_message and deliver the content as text instead."
            )
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


# Slack re-fetches image_url after the message is posted, so the token has to outlive the
# post. Scoped to the artifact's own 30-day storage TTL rather than the 365-day default.
_CHART_IMAGE_URL_TTL = timedelta(days=30)


def _delivery_image_url(team_id: int, export_asset_id: int | None) -> str | None:
    """Mint the url delivery references for a chart image, or None when there is no export.

    The url is trustworthy because it is minted here from the export link the chart
    endpoint set server-side (a dedicated column callers can never write).
    """
    if export_asset_id is None:
        return None
    return get_delivery_image_url(team_id=team_id, asset_id=export_asset_id, expiry_delta=_CHART_IMAGE_URL_TTL)


def _is_url_backed_image(content_type: str, *, team_id: int, export_asset_id: int | None) -> bool:
    """Whether delivery can post this version as an image block instead of an upload.

    Reads only the link being written with this version, so an edit (which always drops
    the export link) needs files:write for its new bytes rather than passing on the
    strength of the old render.
    """
    if not content_type.startswith("image/"):
        return False
    return _delivery_image_url(team_id, export_asset_id) is not None


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
        export_asset_id: int | None = None,
    ) -> ArtifactCommit:
        mapping = _get_slack_mapping(run)
        if not _canvas_file_artifacts_enabled(mapping):
            raise ValueError(
                "Slack file delivery is not enabled for this workspace: you do not have this capability. "
                "Use adapter=slack_message and summarize the result as text instead."
            )
        slack_integration = _slack_integration_for_mapping(mapping)
        resolved_content_type = content_type or _guess_content_type(name)
        # Chart images deliver as image blocks referencing a PostHog-hosted url, which needs no
        # upload and therefore no files:write. Everything else (non-images, and images with no
        # resolvable export) goes out as an upload, so it needs the scope up front — accepting it
        # here would leave the artifact pending forever with the agent believing it was delivered.
        if not _is_url_backed_image(resolved_content_type, team_id=run.team_id, export_asset_id=export_asset_id) and (
            slack_integration.missing_scopes(frozenset({SLACK_FILE_SCOPE}))
        ):
            raise ValueError(
                "Slack file delivery is unavailable: the Slack integration is missing the files:write scope, "
                "so you do not have this capability. Use adapter=slack_message and summarize the result as text instead."
            )

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


# Task-scoped (like the artifact lookups above): a follow-up run that edits a prior run's
# file artifact leaves the pending version on that artifact, and this run's end-of-turn
# delivery must pick it up.
def has_pending_slack_file_artifacts(run: TaskRun) -> bool:
    if not _living_artifacts_enabled_for_run(run):
        return False

    artifacts = TaskArtifact.objects.for_team(run.team_id).filter(
        task_id=run.task_id,
        adapter=TaskArtifact.Adapter.SLACK_FILE,
        status=TaskArtifact.Status.ACTIVE,
    )
    return any(_pending_slack_file_version(artifact) is not None for artifact in artifacts)


# Mutable: delivery accumulates into it as each card is posted.
@dataclass(frozen=False)
class SlackFileDeliveryResult:
    answer_posted: bool = False
    delivered_count: int = 0


def has_pending_slack_image_artifacts(run: TaskRun) -> bool:
    for artifact in _pending_slack_file_queryset(run):
        pending = _pending_slack_file_version(artifact)
        if pending is None:
            continue
        content_type = _pending_slack_content_type(artifact, pending[1])
        if content_type.startswith("image/"):
            return True
    return False


def deliver_pending_slack_file_artifacts(
    run: TaskRun, *, answer_sections: list[str] | None = None
) -> SlackFileDeliveryResult:
    """Deliver pending slack_file artifacts to the mapped thread.

    Images compose into a single chat message together with ``answer_sections``
    (the relay's converted answer text): text sections first, then one card per
    chart (title, image block, "Open in PostHog" button). Chart images reference a
    url minted here from their export asset — Slack's image proxy fetches the PNG
    from us, so no file upload (and no files:write scope) is involved; other images
    upload without a channel share and are referenced by file id. chat.postMessage
    is synchronous, so the whole answer lands atomically — unlike channel file
    shares, which Slack materializes asynchronously. Non-image files still deliver
    as channel shares (these do need files:write), after the composed message.
    ``answer_posted`` tells the caller whether the answer text went out in the
    composed message so it isn't posted twice.
    """
    result = SlackFileDeliveryResult()
    mapping = _get_slack_mapping(run, raise_if_missing=False)
    if mapping is None:
        return result

    if not _living_artifacts_enabled_for_mapping(mapping):
        logger.warning("task_artifact.slack_living_artifacts_disabled", task_run_id=str(run.id))
        return result

    if not _canvas_file_artifacts_enabled(mapping):
        logger.warning("task_artifact.slack_file_delivery_disabled", task_run_id=str(run.id))
        return result

    slack_integration = _slack_integration_for_mapping(mapping)
    # Nobody is waiting on charts or file shares for a prompt that has been deleted.
    # Leave the artifacts pending rather than delivering them into the thread.
    if not slack_message_exists(slack_integration.client, mapping.channel, mapping.thread_ts):
        logger.warning("task_artifact.slack_delivery_skipped_message_deleted", task_run_id=str(run.id))
        return result

    has_file_scope = not slack_integration.missing_scopes(frozenset({SLACK_FILE_SCOPE}))

    # The relay activity's start_to_close_timeout is a minute; a self-inflicted timeout would
    # replay it and repost everything, so budget all Slack I/O — uploads included — and stop
    # rather than run past it. Whatever misses the budget stays pending for the next relay.
    deadline = time.monotonic() + _SLACK_POST_BUDGET_S

    slack = slack_integration.client
    pending_files: list[tuple[TaskArtifact, dict[str, Any], str]] = []
    for artifact in _pending_slack_file_queryset(run):
        pending = _pending_slack_file_version(artifact)
        if pending is None:
            continue
        _version_index, version_payload = pending
        pending_files.append((artifact, version_payload, _pending_slack_content_type(artifact, version_payload)))

    image_files = [f for f in pending_files if f[2].startswith("image/")]
    other_files = [f for f in pending_files if not f[2].startswith("image/")]

    # (artifact, failure_reason or None, delivery_mode) for chart artifacts only —
    # export_asset_id marks an image as chart-endpoint output.
    chart_outcomes: list[tuple[TaskArtifact, str | None, str | None]] = []

    def _record_chart(artifact: TaskArtifact, failure_reason: str | None, delivery_mode: str | None = None) -> None:
        if artifact.export_asset_id is not None:
            chart_outcomes.append((artifact, failure_reason, delivery_mode))

    image_cards: list[_SlackImageCard] = []
    for artifact, version_payload, content_type in image_files:
        # Slack fetches the image from the url in the card — nothing to upload. An artifact
        # whose export can't be resolved for this team falls through to the upload path,
        # which posts the stored bytes instead.
        image_url = _delivery_image_url(run.team_id, artifact.export_asset_id)
        if image_url is not None:
            image_cards.append(_SlackImageCard(artifact, version_payload, image_url=image_url))
            continue
        if artifact.export_asset_id is not None:
            logger.warning("task_artifact.chart_export_asset_unresolved", artifact_id=str(artifact.id))
        if not has_file_scope:
            logger.warning(
                "task_artifact.slack_file_delivery_missing_scope",
                artifact_id=str(artifact.id),
                missing_scopes=[SLACK_FILE_SCOPE],
            )
            _record_chart(artifact, "missing_scope")
            continue
        if time.monotonic() >= deadline:
            logger.warning("task_artifact.slack_post_budget_exhausted", artifact_id=str(artifact.id))
            _record_chart(artifact, "budget_exhausted")
            continue
        payload = _read_pending_slack_file_bytes(artifact, version_payload)
        if payload is None:
            _record_chart(artifact, "payload_missing")
            continue
        try:
            file_id, file_response = _upload_slack_file(
                slack, channel=None, thread_ts=None, name=artifact.name, content=payload, content_type=content_type
            )
        except Exception:
            logger.warning("task_artifact.slack_file_delivery_failed", artifact_id=str(artifact.id), exc_info=True)
            _record_chart(artifact, "upload_failed")
            continue
        image_cards.append(_SlackImageCard(artifact, version_payload, file_id=file_id, file_response=file_response))

    if image_cards:
        # Only cards that actually reached the thread are delivered — an unposted image
        # is invisible (it uploaded with no channel share), so marking it delivered
        # would lose it permanently instead of leaving it pending for the next relay.
        delivered_artifact_ids: set[UUID] = set()

        def _mark_card_delivered(card: _SlackImageCard) -> None:
            if _mark_slack_file_artifact_delivered(
                artifact=card.artifact,
                version_number=int(card.version_payload.get("version") or card.artifact.current_version or 0),
                file_id=card.file_id,
                file_response=card.file_response,
            ):
                result.delivered_count += 1
                delivered_artifact_ids.add(card.artifact.id)
                _record_chart(card.artifact, None, "url" if card.image_url else "file_upload")

        result.answer_posted = _post_composed_answer_message(
            slack,
            mapping=mapping,
            image_cards=image_cards,
            answer_sections=answer_sections or [],
            mark_delivered=_mark_card_delivered,
            deadline=deadline,
        )
        for card in image_cards:
            if card.artifact.id not in delivered_artifact_ids:
                _record_chart(card.artifact, "message_not_posted")
    elif answer_sections is not None:
        # Compose was requested but every image upload failed: the answer text must
        # still land — and before the non-image shares below, to keep thread order.
        sections = [section for section in answer_sections if section.strip()]
        posted = [_post_thread_text(slack, mapping=mapping, text=section) for section in sections]
        result.answer_posted = bool(sections) and all(posted)

    for artifact, version_payload, content_type in other_files:
        if not has_file_scope:
            logger.warning(
                "task_artifact.slack_file_delivery_missing_scope",
                artifact_id=str(artifact.id),
                missing_scopes=[SLACK_FILE_SCOPE],
            )
            continue
        if time.monotonic() >= deadline:
            logger.warning("task_artifact.slack_post_budget_exhausted", artifact_id=str(artifact.id))
            continue
        payload = _read_pending_slack_file_bytes(artifact, version_payload)
        if payload is None:
            continue
        try:
            file_id, file_response = _upload_slack_file(
                slack,
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                name=artifact.name,
                content=payload,
                content_type=content_type,
            )
        except Exception:
            logger.warning("task_artifact.slack_file_delivery_failed", artifact_id=str(artifact.id), exc_info=True)
            continue
        if _mark_slack_file_artifact_delivered(
            artifact=artifact,
            version_number=int(version_payload.get("version") or artifact.current_version or 0),
            file_id=file_id,
            file_response=file_response,
        ):
            result.delivered_count += 1

    _capture_chart_delivery_events(run, chart_outcomes)
    return result


def _capture_chart_delivery_events(run: TaskRun, outcomes: list[tuple[TaskArtifact, str | None, str | None]]) -> None:
    """Emit one analytics event per chart delivery attempt. Runs in the Temporal
    worker, where the global posthoganalytics client drops events — hence the
    scoped client."""
    if not outcomes:
        return
    try:
        team = run.team
        with ph_scoped_capture() as capture:
            for artifact, failure_reason, delivery_mode in outcomes:
                capture(
                    distinct_id=str(artifact.created_by.distinct_id if artifact.created_by else team.uuid),
                    event="task_chart_slack_delivery_failed" if failure_reason else "task_chart_slack_delivered",
                    properties={
                        "artifact_id": str(artifact.id),
                        "task_id": str(artifact.task_id),
                        "run_id": str(run.id),
                        "export_asset_id": artifact.export_asset_id,
                        "delivery_mode": delivery_mode,
                        "failure_reason": failure_reason,
                    },
                    groups=groups(team.organization, team),
                )
    except Exception:
        logger.warning("task_artifact.chart_delivery_capture_failed", task_run_id=str(run.id), exc_info=True)


def _pending_slack_file_queryset(run: TaskRun) -> QuerySet[TaskArtifact]:
    return (
        TaskArtifact.objects.for_team(run.team_id)
        .filter(
            task_id=run.task_id,
            adapter=TaskArtifact.Adapter.SLACK_FILE,
            status=TaskArtifact.Status.ACTIVE,
        )
        .order_by("created_at", "id")
    )


def _read_pending_slack_file_bytes(artifact: TaskArtifact, version_payload: dict[str, Any]) -> bytes | None:
    raw_location = version_payload.get("location")
    location = raw_location if isinstance(raw_location, dict) else {}
    storage_path = str(location.get("storage_path") or (artifact.location or {}).get("storage_path") or "")
    if not storage_path:
        logger.warning("task_artifact.slack_file_missing_storage_path", artifact_id=str(artifact.id))
        return None
    payload = object_storage.read_bytes(storage_path, missing_ok=True)
    if payload is None:
        logger.warning(
            "task_artifact.slack_file_pending_content_missing",
            artifact_id=str(artifact.id),
            storage_path=storage_path,
        )
        return None
    return payload


def _pending_slack_content_type(artifact: TaskArtifact, version_payload: dict[str, Any]) -> str:
    raw_location = version_payload.get("location")
    location = raw_location if isinstance(raw_location, dict) else {}
    return str(
        version_payload.get("content_type")
        or location.get("content_type")
        or (artifact.location or {}).get("content_type")
        or _guess_content_type(artifact.name)
    )


# Slack caps a message at 50 blocks; leading answer sections spill into plain
# messages when a message would exceed it.
_SLACK_MESSAGE_BLOCK_LIMIT = 50


@dataclass(frozen=True)
class _SlackImageCard:
    artifact: TaskArtifact
    version_payload: dict[str, Any]
    # A card carries either a minted image_url (nothing uploaded) or an uploaded file id.
    image_url: str | None = None
    file_id: str | None = None
    file_response: dict[str, Any] | None = None


def _post_composed_answer_message(
    slack: Any,
    *,
    mapping: Any,
    image_cards: list[_SlackImageCard],
    answer_sections: list[str],
    mark_delivered: Callable[[_SlackImageCard], None],
    deadline: float,
) -> bool:
    """Post answer text and chart cards, composed into one message when possible.

    Returns whether the answer text fully reached the thread — a partial post returns
    False so the caller reposts the whole answer (a duplicated chunk beats silently
    losing the rest). ``mark_delivered`` is called for each card as soon as its own
    post succeeds, so an activity that dies part-way through doesn't replay the cards
    that already landed."""
    sections = [section for section in answer_sections if section.strip()]
    section_blocks = _section_blocks(sections)
    card_blocks: list[dict[str, Any]] = []
    for card in image_cards:
        card_blocks.extend(_chart_card_blocks(card))

    spill_count = max(len(section_blocks) - max(_SLACK_MESSAGE_BLOCK_LIMIT - len(card_blocks), 0), 0)
    posted_blocks = 0
    for block in section_blocks[:spill_count]:
        posted_blocks += 1 if _post_thread_text(slack, mapping=mapping, text=block["text"]["text"]) else 0
    kept = section_blocks[spill_count:]

    # Cards alone can exceed the block cap (17+ charts) — composing would then fail
    # deterministically as invalid_blocks, so go straight to the per-card path.
    if len(kept) + len(card_blocks) <= _SLACK_MESSAGE_BLOCK_LIMIT:
        fallback_text = sections[0] if sections else _artifact_fallback_text(image_cards[0].artifact)
        try:
            if _post_blocks_with_processing_retry(
                slack,
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                text=fallback_text,
                blocks=[*kept, *card_blocks],
                deadline=deadline,
            ):
                for card in image_cards:
                    mark_delivered(card)
                posted_blocks += len(kept)
                return bool(section_blocks) and posted_blocks == len(section_blocks)
        except Exception:
            logger.warning("task_artifact.slack_composed_message_failed", exc_info=True)

    # Degraded path: the answer must not be lost — post the text plainly, then each
    # card on its own so one bad card can't sink the others.
    for block in kept:
        posted_blocks += 1 if _post_thread_text(slack, mapping=mapping, text=block["text"]["text"]) else 0
    for card in image_cards:
        try:
            if _post_blocks_with_processing_retry(
                slack,
                channel=mapping.channel,
                thread_ts=mapping.thread_ts,
                text=_artifact_fallback_text(card.artifact),
                blocks=_chart_card_blocks(card),
                attempts=_IMAGE_BLOCK_FALLBACK_ATTEMPTS,
                deadline=deadline,
            ):
                mark_delivered(card)
        except Exception:
            logger.warning("task_artifact.slack_file_delivery_failed", artifact_id=str(card.artifact.id), exc_info=True)
    return bool(section_blocks) and posted_blocks == len(section_blocks)


# Section blocks hard-cap at 3000 chars. The relay pre-splits at 2900 before conversion,
# but the mention prefix and mrkdwn expansion (table column padding, escapes) can push a
# section past that — re-split after conversion, preferring whitespace so the cut doesn't
# land inside a converted mrkdwn entity like `<url|text>`. Tables convert to fenced blocks,
# so a cut inside one is closed and reopened to keep each block self-contained.
_SLACK_SECTION_BLOCK_CHAR_LIMIT = 3000
_SLACK_CODE_FENCE = "```"


def _section_blocks(sections: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in sections:
        for piece in _split_section_text(section):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": piece}})
    return blocks


def _split_section_text(section: str) -> list[str]:
    pieces: list[str] = []
    remaining = section
    reopen = ""
    while True:
        candidate = reopen + remaining
        if len(candidate) <= _SLACK_SECTION_BLOCK_CHAR_LIMIT:
            if candidate.strip():
                pieces.append(candidate)
            return pieces
        limit = _SLACK_SECTION_BLOCK_CHAR_LIMIT
        if candidate[:limit].count(_SLACK_CODE_FENCE) % 2:
            limit -= len(f"\n{_SLACK_CODE_FENCE}")
        window = candidate[:limit]
        cut = max(window.rfind("\n"), window.rfind(" "))
        # A cut inside the reopen prefix would emit just "```" and never consume any of
        # remaining — an infinite loop when a fenced block wraps whitespace-free content.
        if cut <= len(reopen):
            cut = limit
        piece = candidate[:cut]
        remaining = candidate[cut:].lstrip(" \n")
        reopen = ""
        if piece.count(_SLACK_CODE_FENCE) % 2:
            piece += f"\n{_SLACK_CODE_FENCE}"
            reopen = f"{_SLACK_CODE_FENCE}\n"
        if piece.strip():
            pieces.append(piece)


def _post_thread_text(slack: Any, *, mapping: Any, text: str) -> bool:
    """Post one plain text message, reporting whether it landed — callers use this to decide
    whether the answer still needs a fallback, so a swallowed failure must not read as sent."""
    try:
        return (
            post_slack_thread_reply(slack, channel=mapping.channel, thread_ts=mapping.thread_ts, text=text) is not None
        )
    except Exception:
        logger.warning("task_artifact.slack_thread_text_failed", exc_info=True)
        return False


# A freshly completed upload can't be referenced in blocks until Slack finishes
# processing it — chat.postMessage returns invalid_blocks ("invalid slack file")
# for a second or two. Verified empirically; retry until the reference resolves.
_IMAGE_BLOCK_POST_ATTEMPTS = 8
# The per-card fallback runs once per chart after the composed attempt already burned
# its budget; keep it short so the relay activity stays within its timeout.
_IMAGE_BLOCK_FALLBACK_ATTEMPTS = 3
_IMAGE_BLOCK_POST_RETRY_INTERVAL_S = 1.0
_RATE_LIMIT_MAX_WAIT_S = 10.0
# Total wall-clock budget for all Slack I/O in one delivery (uploads and posts), under
# the relay activity's start_to_close_timeout of 1 minute.
_SLACK_POST_BUDGET_S = 45.0
# Slack rejects button urls over 3000 chars, and an ad-hoc chart url embeds the whole
# encoded query JSON — a fat multi-series query can exceed it.
_SLACK_BUTTON_URL_MAX_CHARS = 3000


def _is_posthog_origin_url(url: str) -> bool:
    try:
        candidate = urlparse(url)
        expected = urlparse(absolute_uri("/"))
    except ValueError:
        return False
    return candidate.scheme == expected.scheme and candidate.netloc == expected.netloc


def _artifact_display_title(artifact: TaskArtifact) -> str:
    # The artifact name is a filename (the chart endpoint appends .png); Slack titles
    # and notification previews are display copy, so drop the extension there.
    return os.path.splitext(artifact.name)[0] or artifact.name


def _artifact_fallback_text(artifact: TaskArtifact) -> str:
    # Slack parses a message's top-level text as mrkdwn, so an artifact named `<@U…>` or
    # `<!channel>` would notify from the PostHog bot — escape it like the title block does.
    return _escape_slack_mrkdwn_text(_artifact_display_title(artifact))


def _chart_card_blocks(card: _SlackImageCard) -> list[dict[str, Any]]:
    artifact = card.artifact
    metadata = artifact.metadata or {}
    title = _artifact_display_title(artifact)
    if card.image_url is not None:
        image_block: dict[str, Any] = {"type": "image", "image_url": card.image_url, "alt_text": title}
    else:
        image_block = {"type": "image", "slack_file": {"id": card.file_id}, "alt_text": title}
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{_escape_slack_mrkdwn_text(title)}*"}},
        image_block,
    ]
    posthog_url = metadata.get("posthog_url")
    if isinstance(posthog_url, str) and posthog_url and not _is_posthog_origin_url(posthog_url):
        # Metadata is caller-writable through the generic living-artifact create/edit APIs, so an
        # unchecked url would let a task writer publish a phishing button as the PostHog bot.
        logger.warning(
            "task_artifact.chart_url_untrusted_origin",
            artifact_id=str(artifact.id),
        )
    elif isinstance(posthog_url, str) and 0 < len(posthog_url) <= _SLACK_BUTTON_URL_MAX_CHARS:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in PostHog", "emoji": True},
                        "url": posthog_url,
                    }
                ],
            }
        )
    elif isinstance(posthog_url, str) and posthog_url:
        logger.warning(
            "task_artifact.chart_url_too_long_for_button",
            artifact_id=str(artifact.id),
            url_length=len(posthog_url),
        )
    return blocks


def _post_blocks_with_processing_retry(
    slack: Any,
    *,
    channel: str,
    thread_ts: str,
    text: str,
    blocks: list[dict[str, Any]],
    attempts: int = _IMAGE_BLOCK_POST_ATTEMPTS,
    deadline: float | None = None,
) -> bool:
    """Whether the message actually landed. A skipped post — the message it would answer
    is gone — returns False, so the caller leaves the cards pending instead of delivered."""
    for attempt in range(1, attempts + 1):
        try:
            posted = post_slack_thread_reply(slack, channel=channel, thread_ts=thread_ts, text=text, blocks=blocks)
            return posted is not None
        except SlackApiError as e:
            error = e.response.get("error")
            if attempt == attempts or error not in ("invalid_blocks", "ratelimited"):
                raise
            if error == "ratelimited":
                headers = getattr(e.response, "headers", None) or {}
                try:
                    retry_after = float(headers.get("Retry-After") or _IMAGE_BLOCK_POST_RETRY_INTERVAL_S)
                except (TypeError, ValueError):
                    retry_after = _IMAGE_BLOCK_POST_RETRY_INTERVAL_S
                wait = min(retry_after, _RATE_LIMIT_MAX_WAIT_S)
            else:
                wait = _IMAGE_BLOCK_POST_RETRY_INTERVAL_S
            if deadline is not None and time.monotonic() + wait >= deadline:
                raise
            time.sleep(wait)
    return False  # unreachable: attempts >= 1, so the loop always returns or raises


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
    raw_location = version.get("location")
    location = raw_location if isinstance(raw_location, dict) else {}
    if not location.get("storage_path"):
        return None
    return index, version


def _mark_slack_file_artifact_delivered(
    *,
    artifact: TaskArtifact,
    version_number: int,
    file_id: str | None,
    file_response: dict[str, Any] | None,
) -> bool:
    """``file_id``/``file_response`` are None for url-referenced images, which post
    without a Slack file upload."""
    with transaction.atomic():
        locked = TaskArtifact.objects.for_team(artifact.team_id).select_for_update().get(pk=artifact.pk)
        pending = _pending_slack_file_version(locked)
        if pending is None:
            return False

        version_index, version_payload = pending
        if int(version_payload.get("version") or 0) != version_number:
            return False

        delivered_location = {**(locked.location or {}), "delivery_status": "delivered"}
        delivered_version = {**version_payload, "delivery_status": "delivered"}
        delivered_metadata = {**(locked.metadata or {}), "delivery_status": "delivered"}
        if file_id:
            file_title = str((file_response or {}).get("title") or locked.name)
            file_permalink = (file_response or {}).get("permalink")
            delivered_location["file_id"] = file_id
            delivered_version["slack_file_id"] = file_id
            delivered_version["slack_file_title"] = file_title
            delivered_metadata["slack_file_id"] = file_id
            delivered_metadata["slack_file_title"] = file_title
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


def _living_artifacts_enabled_for_run(run: TaskRun) -> bool:
    mapping = _get_slack_mapping(run, raise_if_missing=False)
    return mapping is None or _living_artifacts_enabled_for_mapping(mapping)


def _living_artifacts_enabled_for_mapping(mapping: Any) -> bool:
    from products.slack_app.backend.feature_flags import is_slack_app_living_artifacts_enabled  # noqa: PLC0415

    return is_slack_app_living_artifacts_enabled(mapping.integration)


def _require_living_artifacts_enabled(run: TaskRun) -> None:
    if not _living_artifacts_enabled_for_run(run):
        raise ValueError(
            "Living artifacts are not enabled for this Slack workspace: you cannot create or deliver "
            "artifacts on this run. Deliver results as plain text in your reply instead."
        )


def _canvas_file_artifacts_enabled(mapping: Any) -> bool:
    from products.slack_app.backend.feature_flags import is_slack_app_canvas_file_artifacts_enabled  # noqa: PLC0415

    return is_slack_app_canvas_file_artifacts_enabled(mapping.integration)


def _slack_client_for_mapping(mapping: Any):
    return _slack_integration_for_mapping(mapping).client


def _slack_integration_for_mapping(mapping: Any):
    from posthog.models.integration import SlackIntegration  # noqa: PLC0415

    return SlackIntegration(mapping.integration)


def _upload_slack_file(
    slack: Any,
    *,
    channel: str | None,
    thread_ts: str | None,
    name: str,
    content: bytes,
    content_type: str,
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

    complete_payload = {"files": json.dumps([{"id": file_id, "title": name}])}
    if channel:
        complete_payload["channel_id"] = channel
        if thread_ts:
            complete_payload["thread_ts"] = thread_ts
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
        post_slack_thread_reply(
            slack,
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            text=f"Created Slack canvas {canvas_reference} (`{escaped_canvas_id}`).",
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError:
        logger.warning("task_artifact.canvas_notice_failed", task_run_id=str(mapping.task_run_id), exc_info=True)
