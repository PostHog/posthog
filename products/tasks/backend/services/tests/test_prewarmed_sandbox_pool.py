from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.models import Organization, Team

from products.tasks.backend.constants import SENDBLUE_TASK_REPOSITORY
from products.tasks.backend.models import Task, TaskPrewarmedSandbox, TaskRun
from products.tasks.backend.services.prewarmed_sandbox_pool import (
    SEND_BLUE_POOL_DISTINCT_ID,
    SEND_BLUE_POOL_FEATURE_FLAG,
    SendbluePrewarmedPoolConfig,
    get_sendblue_prewarmed_pool_config,
    reconcile_sendblue_prewarmed_sandbox_pool,
    try_lease_sendblue_prewarmed_sandbox,
)
from products.tasks.backend.services.sandbox import (
    PREWARMED_SANDBOX_ENV_FILE,
    AgentServerResult,
    ExecutionResult,
    SandboxConfig,
    SandboxStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_prewarmed_sandboxes() -> None:
    TaskPrewarmedSandbox.objects.all().delete()


class FakeSandbox:
    def __init__(self, sandbox_id: str = "sb-test", status: SandboxStatus = SandboxStatus.RUNNING):
        self.id = sandbox_id
        self.status = status
        self.clone_calls: list[tuple[str, str | None, bool]] = []
        self.write_calls: list[tuple[str, bytes]] = []
        self.destroyed = False

    def get_status(self) -> SandboxStatus:
        return self.status

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        self.write_calls.append((path, payload))
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    def get_connect_credentials(self) -> AgentServerResult:
        return AgentServerResult(url=f"https://{self.id}.modal.host", token=f"{self.id}-token")

    def clone_repository(self, repository: str, github_token: str | None = "", shallow: bool = True) -> ExecutionResult:
        self.clone_calls.append((repository, github_token, shallow))
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    def destroy(self) -> None:
        self.destroyed = True


def _team() -> Team:
    organization = Organization.objects.create(name="Sendblue Pool Test Org")
    return Team.objects.create(organization=organization, name="Sendblue Pool Test Team")


def _task_run() -> TaskRun:
    team = _team()
    task = Task.objects.create(
        team=team,
        title="Sendblue task",
        description="Created from Sendblue",
        origin_product=Task.OriginProduct.SENDBLUE,
        repository=SENDBLUE_TASK_REPOSITORY,
    )
    return TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.QUEUED)


def _config(**overrides: Any) -> SendbluePrewarmedPoolConfig:
    return SendbluePrewarmedPoolConfig(
        enabled=overrides.get("enabled", True),
        target_available=overrides.get("target_available", 2),
        repository=overrides.get("repository", SENDBLUE_TASK_REPOSITORY),
        ttl_seconds=overrides.get("ttl_seconds", 3600),
        max_create_batch=overrides.get("max_create_batch", 5),
        modal_docker_default_app_name=overrides.get("modal_docker_default_app_name"),
        team_id=overrides.get("team_id", _team().id),
    )


def _available_entry(config: SendbluePrewarmedPoolConfig, sandbox_id: str = "sb-available") -> TaskPrewarmedSandbox:
    team_id = config.team_id
    assert team_id is not None
    return TaskPrewarmedSandbox.objects.create(
        team_id=team_id,
        pool_key=config.pool_key,
        origin_product=Task.OriginProduct.SENDBLUE,
        repository=config.repository,
        provider="modal",
        template="default_base",
        sandbox_id=sandbox_id,
        status=TaskPrewarmedSandbox.Status.AVAILABLE,
        warmed_at=timezone.now(),
        expires_at=timezone.now() + timedelta(seconds=config.ttl_seconds),
    )


def test_sendblue_prewarmed_pool_config_reads_feature_flag_payload() -> None:
    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.posthoganalytics.feature_enabled",
            return_value=True,
        ) as feature_enabled,
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.posthoganalytics.get_feature_flag_payload",
            return_value={
                "team_id": 7,
                "target_available": 3,
                "repository": "PostHog/PostHog",
                "ttl_seconds": 1800,
                "max_create_batch": 2,
                "modal_docker_default_app_name": "posthog-sandbox-modal-docker-default-alessandro",
            },
        ),
    ):
        config = get_sendblue_prewarmed_pool_config()

    assert config.enabled is True
    assert config.target_available == 3
    assert config.repository == "posthog/posthog"
    assert config.ttl_seconds == 1800
    assert config.max_create_batch == 2
    assert config.modal_docker_default_app_name == "posthog-sandbox-modal-docker-default-alessandro"
    assert config.team_id == 7
    feature_enabled.assert_called_once_with(
        SEND_BLUE_POOL_FEATURE_FLAG,
        SEND_BLUE_POOL_DISTINCT_ID,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def test_reconcile_creates_available_sandboxes_until_target() -> None:
    sandboxes = [FakeSandbox("sb-1"), FakeSandbox("sb-2")]

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.create", side_effect=sandboxes) as create,
    ):
        get_config.return_value = _config(target_available=2, max_create_batch=5)

        result = reconcile_sendblue_prewarmed_sandbox_pool()

    assert result["enabled"] is True
    assert result["created"] == 2
    assert TaskPrewarmedSandbox.objects.filter(status=TaskPrewarmedSandbox.Status.AVAILABLE).count() == 2
    assert [sandbox.clone_calls for sandbox in sandboxes] == [
        [(SENDBLUE_TASK_REPOSITORY, "", True)],
        [(SENDBLUE_TASK_REPOSITORY, "", True)],
    ]
    created_configs = [call.args[0] for call in create.call_args_list]
    assert all(isinstance(config, SandboxConfig) for config in created_configs)
    assert all(config.metadata["origin_product"] == Task.OriginProduct.SENDBLUE for config in created_configs)


@override_settings(SANDBOX_PROVIDER="MODAL_DOCKER")
def test_reconcile_uses_modal_docker_app_name_from_pool_config() -> None:
    sandbox = FakeSandbox("sb-1")

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.create", return_value=sandbox) as create,
    ):
        get_config.return_value = _config(
            target_available=1,
            modal_docker_default_app_name="posthog-sandbox-modal-docker-default-alessandro",
        )

        result = reconcile_sendblue_prewarmed_sandbox_pool()

    assert result["created"] == 1
    created_config = create.call_args.args[0]
    assert isinstance(created_config, SandboxConfig)
    assert created_config.modal_app_name == "posthog-sandbox-modal-docker-default-alessandro"


def test_reconcile_disables_pool_by_terminating_available_sandboxes() -> None:
    config = _config(enabled=False, target_available=0)
    entry = _available_entry(config)
    sandbox = FakeSandbox(entry.sandbox_id or "sb-disabled")

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.get_by_id", return_value=sandbox),
    ):
        get_config.return_value = config

        result = reconcile_sendblue_prewarmed_sandbox_pool()

    entry.refresh_from_db()
    assert result["enabled"] is False
    assert result["terminated"] == 1
    assert entry.status == TaskPrewarmedSandbox.Status.TERMINATED
    assert entry.last_error == "feature flag disabled"
    assert sandbox.destroyed is True


def test_try_lease_sendblue_prewarmed_sandbox_marks_entry_leased_and_injects_environment() -> None:
    task_run = _task_run()
    config = _config(team_id=task_run.team_id)
    entry = _available_entry(config, sandbox_id="sb-lease")
    sandbox = FakeSandbox("sb-lease")

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.get_by_id", return_value=sandbox),
    ):
        get_config.return_value = config

        leased = try_lease_sendblue_prewarmed_sandbox(
            run_id=str(task_run.id),
            team_id=task_run.team_id,
            origin_product=Task.OriginProduct.SENDBLUE,
            repository="PostHog/PostHog",
            environment_variables={"ALPHA": "one", "BETA": "two"},
        )

    entry.refresh_from_db()
    assert leased is not None
    assert leased.pool_entry_id == str(entry.id)
    assert leased.sandbox_id == "sb-lease"
    assert leased.sandbox_url == "https://sb-lease.modal.host"
    assert leased.connect_token == "sb-lease-token"
    assert entry.status == TaskPrewarmedSandbox.Status.LEASED
    assert entry.leased_task_run_id == task_run.id
    assert entry.leased_at is not None
    assert sandbox.write_calls == [(PREWARMED_SANDBOX_ENV_FILE, b"#!/bin/bash\nexport ALPHA=one\nexport BETA=two\n")]


def test_try_lease_sendblue_prewarmed_sandbox_ignores_non_sendblue_tasks() -> None:
    config = _config()
    entry = _available_entry(config, sandbox_id="sb-unused")

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.get_by_id") as get_by_id,
    ):
        get_config.return_value = config

        leased = try_lease_sendblue_prewarmed_sandbox(
            run_id=str(_task_run().id),
            team_id=entry.team_id,
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=SENDBLUE_TASK_REPOSITORY,
            environment_variables={},
        )

    entry.refresh_from_db()
    assert leased is None
    assert entry.status == TaskPrewarmedSandbox.Status.AVAILABLE
    get_by_id.assert_not_called()


def test_try_lease_sendblue_prewarmed_sandbox_marks_bad_entry_failed_and_falls_back() -> None:
    task_run = _task_run()
    config = _config(team_id=task_run.team_id)
    entry = _available_entry(config, sandbox_id="sb-stopped")
    sandbox = FakeSandbox("sb-stopped", status=SandboxStatus.SHUTDOWN)

    with (
        patch(
            "products.tasks.backend.services.prewarmed_sandbox_pool.get_sendblue_prewarmed_pool_config"
        ) as get_config,
        patch("products.tasks.backend.services.prewarmed_sandbox_pool.Sandbox.get_by_id", return_value=sandbox),
    ):
        get_config.return_value = config

        leased = try_lease_sendblue_prewarmed_sandbox(
            run_id=str(task_run.id),
            team_id=task_run.team_id,
            origin_product=Task.OriginProduct.SENDBLUE,
            repository=SENDBLUE_TASK_REPOSITORY,
            environment_variables={},
        )

    entry.refresh_from_db()
    assert leased is None
    assert entry.status == TaskPrewarmedSandbox.Status.FAILED
    assert "not running" in (entry.last_error or "")
