from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import ANY, patch

from django.test import override_settings

from rest_framework import status
from rest_framework.test import APIClient

from posthog.egress.firecrawl.client import FirecrawlScrape, FirecrawlSearchResult
from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.scoping import team_scope
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, PULSE_ANALYSIS_SCOPES

from products.subscriptions.backend.facade.pulse import begin_evidence_tool_call
from products.subscriptions.backend.models import EvidenceToolCall, PulseRun
from products.tasks.backend.models import Task, TaskRun

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@override_settings(CLOUD_DEPLOYMENT="DEV", PULSE_PUBLIC_RESEARCH_ENABLED=True)
class TestPulsePublicResearch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id, canonical=True):
            subscription = create_subscription(
                team=self.team,
                created_by=self.user,
                prompt="Find a useful product improvement.",
            )
            self.pulse_run = PulseRun.objects.create(
                team=self.team,
                subscription_id=subscription.id,
                delivery_id=uuid4(),
                status=PulseRun.Status.ANALYZING,
                config_snapshot={
                    "actor_id": self.user.id,
                    "contexts": [],
                    "flags": {"allow_public_research": True},
                    "limits": {"max_tool_calls": 20, "max_public_research_calls": 3},
                },
                report_snapshot_ref="reports/pulse-public-research",
            )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Pulse public research",
            description="Research public context for a proactive report.",
            origin_product=Task.OriginProduct.PULSE_SUBSCRIPTION,
            origin_key=f"pulse:{self.pulse_run.id}:analysis",
            internal=True,
            state={
                "staged_caller_id": str(self.pulse_run.id),
                "staged_idempotency_key": f"pulse:{self.pulse_run.id}:analysis",
                "staged_mcp_scope_preset": "pulse_analysis",
            },
        )
        self.analysis_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "staged_phase": "analysis",
                "staged_manifest": {
                    "version": 1,
                    "phase": "analysis",
                    "capabilities": ["read", "research"],
                    "bindings": {
                        "caller_id": str(self.pulse_run.id),
                        "task_id": str(self.task.id),
                        "run_id": "pending",
                        "publication_allowed": False,
                    },
                },
            },
        )
        state = dict(self.analysis_run.state)
        manifest = dict(state["staged_manifest"])
        bindings = dict(manifest["bindings"])
        bindings["run_id"] = str(self.analysis_run.id)
        manifest["bindings"] = bindings
        state["staged_manifest"] = manifest
        self.analysis_run.state = state
        self.analysis_run.save(update_fields=["state", "updated_at"])
        self.pulse_run.task_id = self.task.id
        self.pulse_run.analysis_task_run_id = self.analysis_run.id
        self.pulse_run.save(update_fields=["task_id", "analysis_task_run_id", "updated_at"])
        self.oauth_application = OAuthApplication.objects.create(
            name="Pulse public research sandbox",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )

    def _token(
        self,
        *,
        scope: str | None = None,
        task_id: UUID | None = None,
    ) -> str:
        token = f"pha_pulse_research_{uuid4().hex}"
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token=token,
            expires=datetime(2026, 12, 1, tzinfo=UTC),
            scope=scope or " ".join(PULSE_ANALYSIS_SCOPES),
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id if task_id is not None else self.task.id,
        )
        return token

    def _client(self, token: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/subscriptions/pulse/public-research/"

    def test_searches_a_server_owned_topic_and_retries_without_another_provider_call(self) -> None:
        search_result = FirecrawlSearchResult(
            url="https://example.com/research",
            title="Example research",
            description="A public summary",
        )
        scrape_result = FirecrawlScrape(
            url=search_result.url,
            title=search_result.title,
            markdown="Bounded public research",
        )
        client = self._client(self._token())
        with (
            patch(
                "products.subscriptions.backend.facade.pulse.search_public_web",
                return_value=(search_result,),
            ) as search,
            patch(
                "products.subscriptions.backend.facade.pulse.scrape_public_url",
                return_value=scrape_result,
            ) as scrape,
        ):
            first = client.post(self._url(), {"topic": "activation_best_practices"}, format="json")
            retried = client.post(self._url(), {"topic": "activation_best_practices"}, format="json")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert retried.status_code == status.HTTP_200_OK, retried.json()
        assert retried.json() == first.json()
        assert first.json()["canonical_url"] == "https://example.com/research"
        assert first.json()["excerpt"] == "Bounded public research"
        search.assert_called_once_with(
            "software product activation best practices",
            source="subscriptions_pulse_research",
            limit=2,
            timeout=(3.0, 12.0),
            deadline=ANY,
        )
        scrape.assert_called_once_with(
            "https://example.com/research",
            source="subscriptions_pulse_research",
            timeout=(3.0, 12.0),
            deadline=ANY,
        )
        assert EvidenceToolCall.objects.for_team(self.team.id).filter(run=self.pulse_run).count() == 1

    def test_denies_opted_out_inactive_or_wrong_scope_tasks_without_calling_provider(self) -> None:
        self.pulse_run.config_snapshot["flags"]["allow_public_research"] = False
        self.pulse_run.save(update_fields=["config_snapshot", "updated_at"])

        with patch("products.subscriptions.backend.facade.pulse.search_public_web") as search:
            opted_out = self._client(self._token()).post(self._url(), {"topic": "b2b_saas_benchmarks"}, format="json")
            wrong_scope = self._client(self._token(scope=" ".join(PULSE_ANALYSIS_SCOPES[:-1]))).post(
                self._url(), {"topic": "b2b_saas_benchmarks"}, format="json"
            )
            wrong_task = self._client(self._token(task_id=uuid4())).post(
                self._url(), {"topic": "b2b_saas_benchmarks"}, format="json"
            )

        assert opted_out.status_code == status.HTTP_404_NOT_FOUND
        assert wrong_scope.status_code == status.HTTP_403_FORBIDDEN
        assert wrong_task.status_code == status.HTTP_404_NOT_FOUND
        search.assert_not_called()

    def test_rejects_model_authored_or_extra_input(self) -> None:
        client = self._client(self._token())

        authored = client.post(self._url(), {"topic": "Research our private report"}, format="json")
        query = client.post(self._url(), {"query": "product analytics benchmarks"}, format="json")
        extra = client.post(
            self._url(),
            {"topic": "b2b_saas_benchmarks", "run_id": str(self.pulse_run.id)},
            format="json",
        )

        assert authored.status_code == status.HTTP_400_BAD_REQUEST
        assert query.status_code == status.HTTP_400_BAD_REQUEST
        assert extra.status_code == status.HTTP_400_BAD_REQUEST

    def test_returns_conflict_when_the_public_research_budget_is_exhausted(self) -> None:
        self.pulse_run.config_snapshot["limits"]["max_public_research_calls"] = 0
        self.pulse_run.save(update_fields=["config_snapshot", "updated_at"])

        with patch("products.subscriptions.backend.facade.pulse.search_public_web") as search:
            response = self._client(self._token()).post(
                self._url(),
                {"topic": "b2b_saas_benchmarks"},
                format="json",
            )

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        search.assert_not_called()

    def test_returns_conflict_while_an_identical_request_is_in_progress(self) -> None:
        topic = "b2b_saas_benchmarks"
        query = "B2B SaaS product adoption benchmarks"
        tool_call_id = f"pulse-public-research:{topic}"
        with team_scope(self.team.id, canonical=True):
            begin_evidence_tool_call(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                run_id=self.pulse_run.id,
                tool_call_id=tool_call_id,
                tool_name="pulse_public_research",
                tool_schema_version="v1",
                arguments={"topic": topic, "query": query},
                actor_id=self.user.id,
                raw_expires_at=self.pulse_run.created_at + timedelta(days=7),
            )

        with patch("products.subscriptions.backend.facade.pulse.search_public_web") as search:
            response = self._client(self._token()).post(self._url(), {"topic": topic}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        search.assert_not_called()
