from collections.abc import Callable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.tasks.backend.constants import TASK_SIGNALS_CLONING_BLOBLESS_FEATURE_FLAG
from products.tasks.backend.exceptions import SandboxNetworkPolicyError
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CheckoutBranchInSandboxInput,
    CheckoutBranchInSandboxOutput,
    PrepareSandboxForRepositoryOutput,
    _apply_modal_network_policy,
    _build_environment_variables,
    _build_sandbox_tags,
    _is_blobless_signals_clone_enabled,
    _to_modal_domain_allowlist,
    checkout_branch_in_sandbox,
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


@pytest.mark.parametrize(
    ("origin_product", "flag_result", "expected"),
    [
        (Task.OriginProduct.SIGNAL_REPORT, True, True),
        (Task.OriginProduct.SIGNAL_REPORT, False, False),
        (Task.OriginProduct.ERROR_TRACKING, True, False),
    ],
)
def test_blobless_clone_only_applies_to_enabled_signal_tasks(mocker, origin_product, flag_result, expected):
    feature_enabled = mocker.patch(f"{_PROVISION}.posthoganalytics.feature_enabled", return_value=flag_result)

    assert _is_blobless_signals_clone_enabled(_context(origin_product=origin_product)) is expected

    if origin_product == Task.OriginProduct.SIGNAL_REPORT:
        feature_enabled.assert_called_once_with(
            TASK_SIGNALS_CLONING_BLOBLESS_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "org-uuid"},
            group_properties={"organization": {"id": "org-uuid"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    else:
        feature_enabled.assert_not_called()


def test_blobless_clone_fails_closed_when_flag_evaluation_fails(mocker):
    mocker.patch(f"{_PROVISION}.posthoganalytics.feature_enabled", side_effect=RuntimeError("unavailable"))

    assert _is_blobless_signals_clone_enabled(_context(origin_product=Task.OriginProduct.SIGNAL_REPORT)) is False


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
            ["github.com", "registry.npmjs.org"],
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


# A charset-only check admits empty labels and per-label hyphens, putting a host
# in Modal's allowlist its matcher never fires on: the sandbox boots, then its
# gateway calls are silently denied.
@pytest.mark.parametrize(
    "hostname",
    [
        "ai-gateway.dev..posthog.dev",
        "ai-gateway.-dev.posthog.dev",
        "ai-gateway.dev-.posthog.dev",
        "-ai-gateway.dev.posthog.dev",
        # Valid DNS, but no layer matches a rooted name against an unrooted host.
        "ai-gateway.dev.posthog.dev.",
        # Wildcard syntax at both layers; never widen to a whole suffix.
        "*.posthog.dev",
    ],
)
def test_to_modal_domain_allowlist_rejects_malformed_settings_host(hostname):
    with override_settings(DEBUG=False, SANDBOX_AI_GATEWAY_URL=f"https://{hostname}"):
        assert hostname not in _to_modal_domain_allowlist([])


@override_settings(DEBUG=False, SANDBOX_AI_GATEWAY_URL="https://ai-gateway.dev.posthog.dev")
def test_to_modal_domain_allowlist_still_admits_hyphenated_host():
    # Guards against over-rejecting: hyphens inside a label are legal.
    assert "ai-gateway.dev.posthog.dev" in _to_modal_domain_allowlist([])


def test_restricted_vm_cannot_bypass_modal_network_flag() -> None:
    config = SandboxConfig(name="restricted-vm", vm_runtime=True)
    context = _context(
        allowed_domains=["example.com"],
        agentsh_domain_allowlist=["example.com", "api.posthog.com"],
        modal_domain_allowlist=["example.com", "api.posthog.com"],
        network_policy_fingerprint="policy-hash",
        use_modal_vm_sandbox=True,
        use_modal_network_allowlist=False,
    )

    with pytest.raises(SandboxNetworkPolicyError) as error:
        _apply_modal_network_policy(config, context, use_vm_sandbox=True)

    assert error.value.non_retryable is True
    assert config.outbound_domain_allowlist is None


def test_restricted_vm_applies_compiled_modal_policy() -> None:
    config = SandboxConfig(name="restricted-vm", vm_runtime=True)
    context = _context(
        allowed_domains=[],
        agentsh_domain_allowlist=["api.posthog.com"],
        modal_domain_allowlist=["api.posthog.com"],
        network_policy_fingerprint="policy-hash",
        use_modal_vm_sandbox=True,
        use_modal_network_allowlist=True,
    )

    _apply_modal_network_policy(config, context, use_vm_sandbox=True)

    assert config.outbound_domain_allowlist == ["api.posthog.com"]
    assert config.network_policy_fingerprint == "policy-hash"


@override_settings(DEBUG=False)
def test_restricted_vm_recompiles_modal_policy_for_legacy_context() -> None:
    config = SandboxConfig(name="restricted-vm", vm_runtime=True)
    context = _context(
        allowed_domains=["example.com"],
        use_modal_vm_sandbox=True,
        use_modal_network_allowlist=True,
    )

    _apply_modal_network_policy(config, context, use_vm_sandbox=True)

    assert config.outbound_domain_allowlist is not None
    assert "example.com" in config.outbound_domain_allowlist
    assert "*.posthog.com" in config.outbound_domain_allowlist
    assert "api.anthropic.com" in config.outbound_domain_allowlist
    assert config.network_policy_fingerprint is not None


@override_settings(DEBUG=False)
def test_restricted_vm_rejects_invalid_legacy_context() -> None:
    config = SandboxConfig(name="restricted-vm", vm_runtime=True)
    context = _context(
        allowed_domains=["https://example.com/path"],
        use_modal_vm_sandbox=True,
        use_modal_network_allowlist=True,
    )

    with pytest.raises(SandboxNetworkPolicyError) as error:
        _apply_modal_network_policy(config, context, use_vm_sandbox=True)

    assert error.value.non_retryable is True
    assert config.outbound_domain_allowlist is None


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
    "state, expected_resume_run_id, expected_idle",
    [
        ({}, None, None),
        ({"handoff_resumed": True}, "run-456", None),
        ({"handoff_resumed": True, "handoff_resume_idle": True}, "run-456", "1"),
        ({"resume_from_run_id": "run-000", "handoff_resume_idle": True}, "run-000", None),
    ],
)
def test_build_environment_variables_marks_only_an_idle_handoff_as_idle(
    _api, _jwt, _git, state, expected_resume_run_id, expected_idle
):
    env = _build_environment_variables(_context(state=state), MagicMock(), "", "access-token")

    assert env.get("POSTHOG_RESUME_RUN_ID") == expected_resume_run_id
    assert env.get("POSTHOG_RESUME_IDLE") == expected_idle


@patch(f"{_PROVISION}.emit_agent_log")
@patch(f"{_PROVISION}.get_sandbox_class_for_sandbox_id")
@pytest.mark.parametrize(
    "used_snapshot, expected_checkout",
    [
        (False, "git checkout -B new-task-branch HEAD"),
        (True, "git fetch --depth 1 origin -- HEAD && git checkout -B new-task-branch FETCH_HEAD"),
    ],
)
def test_checkout_branch_creates_missing_branch_from_current_default_branch(
    mock_get_sandbox_class, _mock_emit_agent_log, used_snapshot, expected_checkout
):
    sandbox = mock_get_sandbox_class.return_value.get_by_id.return_value

    def execute(command, **_kwargs):
        exit_code = 2 if "git ls-remote" in command else 0
        return ExecutionResult(stdout="", stderr="", exit_code=exit_code)

    sandbox.execute.side_effect = execute
    activity_body = cast(
        Callable[[CheckoutBranchInSandboxInput], CheckoutBranchInSandboxOutput],
        vars(checkout_branch_in_sandbox)["__wrapped__"],
    )

    activity_body(
        CheckoutBranchInSandboxInput(
            context=_context(),
            sandbox_id="sandbox-123",
            repository="posthog/posthog",
            branch="new-task-branch",
            github_token="token",
            shallow_clone=True,
            used_snapshot=used_snapshot,
        )
    )

    checkout_command = sandbox.execute.call_args_list[-1].args[0]
    assert expected_checkout in checkout_command


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


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
@pytest.mark.parametrize(
    "url, token, traces_url, expected_keys",
    [
        (
            "https://us.i.posthog.com/i/v1/logs",
            "phc_telemetry",
            "https://us.i.posthog.com/i/v1/traces",
            {"POSTHOG_AGENT_OTEL_LOGS_URL", "POSTHOG_AGENT_OTEL_LOGS_TOKEN", "POSTHOG_AGENT_OTEL_TRACES_URL"},
        ),
        (
            "https://us.i.posthog.com/i/v1/logs",
            "phc_telemetry",
            None,
            {"POSTHOG_AGENT_OTEL_LOGS_URL", "POSTHOG_AGENT_OTEL_LOGS_TOKEN"},
        ),
        ("https://us.i.posthog.com/i/v1/logs", None, None, set()),
        (None, "phc_telemetry", None, set()),
        # Traces alone are useless without the logs pair carrying the token.
        (None, None, "https://us.i.posthog.com/i/v1/traces", set()),
    ],
)
def test_build_environment_variables_injects_otel_env_only_when_fully_configured(
    _api, _jwt, _git, url, token, traces_url, expected_keys
):
    ctx = _context(agent_otel_telemetry_enabled=True)

    with override_settings(
        SANDBOX_AGENT_OTEL_LOGS_URL=url,
        SANDBOX_AGENT_OTEL_LOGS_TOKEN=token,
        SANDBOX_AGENT_OTEL_TRACES_URL=traces_url,
    ):
        env = _build_environment_variables(ctx, MagicMock(), "", "access-token")

    assert {key for key in env if key.startswith("POSTHOG_AGENT_OTEL_")} == expected_keys


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
def test_build_environment_variables_omits_otel_env_when_flag_disabled(_api, _jwt, _git):
    ctx = _context()

    with override_settings(
        SANDBOX_AGENT_OTEL_LOGS_URL="https://us.i.posthog.com/i/v1/logs",
        SANDBOX_AGENT_OTEL_LOGS_TOKEN="phc_telemetry",
        SANDBOX_AGENT_OTEL_TRACES_URL="https://us.i.posthog.com/i/v1/traces",
    ):
        env = _build_environment_variables(ctx, MagicMock(), "", "access-token")

    assert not any(key.startswith("POSTHOG_AGENT_OTEL_") for key in env)


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
def test_build_environment_variables_forwards_run_context_to_token_minting(_api, _jwt, _git):
    """The fresh-provisioning path must forward team, origin, stage, and internal
    into token minting; a dropped kwarg silently degrades every fresh run to the
    Python gateway."""
    ctx = _context(origin_product="signals_scout", state={"ai_stage": "scout:logs"})
    task = MagicMock()
    task.internal = True
    with patch(
        "products.tasks.backend.temporal.process_task.activities.provision_sandbox.run_gateway_env_vars",
        return_value={"AI_GATEWAY_TOKEN": "phe"},
    ) as env:
        out = _build_environment_variables(ctx, task, "", "access-token")
    env.assert_called_once_with(ctx, task)
    assert out["AI_GATEWAY_TOKEN"] == "phe"
