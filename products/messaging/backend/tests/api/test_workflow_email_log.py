from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.test.persons import create_person
from posthog.uuidt import UUIDT

from products.access_control.backend.facade.testing import create_access_control
from products.workflows.backend.facade.testing import create_workflow_for_test

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
class TestWorkflowEmailLog(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = str(create_workflow_for_test(team_id=self.team.id, name="Onboarding").id)
        self.team.workflows_config.capture_workflows_engagement_events = True
        self.team.workflows_config.save()

    def _email_event(
        self,
        event: str,
        run_id: str,
        step: str,
        at: datetime,
        *,
        distinct_id: str = "jane",
        workflow_id: str | None = None,
        team: Team | None = None,
        **properties: str,
    ) -> None:
        _create_event(
            team=team or self.team,
            event=f"$workflows_email_{event}",
            distinct_id=distinct_id,
            timestamp=at,
            properties={
                "$workflow_id": workflow_id or self.workflow_id,
                "$workflow_action_id": step,
                "$workflow_invocation_id": run_id,
                "$email_to": f"{distinct_id}@example.com",
                "$email_subject": f"Hello from {step}",
                **properties,
            },
        )

    def _run_id(self, started: datetime) -> str:
        return str(UUIDT(unix_time_ms=int(started.timestamp() * 1000)))

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/workflow_email_log/{suffix}"

    def test_lists_each_step_of_a_run_as_its_own_send(self):
        run_started = NOW - timedelta(days=2)
        run_id = self._run_id(run_started)
        welcome_at = run_started + timedelta(minutes=1)
        nudge_at = run_started + timedelta(days=1)
        self._email_event("sent", run_id, "welcome", welcome_at)
        self._email_event("delivered", run_id, "welcome", welcome_at + timedelta(seconds=5))
        self._email_event("link_clicked", run_id, "welcome", welcome_at + timedelta(hours=1))
        self._email_event("sent", run_id, "nudge", nudge_at)
        self._email_event("bounced", run_id, "nudge", nudge_at + timedelta(seconds=5))
        other_workflow = str(create_workflow_for_test(team_id=self.team.id, name="Other").id)
        self._email_event("sent", self._run_id(run_started), "welcome", welcome_at, workflow_id=other_workflow)
        older_run = self._run_id(NOW - timedelta(days=20))
        self._email_event("sent", older_run, "welcome", NOW - timedelta(days=20))
        self._email_event("link_clicked", older_run, "welcome", NOW - timedelta(days=10))
        flush_persons_and_events()

        response = self.client.get(
            self._url(), {"workflow_id": self.workflow_id, "date_from": (NOW - timedelta(days=30)).isoformat()}
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [(s["action_id"], s["status"], s["opened"], s["clicked"]) for s in body["results"]] == [
            ("nudge", "bounced", False, False),
            ("welcome", "delivered", True, True),
            ("welcome", "sent", False, False),
        ]
        assert (body["has_more"], body["engagement_events_enabled"]) == (False, True)

    def test_a_full_page_keeps_every_send_s_engagement(self):
        sent_at = NOW - timedelta(days=1)
        for i in range(40):
            run_id = self._run_id(sent_at)
            self._email_event("sent", run_id, "welcome", sent_at, distinct_id=f"person-{i}")
            for event in ("delivered", "opened", "link_clicked"):
                self._email_event(event, run_id, "welcome", sent_at + timedelta(minutes=1), distinct_id=f"person-{i}")
        flush_persons_and_events()

        body = self.client.get(self._url(), {"workflow_id": self.workflow_id, "limit": 50}).json()

        assert len(body["results"]) == 40
        assert all((s["status"], s["opened"], s["clicked"]) == ("delivered", True, True) for s in body["results"])

    def test_says_when_engagement_events_are_off(self):
        self.team.workflows_config.capture_workflows_engagement_events = False
        self.team.workflows_config.save()

        body = self.client.get(self._url(), {"workflow_id": self.workflow_id}).json()

        assert (body["results"], body["engagement_events_enabled"]) == ([], False)

    def test_shows_a_send_with_its_timeline_and_what_the_recipient_did(self):
        create_person(team=self.team, distinct_ids=["jane", "jane-anonymous"])
        run_id = self._run_id(NOW - timedelta(days=200))
        sent_at = NOW - timedelta(days=3)
        self._email_event("sent", run_id, "welcome", sent_at)
        self._email_event("delivered", run_id, "welcome", sent_at + timedelta(seconds=5))
        for second in range(100):
            self._email_event("opened", run_id, "welcome", sent_at + timedelta(minutes=3, seconds=second))
        self._email_event("link_clicked", run_id, "welcome", sent_at + timedelta(minutes=5))
        self._email_event("sent", run_id, "nudge", sent_at + timedelta(minutes=10))
        for event, distinct_id, offset in [
            ("$pageview", "jane-anonymous", -timedelta(hours=1)),
            ("$pageview", "jane", timedelta(minutes=4)),
            ("upgraded_plan", "jane", timedelta(minutes=6)),
        ]:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=sent_at + offset,
                properties={"$session_id": "s1"},
            )
        flush_persons_and_events()

        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert detail.status_code == status.HTTP_200_OK, detail.json()
        assert [e["kind"] for e in detail.json()["timeline"]] == ["sent", "delivered", *["opened"] * 99]
        assert (detail.json()["subject"], detail.json()["clicked"]) == ("Hello from welcome", True)
        assert activity.status_code == status.HTTP_200_OK, activity.json()
        body = activity.json()
        assert datetime.fromisoformat(body["sent_at"]) == sent_at
        assert [e["event"] for e in body["before"]] == ["$pageview"]
        assert [e["event"] for e in body["after"]] == ["$pageview", "upgraded_plan"]

    def test_a_run_id_without_a_plausible_start_time_is_not_found(self):
        run_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"

        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert (detail.status_code, activity.status_code) == (status.HTTP_404_NOT_FOUND, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("another_projects_send", "other_team", (200, 404, 404)),
            ("a_workflow_the_user_cannot_view", "hog_flow", (404, 404, 404)),
            ("no_person_access", "person", (403, 403, 403)),
            ("no_query_access", "query", (200, 200, 403)),
        ]
    )
    def test_hides_what_the_user_cannot_see(self, _name, denied, expected_statuses):
        run_id = self._run_id(NOW - timedelta(hours=1))
        other_team = Team.objects.create(organization=self.organization)
        self._email_event(
            "sent", run_id, "welcome", NOW - timedelta(minutes=30), team=other_team if denied == "other_team" else None
        )
        flush_persons_and_events()
        if denied != "other_team":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
                {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
            ]
            self.organization.save()
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            create_access_control(
                team_id=self.team.id,
                resource=denied,
                resource_id=self.workflow_id if denied == "hog_flow" else None,
                access_level="none",
                organization_member_id=self.organization_membership.id,
            )

        listed = self.client.get(self._url(), {"workflow_id": self.workflow_id})
        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert (listed.status_code, detail.status_code, activity.status_code) == expected_statuses
