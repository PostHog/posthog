from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, PersonalAPIKey, ProjectSecretAPIKey, Team
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret
from posthog.temporal.common.registration import validate_registration
from posthog.test.anti_ssrf import PUBLIC_TEST_IP, mock_anti_ssrf_dns_lookup

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import (
    DEPLOY_IDEMPOTENCY_WINDOW_MINUTES,
    CreateJourneyDeployInput,
    CreateJourneyInput,
    CreateJourneyRunInput,
    ElementClickStep,
    PageviewStep,
)
from products.user_journeys.backend.facade.enums import (
    JourneyDeployStatus,
    JourneyRunStatus,
    JourneyRunTrigger,
    UrlMatching,
)
from products.user_journeys.backend.facade.temporal import TEMPORAL
from products.user_journeys.backend.logic import runs
from products.user_journeys.backend.logic.deploys import deploy_status
from products.user_journeys.backend.models import JourneyRun, JourneyRunStep

_NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

P, R, OK, F, E = (
    JourneyRunStatus.PENDING,
    JourneyRunStatus.RUNNING,
    JourneyRunStatus.PASSED,
    JourneyRunStatus.FAILED,
    JourneyRunStatus.ERRORED,
)


class TestDeployStatus(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_runs", [], JourneyDeployStatus.NO_RUNS),
            ("all_pending", [P, P], JourneyDeployStatus.PENDING),
            ("one_started", [P, R], JourneyDeployStatus.RUNNING),
            ("some_finished", [P, OK], JourneyDeployStatus.RUNNING),
            ("failed_wins_while_others_run", [R, F, P], JourneyDeployStatus.FAILED),
            ("failed_wins_over_errored", [E, F, OK], JourneyDeployStatus.FAILED),
            ("errored_waits_for_active_runs", [E, R], JourneyDeployStatus.RUNNING),
            ("errored_once_all_ended", [E, OK], JourneyDeployStatus.ERRORED),
            ("all_passed", [OK, OK], JourneyDeployStatus.PASSED),
        ]
    )
    def test_roll_up(self, _name: str, statuses: list[JourneyRunStatus], expected: JourneyDeployStatus) -> None:
        assert deploy_status(statuses) == expected


def _journey(team_id: int, name: str, **kwargs: Any) -> UUID:
    steps = kwargs.pop("steps", [PageviewStep(url="https://example.com/pricing"), ElementClickStep(selector="a")])
    return api.create_journey(team_id, None, CreateJourneyInput(name=name, steps=steps, **kwargs)).id


@patch("products.user_journeys.backend.facade.api.is_user_journeys_enabled", return_value=True)
@mock_anti_ssrf_dns_lookup()
class TestJourneyDeployAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.app_urls = ["https://example.com", "https://preview.example.com"]
        self.team.save()
        self.url = f"/api/projects/{self.team.id}/user_journeys/deploys/"

    def _post(self, body: dict[str, Any], client: APIClient | None = None) -> tuple[Any, list[str]]:
        with (
            patch("products.user_journeys.backend.tasks.tasks.execute_journey_run.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = (client or self.client).post(self.url, body, format="json")
        return response, [call.args[1] for call in delay.call_args_list]

    def _psak_client(self, scopes: list[str], team: Team | None = None) -> APIClient:
        token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team or self.team,
            label=f"ci {ProjectSecretAPIKey.objects.count()}",
            secure_value=hash_key_value(token),
            scopes=scopes,
            mask_value=f"{token[:4]}...{token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def _personal_key_client(self, scopes: list[str]) -> APIClient:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label=f"ci {PersonalAPIKey.objects.count()}",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_deploy_runs_each_runnable_journey_and_reports_the_rest(self, _dns: MagicMock, _flag: MagicMock) -> None:
        runnable = _journey(self.team.id, "Checkout")
        not_runnable = _journey(
            self.team.id,
            "Pricing",
            steps=[PageviewStep(url="/pricing", url_matching=UrlMatching.CONTAINS), ElementClickStep(selector="a")],
        )
        unauthorized = _journey(self.team.id, "Partner", start_url="https://elsewhere.example.org/")
        busy = _journey(self.team.id, "Signup")
        api.start_run(self.team.id, CreateJourneyRunInput(journey_id=busy))
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other_teams_journey = _journey(other_team.id, "Not yours")

        response, queued = self._post(
            {
                "commit_sha": "abc123",
                "branch": "main",
                "base_url": "https://preview.example.com/some/path",
                "url": "https://ci.example.com/runs/1",
                "journey_ids": [str(j) for j in [runnable, not_runnable, unauthorized, busy, other_teams_journey]],
            }
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        deploy = response.json()
        assert (deploy["status"], deploy["run_count"], deploy["base_url"]) == (
            "pending",
            2,
            "https://preview.example.com",
        )
        # The preview origin is authorized, so a journey whose own start URL isn't still runs against it.
        assert [(run["journey_id"], run["status"]) for run in deploy["runs"]] == [
            (str(runnable), "pending"),
            (str(unauthorized), "pending"),
        ]
        assert sorted(queued) == sorted(run["run_id"] for run in deploy["runs"])
        assert {skip["journey_id"]: skip["reason"] for skip in deploy["skipped"]} == {
            str(not_runnable): "not_runnable",
            str(busy): "run_in_progress",
            str(other_teams_journey): "journey_not_found",
        }
        run = JourneyRun.objects.for_team(self.team.id).get(id=deploy["runs"][0]["run_id"])
        assert (run.trigger, str(run.deploy_id), run.commit_sha) == (JourneyRunTrigger.DEPLOY, deploy["id"], "abc123")

        JourneyRun.objects.for_team(self.team.id).filter(id=run.id).update(status=JourneyRunStatus.FAILED)
        JourneyRunStep.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            index=1,
            step={},
            status="failed",
            failure_reason="element_obscured",
            message="Another element covers the button.",
        )
        detail = self.client.get(f"{self.url}{deploy['id']}/").json()
        assert detail["status"] == "failed"
        assert {k: detail["runs"][0][k] for k in ("failed_step_index", "failure_reason", "message")} == {
            "failed_step_index": 1,
            "failure_reason": "element_obscured",
            "message": "Another element covers the button.",
        }
        assert detail["skipped"] == deploy["skipped"]
        listed = self.client.get(self.url).json()
        assert [(d["id"], d["status"]) for d in listed["results"]] == [(deploy["id"], "failed")]

    def test_without_journey_ids_every_journey_runs_against_its_own_start_url(
        self, _dns: MagicMock, _flag: MagicMock
    ) -> None:
        runnable = _journey(self.team.id, "Checkout")
        unauthorized = _journey(self.team.id, "Partner", start_url="https://elsewhere.example.org/")

        response, queued = self._post({"commit_sha": "abc123"})

        deploy = response.json()
        assert [run["journey_id"] for run in deploy["runs"]] == [str(runnable)]
        assert [(s["journey_id"], s["reason"]) for s in deploy["skipped"]] == [
            (str(unauthorized), "target_not_allowed")
        ]
        assert len(queued) == 1

    @time_machine.travel(_NOW, tick=False)
    def test_a_retried_deploy_returns_the_first_and_starts_nothing(self, _dns: MagicMock, _flag: MagicMock) -> None:
        _journey(self.team.id, "Checkout")
        body = {"commit_sha": "abc123", "base_url": "https://preview.example.com"}

        first, first_queued = self._post(body)
        retry, retry_queued = self._post({**body, "base_url": "https://preview.example.com/other"})
        other_origin, _ = self._post({**body, "base_url": "https://example.com"})

        assert (first.status_code, retry.status_code) == (status.HTTP_201_CREATED, status.HTTP_200_OK)
        assert retry.json()["id"] == first.json()["id"]
        assert (len(first_queued), retry_queued) == (1, [])
        assert other_origin.status_code == status.HTTP_201_CREATED
        assert other_origin.json()["id"] != first.json()["id"]

        later = _NOW + timedelta(minutes=DEPLOY_IDEMPOTENCY_WINDOW_MINUTES + 1)
        with time_machine.travel(later, tick=False):
            after_window, _ = self._post(body)
        assert after_window.status_code == status.HTTP_201_CREATED
        assert after_window.json()["id"] != first.json()["id"]

    @parameterized.expand(
        [
            ("authorized_host_resolving_internally", "https://preview.example.com", "10.0.0.5", "can't be reached"),
            ("unauthorized_host", "https://example.org", PUBLIC_TEST_IP, "authorized URLs"),
            ("not_http", "ftp://example.com", PUBLIC_TEST_IP, "http:// or https://"),
        ]
    )
    def test_a_base_url_runs_may_not_open_is_rejected_before_anything_is_recorded(
        self, _dns: MagicMock, _flag: MagicMock, _name: str, base_url: str, resolves_to: object, message: str
    ) -> None:
        _journey(self.team.id, "Checkout")

        with mock_anti_ssrf_dns_lookup([resolves_to]):  # type: ignore[list-item]
            response, queued = self._post({"commit_sha": "abc123", "base_url": base_url})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert queued == []
        assert self.client.get(self.url).json()["count"] == 0

    def test_another_teams_deploys_are_not_found(self, _dns: MagicMock, _flag: MagicMock) -> None:
        other_team = Team.objects.create(
            organization=Organization.objects.create(name="Other"), app_urls=["https://example.com"]
        )
        other = api.create_deploy(other_team.id, CreateJourneyDeployInput(commit_sha="abc123")).deploy

        assert self.client.get(f"{self.url}{other.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self.url).json()["count"] == 0
        other_teams_key = self._psak_client(["user_journey:read"], team=other_team)
        assert other_teams_key.get(self.url).status_code == status.HTTP_403_FORBIDDEN

    def test_flag_off_hides_deploys(self, _dns: MagicMock, flag: MagicMock) -> None:
        flag.return_value = False

        assert self.client.get(self.url).status_code == status.HTTP_404_NOT_FOUND
        assert self._post({"commit_sha": "abc123"})[0].status_code == status.HTTP_404_NOT_FOUND
        assert self._psak_client(["user_journey:read"]).get(self.url).status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("secret_key_with_write", "psak", ["user_journey:write"], 201, 200),
            ("secret_key_with_read", "psak", ["user_journey:read"], 403, 200),
            ("secret_key_without_scope", "psak", ["feature_flag:read"], 403, 403),
            ("personal_key_with_write", "personal", ["user_journey:write"], 201, 200),
            ("personal_key_without_scope", "personal", ["insight:read"], 403, 403),
        ]
    )
    def test_tokens_need_the_user_journey_scope(
        self,
        _dns: MagicMock,
        _flag: MagicMock,
        _name: str,
        kind: str,
        scopes: list[str],
        create_status: int,
        read_status: int,
    ) -> None:
        journey = _journey(self.team.id, "Checkout")
        client = self._psak_client(scopes) if kind == "psak" else self._personal_key_client(scopes)

        created, _ = self._post({"commit_sha": "abc123"}, client=client)
        listed = client.get(self.url)
        runs_url = f"/api/projects/{self.team.id}/user_journeys/{journey}/runs/"

        assert created.status_code == create_status
        assert listed.status_code == read_status
        assert client.get(runs_url).status_code == read_status
        # Starting a run by hand stays with a logged-in person, whatever the token holds.
        assert client.post(runs_url, {}, format="json").status_code == status.HTTP_403_FORBIDDEN
        if create_status == status.HTTP_201_CREATED:
            expected_creator = self.user.id if kind == "personal" else None
            assert created.json()["created_by_id"] == expected_creator


class TestReapStaleRuns(BaseTest):
    def _run(self, team: Team, run_status: JourneyRunStatus, age: timedelta) -> JourneyRun:
        journey_id = _journey(team.id, f"Journey {JourneyRun.objects.unscoped().count()}")
        at = timezone.now() - age
        run = JourneyRun.objects.for_team(team.id).create(
            team_id=team.id, journey_id=journey_id, trigger=JourneyRunTrigger.DEPLOY, status=run_status
        )
        JourneyRun.objects.for_team(team.id).filter(id=run.id).update(created_at=at, started_at=at)
        return run

    def test_the_scheduled_sweep_ends_stale_runs_in_every_team_and_leaves_fresh_ones(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        stale_age = runs.PENDING_STALE_AFTER + timedelta(minutes=1)
        stale = [
            self._run(self.team, JourneyRunStatus.RUNNING, runs.RUN_STALE_AFTER + timedelta(minutes=1)),
            self._run(other_team, JourneyRunStatus.PENDING, stale_age),
        ]
        fresh = [
            self._run(self.team, JourneyRunStatus.PENDING, timedelta(minutes=1)),
            self._run(other_team, JourneyRunStatus.RUNNING, timedelta(minutes=1)),
            self._run(other_team, JourneyRunStatus.PASSED, stale_age),
        ]

        assert runs.reap_stale_runs_all_teams() == len(stale)

        for run in stale:
            run.refresh_from_db()
            assert run.status == JourneyRunStatus.ERRORED
        for run, before in zip(fresh, [JourneyRunStatus.PENDING, JourneyRunStatus.RUNNING, JourneyRunStatus.PASSED]):
            run.refresh_from_db()
            assert run.status == before


def test_core_accepts_the_user_journeys_temporal_declaration() -> None:
    validate_registration("user_journeys", TEMPORAL)
