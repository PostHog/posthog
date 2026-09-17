from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import OAuthApplication, Team
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.oauth import OAuthAccessToken

from products.signals.backend.facade.activity_client import resolve_scout_client_tag
from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.models import Task, TaskRun

SELF_REPORTED_CLIENT = "mcp"
SKILL_NAME = "signals-scout-self-driving-dwh"


class TestScoutActivityClient(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.factory = RequestFactory()
        self.application = OAuthApplication.objects.create(
            client_id="scout-sandbox-client",
            redirect_uris="http://localhost/cb",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            organization=self.organization,
        )
        activity_storage.mark_request_scoped()
        activity_storage.set_client(SELF_REPORTED_CLIENT)

    def tearDown(self) -> None:
        activity_storage.clear_all()
        super().tearDown()

    def _make_task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )

    def _make_scout_run(self, task: Task) -> SignalScoutRun:
        return SignalScoutRun.objects.create(
            task_run=TaskRun.objects.create(task=task, team=self.team),
            team=self.team,
            skill_name=SKILL_NAME,
            skill_version=1,
        )

    def _authenticate_with_sandbox_token(
        self, sandbox_task_id: str | None, scoped_teams: list[int] | None = None
    ) -> None:
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="pha_scout_sandbox_token",
            scope="dashboard:write",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id] if scoped_teams is None else scoped_teams,
            scoped_organizations=[],
            sandbox_task_id=sandbox_task_id,
        )
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer pha_scout_sandbox_token")
        OAuthAccessTokenAuthentication().authenticate(request)

    def test_scout_run_token_tags_activity_with_the_scout_name(self) -> None:
        task = self._make_task()
        self._make_scout_run(task)

        self._authenticate_with_sandbox_token(str(task.id))

        assert activity_storage.get_client() == f"scout:{SKILL_NAME}"

    def test_the_scout_is_looked_up_only_when_a_client_is_read(self) -> None:
        task = self._make_task()
        self._make_scout_run(task)

        # The auth module binds the facade function by name, so patch it where it is used.
        with patch("posthog.auth.resolve_scout_client_tag", wraps=resolve_scout_client_tag) as resolve:
            self._authenticate_with_sandbox_token(str(task.id))
            assert resolve.call_count == 0

            assert activity_storage.get_client() == f"scout:{SKILL_NAME}"
            assert activity_storage.get_client() == f"scout:{SKILL_NAME}"
            assert resolve.call_count == 1

    @parameterized.expand(
        [
            ("no task bound to the token", False),
            ("task is not a scout run", True),
        ]
    )
    def test_token_without_a_scout_run_keeps_the_self_reported_client(self, _name: str, bind_task: bool) -> None:
        sandbox_task_id = str(self._make_task().id) if bind_task else None

        self._authenticate_with_sandbox_token(sandbox_task_id)

        assert activity_storage.get_client() == SELF_REPORTED_CLIENT

    @parameterized.expand(
        [
            ("scoped to two teams", "two"),
            ("scoped to no team", "none"),
        ]
    )
    def test_token_that_does_not_name_one_team_keeps_the_self_reported_client(self, _name: str, scoping: str) -> None:
        # Which team's runs to search is not a guess to make, so a token that does not name
        # exactly one team is left with the client it reported, scout run or not.
        task = self._make_task()
        self._make_scout_run(task)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        scoped_teams = [self.team.id, other_team.id] if scoping == "two" else []

        self._authenticate_with_sandbox_token(str(task.id), scoped_teams=scoped_teams)

        assert activity_storage.get_client() == SELF_REPORTED_CLIENT
