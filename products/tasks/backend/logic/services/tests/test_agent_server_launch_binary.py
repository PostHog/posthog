from django.test import override_settings

from products.tasks.backend.logic.services.sandbox import (
    NODE_AGENT_SERVER_BINARY,
    RUST_AGENT_SERVER_BINARY,
    agent_server_launch_binary,
)


class TestAgentServerLaunchBinary:
    def test_defaults_to_node_implementation(self):
        assert agent_server_launch_binary() == NODE_AGENT_SERVER_BINARY

    @override_settings(SANDBOX_RUST_AGENT_SERVER=True)
    def test_setting_switches_to_rust_binary(self):
        assert agent_server_launch_binary() == RUST_AGENT_SERVER_BINARY
