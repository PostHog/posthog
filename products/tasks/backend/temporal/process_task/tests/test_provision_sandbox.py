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


# A prefixed-dispatch id (not the derived task-processing-<task>-<run> shape): the tags read the
# RUNNING workflow's id via activity.info(), which only exists inside an activity context — and
# labeling prefixed dispatches correctly is the reason the derived id was dropped.
_WORKFLOW_ID = "review-pr:42:posthog/posthog:7-sandbox"


def _build_tags(*args, **kwargs):
    with patch(f"{_PROVISION}.activity") as mock_activity:
        mock_activity.info.return_value = MagicMock(workflow_id=_WORKFLOW_ID)
        return _build_sandbox_tags(*args, **kwargs)


def test_build_sandbox_tags_includes_all_identifiers():
    tags = _build_tags(_context(), _prepared(), use_vm_sandbox=False)

    assert tags == {
        "task_id": "task-123",
        "task_run_id": "run-456",
        "origin_product": "error_tracking",
        "team_id": "42",
        "workflow_id": _WORKFLOW_ID,
        "image_source": "base_image",
        "sandbox_runtime": "gvisor",
    }


@pytest.mark.parametrize("use_vm_sandbox, expected", [(True, "vm"), (False, "gvisor")])
def test_build_sandbox_tags_marks_runtime(use_vm_sandbox, expected):
    tags = _build_tags(_context(), _prepared(), use_vm_sandbox=use_vm_sandbox)

    assert tags["sandbox_runtime"] == expected


@pytest.mark.parametrize("image_source", ["base_image", "resume_snapshot", "repository_snapshot"])
def test_build_sandbox_tags_reflects_image_source(image_source):
    tags = _build_tags(_context(), _prepared(image_source=image_source), use_vm_sandbox=False)

    assert tags["image_source"] == image_source


def test_build_sandbox_tags_drops_none_values():
    tags = _build_tags(_context(origin_product=None), _prepared(), use_vm_sandbox=False)

    assert "origin_product" not in tags
    assert all(isinstance(value, str) for value in tags.values())


# All four SANDBOX_*_URL settings are pinned: they feed the enforced allowlist
# outside DEBUG, so a developer's environment value (an ngrok SANDBOX_API_URL)
# would otherwise leak into these exact-equality expectations.
@override_settings(
    DEBUG=False,
    SANDBOX_API_URL=None,
    SANDBOX_LLM_GATEWAY_URL=None,
    SANDBOX_AI_GATEWAY_URL=None,
    SANDBOX_MCP_URL=None,
)
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


@override_settings(DEBUG=False, SANDBOX_AI_GATEWAY_URL="https://ai-gateway.dev.posthog.dev")
def test_to_modal_domain_allowlist_admits_configured_gateway_host():
    # Modal fences egress independently of agentsh, so the settings-derived
    # gateway host must clear this layer too; dev's host is outside
    # *.posthog.com and nothing else admits it.
    assert "ai-gateway.dev.posthog.dev" in _to_modal_domain_allowlist([])


@override_settings(DEBUG=False, SANDBOX_LLM_GATEWAY_URL="http://127.0.0.1:3308")
def test_to_modal_domain_allowlist_drops_loopback_ip_settings_host():
    # 127.0.0.1 contains dots, so the fqdn filter alone would pass it into
    # Modal's outbound_domain_allowlist, which rejects non-domain entries;
    # the loopback exclusion in sandbox_url_setting_domains is the only
    # defense on this path.
    assert "127.0.0.1" not in _to_modal_domain_allowlist([])


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
@override_settings(
    SANDBOX_AI_GATEWAY_URL="https://ai-gateway.us.posthog.com",
    SANDBOX_AI_GATEWAY_PRODUCTS="signals_scout",
)
def test_build_environment_variables_injects_ai_gateway_pair(_api, _jwt, _git):
    # Pins this site's wiring of the shared helper: the conjunction itself is
    # tested in test_utils.py, but deleting the update() call here would merge
    # green without this assertion and Modal-provisioned sandboxes would
    # silently stay on the legacy gateway.
    env = _build_environment_variables(_context(), MagicMock(), "", "access-token")

    assert env["AI_GATEWAY_URL"] == "https://ai-gateway.us.posthog.com"
    assert env["AI_GATEWAY_PRODUCTS"] == "signals_scout"


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
