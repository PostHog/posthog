from __future__ import annotations

import re
import json
import shlex
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import posthoganalytics

from products.tasks.backend.constants import SENDBLUE_TASK_REPOSITORY
from products.tasks.backend.models import Task, TaskPrewarmedSandbox
from products.tasks.backend.services.sandbox import (
    PREWARMED_SANDBOX_ENV_FILE,
    Sandbox,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
)

logger = logging.getLogger(__name__)

SEND_BLUE_POOL_FEATURE_FLAG = "tasks-sendblue-prewarmed-sandbox-pool"
SEND_BLUE_POOL_DISTINCT_ID = "internal_tasks_sendblue_prewarmed_sandbox_pool"
DEFAULT_POOL_TTL_SECONDS = 60 * 60
DEFAULT_MAX_CREATE_BATCH = 5
MAX_TARGET_AVAILABLE = 200
MAX_CREATE_BATCH = 25
ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SendbluePrewarmedPoolConfig:
    enabled: bool
    target_available: int
    repository: str
    ttl_seconds: int
    max_create_batch: int
    modal_docker_default_app_name: str | None
    team_id: int | None

    @property
    def pool_key(self) -> str:
        return f"{Task.OriginProduct.SENDBLUE}:{self.repository}:{SandboxTemplate.DEFAULT_BASE.value}"


@dataclass(frozen=True)
class LeasedPrewarmedSandbox:
    pool_entry_id: str
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None


def get_sendblue_prewarmed_pool_config(*, team_id: int | None = None) -> SendbluePrewarmedPoolConfig:
    enabled = bool(
        posthoganalytics.feature_enabled(
            SEND_BLUE_POOL_FEATURE_FLAG,
            SEND_BLUE_POOL_DISTINCT_ID,
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )

    payload = _get_feature_flag_payload()
    return SendbluePrewarmedPoolConfig(
        enabled=enabled,
        target_available=_bounded_int(
            payload.get("target_available"), default=0, minimum=0, maximum=MAX_TARGET_AVAILABLE
        ),
        repository=_repository_from_payload(payload),
        ttl_seconds=_bounded_int(
            payload.get("ttl_seconds"), default=DEFAULT_POOL_TTL_SECONDS, minimum=300, maximum=6 * 60 * 60
        ),
        max_create_batch=_bounded_int(
            payload.get("max_create_batch"),
            default=DEFAULT_MAX_CREATE_BATCH,
            minimum=1,
            maximum=MAX_CREATE_BATCH,
        ),
        modal_docker_default_app_name=_modal_docker_default_app_name_from_payload(payload),
        team_id=team_id if team_id is not None else _team_id_from_payload(payload),
    )


def try_lease_sendblue_prewarmed_sandbox(
    *,
    run_id: str,
    team_id: int,
    origin_product: str | None,
    repository: str | None,
    environment_variables: dict[str, str],
) -> LeasedPrewarmedSandbox | None:
    config = get_sendblue_prewarmed_pool_config(team_id=team_id)
    normalized_repository = (repository or "").lower()
    if (
        not config.enabled
        or config.target_available <= 0
        or config.team_id is None
        or origin_product != Task.OriginProduct.SENDBLUE
        or normalized_repository != config.repository
    ):
        return None

    entry = _lease_available_entry(config=config, run_id=run_id)
    if entry is None:
        return None

    try:
        sandbox = Sandbox.get_by_id(entry.sandbox_id or "")
        if sandbox.get_status() != SandboxStatus.RUNNING:
            raise RuntimeError(f"Prewarmed sandbox {entry.sandbox_id} is not running")

        env_result = sandbox.write_file(PREWARMED_SANDBOX_ENV_FILE, _environment_payload(environment_variables))
        if env_result.exit_code != 0:
            raise RuntimeError("Failed to inject task environment into prewarmed sandbox")

        credentials = sandbox.get_connect_credentials()
        logger.info(
            "Leased prewarmed Sendblue sandbox",
            extra={
                "pool_entry_id": str(entry.id),
                "sandbox_id": sandbox.id,
                "run_id": run_id,
                "repository": config.repository,
            },
        )
        return LeasedPrewarmedSandbox(
            pool_entry_id=str(entry.id),
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
        )
    except Exception as err:
        _mark_entry_failed(entry, str(err))
        logger.warning(
            "Failed to lease prewarmed Sendblue sandbox; falling back to cold sandbox",
            extra={
                "pool_entry_id": str(entry.id),
                "sandbox_id": entry.sandbox_id,
                "run_id": run_id,
                "error": str(err),
            },
        )
        return None


def reconcile_sendblue_prewarmed_sandbox_pool(*, team_id: int | None = None) -> dict[str, int | bool | str]:
    config = get_sendblue_prewarmed_pool_config(team_id=team_id)
    if config.team_id is None:
        return {
            "enabled": config.enabled,
            "created": 0,
            "cleaned": 0,
            "terminated": 0,
            "target_available": config.target_available,
            "repository": config.repository,
            "missing_team_id": True,
        }

    cleaned = cleanup_expired_sendblue_prewarmed_sandboxes(config=config)
    if not config.enabled or config.target_available <= 0:
        terminated = terminate_available_sendblue_prewarmed_sandboxes(config=config)
        return {
            "enabled": False,
            "created": 0,
            "cleaned": cleaned,
            "terminated": terminated,
            "target_available": config.target_available,
            "repository": config.repository,
        }

    created = 0
    for _ in range(config.max_create_batch):
        if _available_or_provisioning_count(config=config) >= config.target_available:
            break
        entry = _reserve_provisioning_entry(config=config)
        if entry is None:
            break
        if not _provision_entry(entry=entry, config=config):
            break
        created += 1

    return {
        "enabled": True,
        "created": created,
        "cleaned": cleaned,
        "terminated": 0,
        "target_available": config.target_available,
        "repository": config.repository,
    }


def cleanup_expired_sendblue_prewarmed_sandboxes(*, config: SendbluePrewarmedPoolConfig | None = None) -> int:
    config = config or get_sendblue_prewarmed_pool_config()
    team_id = config.team_id
    if team_id is None:
        return 0
    now = timezone.now()
    expired = list(
        TaskPrewarmedSandbox.objects.filter(
            team_id=team_id,
            pool_key=config.pool_key,
            status__in=[TaskPrewarmedSandbox.Status.AVAILABLE, TaskPrewarmedSandbox.Status.PROVISIONING],
            expires_at__lte=now,
        )[:100]
    )
    for entry in expired:
        _terminate_entry(entry, status=TaskPrewarmedSandbox.Status.TERMINATED, reason="expired")
    return len(expired)


def terminate_available_sendblue_prewarmed_sandboxes(*, config: SendbluePrewarmedPoolConfig | None = None) -> int:
    config = config or get_sendblue_prewarmed_pool_config()
    team_id = config.team_id
    if team_id is None:
        return 0
    entries = list(
        TaskPrewarmedSandbox.objects.filter(
            team_id=team_id,
            pool_key=config.pool_key,
            status__in=[TaskPrewarmedSandbox.Status.AVAILABLE, TaskPrewarmedSandbox.Status.PROVISIONING],
        )[:100]
    )
    for entry in entries:
        _terminate_entry(entry, status=TaskPrewarmedSandbox.Status.TERMINATED, reason="feature flag disabled")
    return len(entries)


def _get_feature_flag_payload() -> dict[str, Any]:
    raw_payload = posthoganalytics.get_feature_flag_payload(
        SEND_BLUE_POOL_FEATURE_FLAG,
        SEND_BLUE_POOL_DISTINCT_ID,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if isinstance(raw_payload, str):
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw_payload if isinstance(raw_payload, dict) else {}


def _repository_from_payload(payload: dict[str, Any]) -> str:
    value = payload.get("repository")
    if isinstance(value, str) and "/" in value:
        return value.lower()
    return SENDBLUE_TASK_REPOSITORY


def _modal_docker_default_app_name_from_payload(payload: dict[str, Any]) -> str | None:
    value = payload.get("modal_docker_default_app_name")
    if isinstance(value, str) and value:
        return value
    return None


def _team_id_from_payload(payload: dict[str, Any]) -> int | None:
    value = payload.get("team_id") or payload.get("project_id")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _modal_app_name_for_provider(config: SendbluePrewarmedPoolConfig) -> str | None:
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    if provider and provider.upper() == "MODAL_DOCKER":
        return config.modal_docker_default_app_name
    return None


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        return default
    return max(minimum, min(value, maximum))


def _available_or_provisioning_count(*, config: SendbluePrewarmedPoolConfig) -> int:
    team_id = _require_team_id(config)
    now = timezone.now()
    return TaskPrewarmedSandbox.objects.filter(
        team_id=team_id,
        pool_key=config.pool_key,
        status__in=[TaskPrewarmedSandbox.Status.AVAILABLE, TaskPrewarmedSandbox.Status.PROVISIONING],
        expires_at__gt=now,
    ).count()


def _reserve_provisioning_entry(*, config: SendbluePrewarmedPoolConfig) -> TaskPrewarmedSandbox | None:
    team_id = _require_team_id(config)
    with transaction.atomic():
        if _available_or_provisioning_count(config=config) >= config.target_available:
            return None

        return TaskPrewarmedSandbox.objects.create(
            team_id=team_id,
            pool_key=config.pool_key,
            origin_product=Task.OriginProduct.SENDBLUE,
            repository=config.repository,
            provider=getattr(settings, "SANDBOX_PROVIDER", None) or "modal",
            template=SandboxTemplate.DEFAULT_BASE.value,
            status=TaskPrewarmedSandbox.Status.PROVISIONING,
            expires_at=timezone.now() + timedelta(seconds=config.ttl_seconds),
            metadata={"source": "sendblue-prewarm-pool"},
        )


def _provision_entry(*, entry: TaskPrewarmedSandbox, config: SendbluePrewarmedPoolConfig) -> bool:
    sandbox = None
    try:
        sandbox = Sandbox.create(
            SandboxConfig(
                name=f"sendblue-prewarm-{entry.id}",
                template=SandboxTemplate.DEFAULT_BASE,
                ttl_seconds=config.ttl_seconds,
                modal_app_name=_modal_app_name_for_provider(config),
                metadata={
                    "pool_key": config.pool_key,
                    "pool_entry_id": str(entry.id),
                    "team_id": str(config.team_id),
                    "origin_product": Task.OriginProduct.SENDBLUE,
                    "repository": config.repository,
                },
            )
        )
        clone_result = sandbox.clone_repository(config.repository, github_token="", shallow=True)
        if clone_result.exit_code != 0:
            raise RuntimeError(f"Failed to clone {config.repository}: {clone_result.stderr}")

        entry.sandbox_id = sandbox.id
        entry.status = TaskPrewarmedSandbox.Status.AVAILABLE
        entry.warmed_at = timezone.now()
        entry.last_error = None
        entry.save(update_fields=["sandbox_id", "status", "warmed_at", "last_error", "updated_at"])
        return True
    except Exception as err:
        if sandbox is not None:
            try:
                sandbox.destroy()
            except Exception:
                logger.exception("Failed to destroy failed prewarmed sandbox", extra={"sandbox_id": sandbox.id})
        _mark_entry_failed(entry, str(err))
        return False


def _lease_available_entry(
    *,
    config: SendbluePrewarmedPoolConfig,
    run_id: str,
) -> TaskPrewarmedSandbox | None:
    team_id = _require_team_id(config)
    now = timezone.now()
    with transaction.atomic():
        entry = (
            TaskPrewarmedSandbox.objects.select_for_update(skip_locked=True)
            .filter(
                team_id=team_id,
                pool_key=config.pool_key,
                status=TaskPrewarmedSandbox.Status.AVAILABLE,
                expires_at__gt=now,
            )
            .order_by("warmed_at", "created_at")
            .first()
        )
        if entry is None:
            return None

        entry.status = TaskPrewarmedSandbox.Status.LEASED
        entry.leased_task_run_id = run_id
        entry.leased_at = now
        entry.save(update_fields=["status", "leased_task_run", "leased_at", "updated_at"])
        return entry


def _require_team_id(config: SendbluePrewarmedPoolConfig) -> int:
    if config.team_id is None:
        raise ValueError("Sendblue prewarmed sandbox pool requires a team_id")
    return config.team_id


def _mark_entry_failed(entry: TaskPrewarmedSandbox, error: str) -> None:
    entry.status = TaskPrewarmedSandbox.Status.FAILED
    entry.last_error = error[:1000]
    entry.save(update_fields=["status", "last_error", "updated_at"])


def _terminate_entry(entry: TaskPrewarmedSandbox, *, status: str, reason: str) -> None:
    if entry.sandbox_id:
        try:
            sandbox = Sandbox.get_by_id(entry.sandbox_id)
            sandbox.destroy()
        except Exception:
            logger.exception(
                "Failed to terminate prewarmed sandbox",
                extra={"pool_entry_id": str(entry.id), "sandbox_id": entry.sandbox_id},
            )
    entry.status = status
    entry.last_error = reason
    entry.save(update_fields=["status", "last_error", "updated_at"])


def _environment_payload(environment_variables: dict[str, str]) -> bytes:
    lines = ["#!/bin/bash"]
    skipped_keys = []
    for key, value in environment_variables.items():
        if not ENV_VAR_NAME_RE.match(key):
            skipped_keys.append(key)
            continue
        lines.append(f"export {key}={shlex.quote(str(value))}")

    if skipped_keys:
        logger.warning(
            "Skipping invalid prewarmed sandbox environment variable keys",
            extra={"keys": sorted(skipped_keys)},
        )

    return ("\n".join(lines) + "\n").encode()
