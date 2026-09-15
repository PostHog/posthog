from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.test import RequestFactory

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import OAuthApplication
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.oauth import OAuthAccessToken

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun

SCOUT_SKILL = "signals-scout-error-tracking"


class TestScoutActivityClient(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.factory = RequestFactory()
        self.application = OAuthApplication.objects.create(
            client_id="scout-client-id",
            redirect_uris="http://localhost/cb",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            organization=self.organization,
        )
        activity_storage.mark_request_scoped()
        self.addCleanup(activity_storage.clear_all)

    def _create_task(self):
        Task = apps.get_model("tasks", "Task")
        return Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )

    def _create_run(self, task, *, skill_name: str = SCOUT_SKILL) -> SignalScoutRun:
        TaskRun = apps.get_model("tasks", "TaskRun")
        config, _ = SignalScoutConfig.objects.get_or_create(team=self.team, skill_name=skill_name)
        return SignalScoutRun.objects.create(
            team=self.team,
            task_run=TaskRun.objects.create(task=task, team=self.team),
            scout_config=config,
            skill_name=skill_name,
            skill_version=1,
        )

    def _authenticate(self, *, sandbox_task_id=None) -> str | None:
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="pha_scout_token",
            scope="dashboard:write",
            expires="2099-01-01T00:00:00Z",
            scoped_teams=[self.team.id],
            scoped_organizations=[],
            sandbox_task_id=sandbox_task_id,
        )
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer pha_scout_token")
        # What ActivityLoggingMiddleware has already stored by the time authentication runs.
        activity_storage.set_client("mcp")
        assert OAuthAccessTokenAuthentication().authenticate(request) is not None
        return activity_storage.get_client()

    def test_token_bound_to_a_scout_run_names_the_scout(self) -> None:
        task = self._create_task()
        self._create_run(task)

        assert self._authenticate(sandbox_task_id=task.id) == f"scout:{SCOUT_SKILL}"

    def test_a_retried_task_names_the_scout_of_its_newest_run(self) -> None:
        task = self._create_task()
        self._create_run(task, skill_name="signals-scout-logs")
        self._create_run(task)

        assert self._authenticate(sandbox_task_id=task.id) == f"scout:{SCOUT_SKILL}"

    @parameterized.expand(
        [
            ("no_task_on_the_token", False),
            ("task_without_a_scout_run", True),
        ]
    )
    def test_a_non_scout_request_keeps_the_self_reported_client(self, _name: str, bind_task: bool) -> None:
        sandbox_task_id = self._create_task().id if bind_task else None

        assert self._authenticate(sandbox_task_id=sandbox_task_id) == "mcp"

    def test_a_failed_lookup_leaves_authentication_alone(self) -> None:
        task = self._create_task()
        self._create_run(task)

        with patch(
            "posthog.auth.resolve_scout_activity_client",
            side_effect=Exception("database is down"),
        ):
            assert self._authenticate(sandbox_task_id=task.id) == "mcp"
