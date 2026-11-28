from datetime import UTC, datetime
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.test.anti_ssrf import mock_anti_ssrf_dns_lookup

from products.user_journeys.backend.facade import api
from products.user_journeys.backend.facade.contracts import (
    CreateJourneyInput,
    CreateJourneyRunInput,
    ElementClickStep,
    PageviewStep,
)
from products.user_journeys.backend.facade.enums import JourneyRunTrigger, UrlMatching
from products.user_journeys.backend.models import JourneyRun, JourneyRunStep

STEPS = [
    {"type": "pageview", "url": "https://example.com/pricing", "url_matching": "exact"},
    {
        "type": "element_click",
        "selector": "button.signup",
        "text": "Sign up",
        "href": None,
        "url": None,
        "url_matching": "exact",
    },
]


@patch("products.user_journeys.backend.facade.api.is_user_journeys_enabled", return_value=True)
class TestJourneyAPI(APIBaseTest):
    def _url(self, journey_id: object = None) -> str:
        base = f"/api/projects/{self.team.id}/user_journeys/"
        return f"{base}{journey_id}/" if journey_id else base

    def test_create_update_list_delete(self, _flag: MagicMock) -> None:
        created = self.client.post(
            self._url(),
            {"name": "Sign up", "steps": STEPS, "source": "toolbar", "start_url": "https://example.com/"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        body = created.json()
        assert body["steps"] == STEPS
        assert body["source"] == "toolbar"
        assert body["start_url"] == "https://example.com/"
        assert body["created_by_id"] == self.user.id
        journey_id = body["id"]

        updated = self.client.patch(
            self._url(journey_id), {"conversion_window_minutes": 60, "steps": STEPS[::-1]}, format="json"
        )
        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["conversion_window_minutes"] == 60
        assert updated.json()["steps"] == STEPS[::-1]
        assert updated.json()["name"] == "Sign up"
        assert updated.json()["start_url"] == "https://example.com/"
        cleared = self.client.patch(self._url(journey_id), {"start_url": ""}, format="json")
        assert cleared.json()["start_url"] is None

        assert self.client.get(self._url(journey_id)).json()["steps"] == STEPS[::-1]
        listed = self.client.get(self._url()).json()
        assert listed["count"] == 1
        assert [j["id"] for j in listed["results"]] == [journey_id]

        assert self.client.delete(self._url(journey_id)).status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self._url(journey_id)).status_code == status.HTTP_404_NOT_FOUND

    def test_funnel_query_returns_the_journeys_funnel(self, _flag: MagicMock) -> None:
        journey_id = self.client.post(
            self._url(), {"name": "Sign up", "steps": STEPS, "conversion_window_minutes": 45}, format="json"
        ).json()["id"]

        response = self.client.get(f"{self._url(journey_id)}funnel_query/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        query = response.json()["query"]
        journey = api.get_journey(self.team.id, UUID(journey_id))
        assert query == api.journey_to_funnels_query(journey).model_dump(mode="json", exclude_none=True)
        assert [node["event"] for node in query["series"]] == ["$pageview", "$autocapture"]
        assert query["funnelsFilter"]["funnelWindowInterval"] == 45
        assert query["funnelsFilter"]["funnelWindowIntervalUnit"] == "minute"

    @parameterized.expand(
        [
            ("too_few_steps", {"steps": STEPS[:1]}),
            ("start_url_not_http", {"steps": STEPS, "start_url": "ftp://example.com/"}),
            ("start_url_with_credentials", {"steps": STEPS, "start_url": "https://me:pw@example.com/"}),
        ]
    )
    def test_invalid_journeys_are_rejected(self, _flag: MagicMock, _name: str, fields: dict) -> None:
        response = self.client.post(self._url(), {"name": "Sign up", **fields}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("get", ""), ("patch", ""), ("delete", ""), ("get", "funnel_query/")])
    def test_another_teams_journey_is_not_found(self, _flag: MagicMock, method: str, action: str) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        other = api.create_journey(
            other_team.id,
            None,
            CreateJourneyInput(name="Other", steps=[PageviewStep(url="/a"), ElementClickStep(selector="#b")]),
        )

        response = getattr(self.client, method)(f"{self._url(other.id)}{action}", {"name": "Taken"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert api.get_journey(other_team.id, other.id).name == "Other"
        assert self.client.get(self._url()).json()["count"] == 0

    def test_flag_off_hides_the_api(self, flag: MagicMock) -> None:
        flag.return_value = False
        assert self.client.get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        response = self.client.post(self._url(), {"name": "Sign up", "steps": STEPS}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@patch("products.user_journeys.backend.facade.api.is_user_journeys_enabled", return_value=True)
@mock_anti_ssrf_dns_lookup()
class TestJourneyRunAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.journey = api.create_journey(
            self.team.id,
            None,
            CreateJourneyInput(
                name="Sign up",
                steps=[PageviewStep(url="https://example.com/pricing"), ElementClickStep(selector="button.signup")],
            ),
        )

    def _runs_url(self, journey_id: object = None, run_id: object = None) -> str:
        base = f"/api/projects/{self.team.id}/user_journeys/{journey_id or self.journey.id}/runs/"
        return f"{base}{run_id}/" if run_id else base

    def test_run_now_returns_a_pending_run_and_executes_it_after_commit(
        self, _dns: MagicMock, _flag: MagicMock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=False) as queued:
            created = self.client.post(self._runs_url(), {"commit_sha": "abc123"}, format="json")

        assert created.status_code == status.HTTP_202_ACCEPTED, created.json()
        run = created.json()
        assert run["status"] == "pending"
        assert run["trigger"] == "manual"
        assert run["commit_sha"] == "abc123"
        assert (run["viewport_width"], run["viewport_height"]) == (1280, 800)
        assert self.client.post(self._runs_url(), {}, format="json").status_code == status.HTTP_409_CONFLICT

        # No browser fleet is configured in tests, so the queued run reaches the browser step and stops there.
        with patch("products.user_journeys.backend.logic.runs.is_user_journeys_enabled", return_value=True):
            for callback in queued:
                callback()

        assert [r["id"] for r in self.client.get(self._runs_url()).json()["results"]] == [run["id"]]
        detail = self.client.get(self._runs_url(run_id=run["id"])).json()
        assert detail["status"] == "errored"
        assert detail["error"] == "Journey runs aren't set up on this PostHog instance."
        assert detail["steps"] == []

    @parameterized.expand(
        [
            ("first_step_not_exact", None, "no start URL"),
            ("start_url_not_authorized", "https://elsewhere.example.org/", "authorized URLs"),
        ]
    )
    def test_journey_that_cannot_start_is_rejected(
        self, _dns: MagicMock, _flag: MagicMock, _name: str, start_url: str | None, message: str
    ) -> None:
        journey = api.create_journey(
            self.team.id,
            None,
            CreateJourneyInput(
                name="Pricing",
                steps=[PageviewStep(url="/pricing", url_matching=UrlMatching.CONTAINS), ElementClickStep(selector="a")],
                start_url=start_url,
            ),
        )

        response = self.client.post(self._runs_url(journey.id), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert self.client.get(self._runs_url(journey.id)).json()["count"] == 0

    @parameterized.expand([("metadata_service", "http://169.254.169.254"), ("unauthorized", "https://example.org")])
    def test_base_url_outside_the_allowed_hosts_is_rejected(
        self, _dns: MagicMock, _flag: MagicMock, _name: str, base_url: str
    ) -> None:
        response = self.client.post(self._runs_url(), {"base_url": base_url}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "authorized URLs" in response.json()["detail"]

    def test_another_teams_runs_are_not_found(self, _dns: MagicMock, _flag: MagicMock) -> None:
        other_team = Team.objects.create(
            organization=Organization.objects.create(name="Other"), app_urls=["https://example.com"]
        )
        other_journey = api.create_journey(
            other_team.id,
            None,
            CreateJourneyInput(
                name="Other", steps=[PageviewStep(url="https://example.com/"), ElementClickStep(selector="a")]
            ),
        )
        other_run = api.start_run(other_team.id, CreateJourneyRunInput(journey_id=other_journey.id))

        assert self.client.get(self._runs_url(other_journey.id)).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(self._runs_url(other_journey.id), {}, format="json").status_code == 404
        assert self.client.get(self._runs_url(other_journey.id, other_run.id)).status_code == 404
        assert self.client.get(self._runs_url(run_id=other_run.id)).status_code == status.HTTP_404_NOT_FOUND

    def _add_run(self, team_id: int, journey_id: UUID, status: str, created_at: datetime) -> JourneyRun:
        run = JourneyRun.objects.for_team(team_id).create(
            team_id=team_id, journey_id=journey_id, trigger=JourneyRunTrigger.MANUAL, status=status
        )
        JourneyRun.objects.for_team(team_id).filter(id=run.id).update(created_at=created_at)
        return run

    def test_journeys_carry_their_latest_run_from_one_query(self, _dns: MagicMock, _flag: MagicMock) -> None:
        never_run = api.create_journey(
            self.team.id, None, CreateJourneyInput(name="Never run", steps=self.journey.steps)
        )
        self._add_run(self.team.id, self.journey.id, "passed", datetime(2026, 11, 1, tzinfo=UTC))
        latest = self._add_run(self.team.id, self.journey.id, "failed", datetime(2026, 11, 2, tzinfo=UTC))
        for index, step_status in enumerate(["passed", "failed", "skipped"]):
            JourneyRunStep.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                run=latest,
                index=index,
                step={},
                status=step_status,
                failure_reason="element_not_visible" if step_status == "failed" else None,
            )
        # A row that names this team's journey but belongs to another team must never leak into the answer.
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        self._add_run(other_team.id, self.journey.id, "passed", datetime(2026, 11, 3, tzinfo=UTC))

        listed = self.client.get(f"/api/projects/{self.team.id}/user_journeys/").json()["results"]
        with CaptureQueriesContext(connection) as two_journeys:
            self.client.get(f"/api/projects/{self.team.id}/user_journeys/")
        for _ in range(3):
            api.create_journey(self.team.id, None, CreateJourneyInput(name="More", steps=self.journey.steps))
        with CaptureQueriesContext(connection) as five_journeys:
            self.client.get(f"/api/projects/{self.team.id}/user_journeys/")

        assert len(five_journeys) == len(two_journeys)
        by_id = {journey["id"]: journey["latest_run"] for journey in listed}
        assert by_id[str(never_run.id)] is None
        expected = {
            "id": str(latest.id),
            "status": "failed",
            "created_at": "2026-11-02T00:00:00Z",
            "finished_at": None,
            "failed_step_index": 1,
        }
        assert by_id[str(self.journey.id)] == expected
        detail = self.client.get(f"/api/projects/{self.team.id}/user_journeys/{self.journey.id}/").json()
        assert detail["latest_run"] == expected
        listed_runs = self.client.get(self._runs_url()).json()["results"]
        assert [(r["id"], r["failed_step_index"], r["failure_reason"]) for r in listed_runs] == [
            (str(latest.id), 1, "element_not_visible"),
            (listed_runs[1]["id"], None, None),
        ]

    def test_flag_off_hides_runs(self, _dns: MagicMock, flag: MagicMock) -> None:
        flag.return_value = False
        assert self.client.get(self._runs_url()).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(self._runs_url(), {}, format="json").status_code == status.HTTP_404_NOT_FOUND
