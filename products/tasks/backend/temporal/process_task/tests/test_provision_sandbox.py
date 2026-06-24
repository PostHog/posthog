from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    PrepareSandboxForRepositoryOutput,
    _build_environment_variables,
    _build_sandbox_tags,
    _to_modal_domain_allowlist,
)

_PROVISION = "products.tasks.backend.temporal.process_task.activities.provision_sandbox"


def _context(**overrides) -> TaskProcessingContext:
    defaults: dict[str, Any] = {
        "task_id": "task-123",
        "run_id": "run-456",
        "team_id": 42,
        "team_uuid": "team-uuid",
        "organization_id": "org-uuid",
        "github_integration_id": None,
        "repository": "posthog/posthog",
        "distinct_id": "distinct-id",
        "origin_product": "error_tracking",
        "state": {},
    }
    defaults.update(overrides)
    return TaskProcessingContext(**defaults)


def _prepared(**overrides) -> PrepareSandboxForRepositoryOutput:
    defaults: dict[str, Any] = {
        "sandbox_name": "sandbox-name",
        "repository": "posthog/posthog",
        "github_token": "token",
        "branch": "feature-branch",
        "environment_variables": {},
        "snapshot_id": None,
        "snapshot_external_id": None,
        "used_snapshot": False,
        "should_create_snapshot": True,
        "shallow_clone": True,
        "image_source": "base_image",
        "image_source_label": "base image",
    }
    defaults.update(overrides)
    return PrepareSandboxForRepositoryOutput(**defaults)


def test_build_sandbox_tags_includes_all_identifiers():
    tags = _build_sandbox_tags(_context(), _prepared(), use_vm_sandbox=False)

    assert tags == {
        "task_id": "task-123",
        "task_run_id": "run-456",
        "origin_product": "error_tracking",
        "team_id": "42",
        "workflow_id": "task-processing-task-123-run-456",
        "image_source": "base_image",
        "sandbox_runtime": "gvisor",
    }


@pytest.mark.parametrize("use_vm_sandbox, expected", [(True, "vm"), (False, "gvisor")])
def test_build_sandbox_tags_marks_runtime(use_vm_sandbox, expected):
    tags = _build_sandbox_tags(_context(), _prepared(), use_vm_sandbox=use_vm_sandbox)

    assert tags["sandbox_runtime"] == expected


@pytest.mark.parametrize("image_source", ["base_image", "resume_snapshot", "repository_snapshot"])
def test_build_sandbox_tags_reflects_image_source(image_source):
    tags = _build_sandbox_tags(_context(), _prepared(image_source=image_source), use_vm_sandbox=False)

    assert tags["image_source"] == image_source


def test_build_sandbox_tags_drops_none_values():
    tags = _build_sandbox_tags(_context(origin_product=None), _prepared(), use_vm_sandbox=False)

    assert "origin_product" not in tags
    assert all(isinstance(value, str) for value in tags.values())


@override_settings(DEBUG=False)
@pytest.mark.parametrize(
    "allowed_domains, expected",
    [
        (
            ["github.com", "api.github.com", "posthog.com", "us.posthog.com", "example.com"],
            ["github.com", "api.github.com", "example.com", "*.posthog.com", "api.anthropic.com"],
        ),
        (
            [],
            ["*.posthog.com", "api.anthropic.com"],
        ),
        (
            ["github.com", "localhost", "host.docker.internal", "registry.npmjs.org"],
            ["github.com", "registry.npmjs.org", "*.posthog.com", "api.anthropic.com"],
        ),
        (
            ["*.posthog.com", "*.us.posthog.com", "gateway.us.posthog.com", "github.com"],
            ["*.posthog.com", "github.com", "api.anthropic.com"],
        ),
        (
            ["github.com", "github.com", "api.anthropic.com"],
            ["github.com", "api.anthropic.com", "*.posthog.com"],
        ),
    ],
)
def test_to_modal_domain_allowlist_resolves_exact_list(allowed_domains, expected):
    assert _to_modal_domain_allowlist(allowed_domains) == expected


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
@pytest.mark.parametrize(
    "allowed_domains, telemetry_disabled",
    [
        (["github.com"], True),
        ([], True),
        (None, False),
    ],
)
def test_build_environment_variables_disables_telemetry_when_restricted(
    _api, _jwt, _git, allowed_domains, telemetry_disabled
):
    ctx = _context(allowed_domains=allowed_domains)

    env = _build_environment_variables(ctx, MagicMock(), "", "access-token")

    keys = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"}
    if telemetry_disabled:
        assert all(env.get(k) == "1" for k in keys)
    else:
        assert not (keys & env.keys())
