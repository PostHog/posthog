from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import structlog

from posthog.storage import object_storage

from products.tasks.backend.models import Task, TaskRun

STAGED_TASK_ARTIFACT_CACHE_TTL_SECONDS = 24 * 60 * 60
RUN_ARTIFACT_TTL_DAYS = "30"
STAGED_ARTIFACT_TTL_DAYS = "1"

logger = structlog.get_logger(__name__)


def get_safe_artifact_name(name: str) -> str:
    return os.path.basename(name).strip() or "artifact"


def build_task_staged_artifact_cache_key(task_id: str, artifact_id: str) -> str:
    return f"tasks:staged_artifact:{task_id}:{artifact_id}"


def build_task_staged_artifact_storage_path(task: Task, artifact_id: str, name: str) -> str:
    safe_name = get_safe_artifact_name(name)
    return (
        f"{settings.OBJECT_STORAGE_TASKS_FOLDER}/artifacts/team_{task.team_id}/task_{task.id}"
        f"/staged/{artifact_id}/{safe_name}"
    )


def build_task_run_artifact_storage_path(task_run: TaskRun, artifact_id: str, name: str) -> str:
    safe_name = get_safe_artifact_name(name)
    return f"{task_run.get_artifact_s3_prefix()}/{artifact_id}_{safe_name}"


def build_task_artifact_entry(
    *,
    artifact_id: str,
    name: str,
    artifact_type: str,
    source: str,
    size: int | None,
    content_type: str,
    storage_path: str,
    uploaded_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "type": artifact_type,
        "source": source,
        "size": size,
        "content_type": content_type,
        "storage_path": storage_path,
        "uploaded_at": uploaded_at or timezone.now().isoformat(),
    }


def cache_task_staged_artifact(task: Task, artifact: dict[str, Any]) -> None:
    artifact_id = str(artifact["id"])
    cache.set(
        build_task_staged_artifact_cache_key(str(task.id), artifact_id),
        artifact,
        timeout=STAGED_TASK_ARTIFACT_CACHE_TTL_SECONDS,
    )


def get_task_staged_artifacts(task: Task, artifact_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    artifacts: list[dict[str, Any]] = []
    missing_ids: list[str] = []

    for artifact_id in artifact_ids:
        cache_key = build_task_staged_artifact_cache_key(str(task.id), artifact_id)
        artifact = cache.get(cache_key)
        if not isinstance(artifact, dict):
            missing_ids.append(artifact_id)
            continue
        artifacts.append(artifact)

    return artifacts, missing_ids


def consume_task_staged_artifacts(task: Task, artifact_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    artifacts, missing_ids = get_task_staged_artifacts(task, artifact_ids)
    if missing_ids:
        return [], missing_ids

    for artifact_id in artifact_ids:
        cache.delete(build_task_staged_artifact_cache_key(str(task.id), artifact_id))

    return artifacts, []


def get_task_run_artifacts_by_id(task_run: TaskRun, artifact_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    artifacts_by_id = {
        str(artifact.get("id")): artifact
        for artifact in (task_run.artifacts or [])
        if isinstance(artifact, dict) and artifact.get("id")
    }

    resolved_artifacts: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    for artifact_id in artifact_ids:
        artifact = artifacts_by_id.get(artifact_id)
        if artifact is None:
            missing_ids.append(artifact_id)
            continue
        resolved_artifacts.append(artifact)

    return resolved_artifacts, missing_ids


def tag_task_artifact(storage_path: str, *, ttl_days: str, team_id: int) -> None:
    try:
        object_storage.tag(
            storage_path,
            {
                "ttl_days": ttl_days,
                "team_id": str(team_id),
            },
        )
    except Exception as exc:
        logger.warning(
            "task_artifact.tag_failed",
            storage_path=storage_path,
            ttl_days=ttl_days,
            team_id=team_id,
            error=str(exc),
        )
