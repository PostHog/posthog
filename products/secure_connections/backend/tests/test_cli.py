from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from products.secure_connections.cli import ENV_BLOCK_END, ENV_BLOCK_START, update_demo_environment


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
