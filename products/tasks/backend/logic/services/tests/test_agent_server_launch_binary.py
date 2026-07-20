from django.test import override_settings

from products.tasks.backend.logic.services.sandbox import (
    NODE_AGENT_SERVER_BINARY,
    RUST_AGENT_SERVER_BINARY,
    RUST_CLAUDE_DRIVER_BINARY,
    RUST_CODEX_DRIVER_BINARY,
    agent_server_launch_binary,
    build_agent_runtime_env_prefix,
)


class TestAgentServerLaunchBinary:
    def test_defaults_to_node_implementation(self):
        assert agent_server_launch_binary() == NODE_AGENT_SERVER_BINARY

    @override_settings(SANDBOX_RUST_AGENT_SERVER=True)
    def test_setting_switches_to_rust_binary(self):
        assert agent_server_launch_binary() == RUST_AGENT_SERVER_BINARY

    def test_driver_adapter_envs_absent_by_default(self):
        prefix = build_agent_runtime_env_prefix(runtime_adapter="claude")
        assert "POSTHOG_CLAUDE_ADAPTER_CMD" not in prefix
        assert "POSTHOG_CODEX_ADAPTER_CMD" not in prefix

    @override_settings(SANDBOX_RUST_CLAUDE_DRIVER=True)
    def test_claude_driver_setting_exports_adapter_env(self):
        prefix = build_agent_runtime_env_prefix(runtime_adapter="claude")
        assert f"POSTHOG_CLAUDE_ADAPTER_CMD={RUST_CLAUDE_DRIVER_BINARY}" in prefix

    @override_settings(SANDBOX_RUST_CODEX_DRIVER=True)
    def test_codex_driver_setting_exports_adapter_env(self):
        prefix = build_agent_runtime_env_prefix(runtime_adapter="codex")
        assert f"POSTHOG_CODEX_ADAPTER_CMD={RUST_CODEX_DRIVER_BINARY}" in prefix
