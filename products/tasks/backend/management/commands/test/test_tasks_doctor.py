import json
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import override_settings

from parameterized import parameterized

from posthog.models import OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.feature_flags.backend.models.feature_flag import FeatureFlag

WIZARD_CLIENT_ID = "test-wizard-client-id"


@override_settings(CLOUD_DEPLOYMENT=None, WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID=WIZARD_CLIENT_ID)
class TestTasksDoctor(BaseTest):
    def _create_oauth_app(self, client_id: str) -> None:
        OAuthApplication.objects.create(
            client_id=client_id,
            name=client_id,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost/callback",
            algorithm="RS256",
        )

    def _run(self) -> dict[str, str]:
        out = StringIO()
        call_command("tasks_doctor", stdout=out)
        return {row["id"]: row["status"] for row in json.loads(out.getvalue())}

    @parameterized.expand(
        [
            ("nothing_set_up", False, False, False, {"array": "error", "wizard": "warn", "flag": "warn"}),
            ("everything_set_up", True, True, True, {"array": "ok", "wizard": "ok", "flag": "ok"}),
            ("only_sandbox_app", True, False, False, {"array": "ok", "wizard": "warn", "flag": "warn"}),
        ]
    )
    def test_reports_database_state(
        self,
        _name: str,
        with_array_app: bool,
        with_wizard_app: bool,
        with_tasks_flag: bool,
        expected: dict[str, str],
    ) -> None:
        if with_array_app:
            self._create_oauth_app(ARRAY_APP_CLIENT_ID_DEV)
        if with_wizard_app:
            self._create_oauth_app(WIZARD_CLIENT_ID)
        if with_tasks_flag:
            FeatureFlag.objects.create(team=self.team, key="tasks", created_by=self.user, active=True)

        statuses = self._run()

        assert {
            "array": statuses["db.array_oauth_app"],
            "wizard": statuses["db.wizard_oauth_app"],
            "flag": statuses["db.tasks_flag"],
        } == expected
