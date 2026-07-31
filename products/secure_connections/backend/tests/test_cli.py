from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import call, patch

from django.test import SimpleTestCase

from products.secure_connections.cli import (
    ENV_BLOCK_END,
    ENV_BLOCK_START,
    run_demo_command,
    run_managed_demo,
    update_demo_environment,
)


class TestSecureConnectionsDemoEnvironment(SimpleTestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def test_replaces_demo_block_without_changing_existing_secrets(self) -> None:
        env_file = Path(self.temporary_directory.name) / ".env.local"
        env_file.write_text(
            f"OTHER_SECRET=keep-me\n\n{ENV_BLOCK_START}\nSECURE_CONNECTION_ADMIN_TOKEN=old\n{ENV_BLOCK_END}\n"
        )

        update_demo_environment(env_file, enabled=True)

        contents = env_file.read_text()
        assert "OTHER_SECRET=keep-me" in contents
        assert "SECURE_CONNECTION_ADMIN_TOKEN=demo-admin-token" in contents
        assert contents.count(ENV_BLOCK_START) == 1

    def test_disable_removes_only_demo_block(self) -> None:
        env_file = Path(self.temporary_directory.name) / ".env.local"
        env_file.write_text(
            f"OTHER_SECRET=keep-me\n\n{ENV_BLOCK_START}\nSECURE_CONNECTION_ADMIN_TOKEN=demo-admin-token\n{ENV_BLOCK_END}\n"
        )

        update_demo_environment(env_file, enabled=False)

        assert env_file.read_text() == "OTHER_SECRET=keep-me\n"

    @patch("products.secure_connections.cli.signal.signal")
    @patch("products.secure_connections.cli.run_demo_command")
    def test_managed_demo_cleans_up_when_stopped(self, run_demo_command_mock, _signal_mock) -> None:
        env_file = Path(self.temporary_directory.name) / ".env.local"
        burrow_repo = Path(self.temporary_directory.name) / "burrow"
        run_demo_command_mock.side_effect = [None, KeyboardInterrupt, None]

        run_managed_demo(burrow_repo, env_file)

        assert run_demo_command_mock.call_args_list == [
            call(burrow_repo, "start"),
            call(burrow_repo, "logs"),
            call(burrow_repo, "stop"),
        ]
        assert not env_file.exists() or env_file.read_text() == ""

    @patch("products.secure_connections.cli.subprocess.run")
    @patch.dict("products.secure_connections.cli.os.environ", {}, clear=True)
    def test_demo_commands_use_posthog_compose_project(self, subprocess_run_mock) -> None:
        burrow_repo = Path(self.temporary_directory.name) / "burrow"

        run_demo_command(burrow_repo, "test")

        assert subprocess_run_mock.call_args.kwargs["env"]["COMPOSE_PROJECT_NAME"] == "posthog"
