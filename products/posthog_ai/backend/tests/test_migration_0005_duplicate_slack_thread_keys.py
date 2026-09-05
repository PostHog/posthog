import importlib

from posthog.test.base import BaseTest

from django.apps import apps
from django.db import connection

from posthog.models.team.team import Team

from products.posthog_ai.backend.models.assistant import Conversation

migration_module = importlib.import_module(
    "products.posthog_ai.backend.migrations.0005_check_duplicate_slack_thread_keys"
)
fail_on_duplicate_slack_thread_keys = migration_module.fail_on_duplicate_slack_thread_keys


class TestFailOnDuplicateSlackThreadKeys(BaseTest):
    def _create_conversation(self, slack_thread_key: str | None, team: Team | None = None) -> Conversation:
        return Conversation.objects.create(
            team=team or self.team,
            user=self.user,
            slack_thread_key=slack_thread_key,
        )

    def _drop_index(self) -> None:
        # The guard only has work to do where the index does not enforce uniqueness,
        # which is the state this migration repairs.
        with connection.cursor() as cursor:
            cursor.execute('DROP INDEX IF EXISTS "unique_team_slack_thread_key"')

    def test_passes_when_rows_have_no_key(self):
        self._create_conversation(None)
        self._create_conversation(None)

        fail_on_duplicate_slack_thread_keys(apps, None)

    def test_passes_when_two_teams_share_a_key(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._create_conversation("workspace:channel:1")
        self._create_conversation("workspace:channel:1", team=other_team)

        fail_on_duplicate_slack_thread_keys(apps, None)

    def test_fails_when_a_team_has_a_duplicate_key(self):
        self._drop_index()
        self._create_conversation("workspace:channel:1")
        self._create_conversation("workspace:channel:1")

        with self.assertRaises(RuntimeError) as error:
            fail_on_duplicate_slack_thread_keys(apps, None)

        self.assertIn(str(self.team.id), str(error.exception))
