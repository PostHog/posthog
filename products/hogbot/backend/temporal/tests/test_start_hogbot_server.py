from products.hogbot.backend.temporal.activities.start_hogbot_server import (
    HOGBOT_SERVER_BIN_PATH,
    _render_server_command,
)


class TestStartHogbotServerActivity:
    def test_default_server_command_targets_hogbot_server_binary(self) -> None:
        command = _render_server_command(
            team_id=17,
            port=47821,
            public_base_url="http://localhost:47821",
            connect_token="modal-token",
            server_command=None,
        )

        assert HOGBOT_SERVER_BIN_PATH in command
        assert "--teamId 17" in command
        assert "--port 47821" in command
        assert "--workspacePath /tmp/workspace" in command
        assert "--sandboxConnectToken modal-token" in command

    def test_custom_server_command_template_is_rendered(self) -> None:
        command = _render_server_command(
            team_id=11,
            port=8080,
            public_base_url="https://demo.modal.run",
            connect_token="connect-token",
            server_command="start --team {team_id} --port {port} --url {public_base_url}{sandbox_connect_token_arg}",
        )

        assert command == "start --team 11 --port 8080 --url https://demo.modal.run --sandboxConnectToken connect-token"
