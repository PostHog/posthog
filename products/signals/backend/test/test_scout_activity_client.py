from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import OAuthApplication
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.oauth import OAuthAccessToken

from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.models import Task, TaskRun

SELF_REPORTED_CLIENT = "mcp"


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

    def _authenticate_with_sandbox_token(self, sandbox_task_id: str | None) -> None:
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="pha_scout_sandbox_token",
            scope="dashboard:write",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            scoped_organizations=[],
            sandbox_task_id=sandbox_task_id,
        )
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer pha_scout_sandbox_token")
        OAuthAccessTokenAuthentication().authenticate(request)

    def test_scout_run_token_tags_activity_with_the_scout_name(self) -> None:
        task = self._make_task()
        SignalScoutRun.objects.create(
            task_run=TaskRun.objects.create(task=task, team=self.team),
            team=self.team,
            skill_name="signals-scout-self-driving-dwh",
            skill_version=1,
        )

        self._authenticate_with_sandbox_token(str(task.id))

        assert activity_storage.get_client() == "scout:signals-scout-self-driving-dwh"

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
