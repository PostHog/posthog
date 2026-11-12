from typing import Any

from posthog.test.base import TestMigrations

from posthog.models import Team

from products.logs.backend.models import DEFAULT_LOGS_PATTERN_MESSAGE_KEYS


class TestPatternMessageKeyPaths(TestMigrations):
    app = "logs"
    migrate_from = "0029_pattern_message_key_paths"
    migrate_to = "0030_move_pattern_message_keys_to_new_default"

    def setUpBeforeMigration(self, apps: Any) -> None:
        TeamLogsConfig = apps.get_model("logs", "TeamLogsConfig")
        self.saved = {
            "old_default": ["message", "msg", "event"],
            "custom": ["msg", "text"],
            "extraction_off": [],
        }
        self.team_ids = {}
        for name, keys in self.saved.items():
            team = Team.objects.create(organization=self.organization, name=name)
            TeamLogsConfig.objects.create(team_id=team.id, logs_pattern_message_keys=keys)
            self.team_ids[name] = team.id

    def test_only_rows_on_the_old_default_move_to_the_new_default(self) -> None:
        TeamLogsConfig = self.apps.get_model("logs", "TeamLogsConfig")  # type: ignore[union-attr]
        stored = {
            name: TeamLogsConfig.objects.get(team_id=team_id).logs_pattern_message_keys
            for name, team_id in self.team_ids.items()
        }

        assert stored == {
            "old_default": DEFAULT_LOGS_PATTERN_MESSAGE_KEYS,
            "custom": ["msg", "text"],
            "extraction_off": [],
        }
