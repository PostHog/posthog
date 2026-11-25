from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from posthoganalytics import Client
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team
from posthog.test.persons import create_person
from posthog.uuidt import UUIDT

from products.access_control.backend.facade.testing import (
    PropertyAccess,
    create_access_control,
    set_member_property_access,
)
from products.workflows.backend.facade.testing import create_batch_job_for_test, create_workflow_for_test

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)

ORGANIZATION, INSTANCE, PROJECT = 0, 1, 2
FlagCondition = tuple[int | None, dict[str, object]]
PROJECT_KEY: FlagCondition = (PROJECT, {"key": "$group_key", "type": "group", "group_type_index": PROJECT})
ORGANIZATION_KEY: FlagCondition = (
    ORGANIZATION,
    {"key": "$group_key", "type": "group", "group_type_index": ORGANIZATION},
)
PROJECT_ID: FlagCondition = (PROJECT, {"key": "id", "type": "group", "group_type_index": PROJECT})
EMAIL: FlagCondition = (None, {"key": "email", "type": "person"})


def _email_activity_flag(condition: FlagCondition, value: str) -> dict[str, object]:
    aggregation, prop = condition
    return {
        "id": 1,
        "key": "workflows-email-activity",
        "active": True,
        "filters": {
            "groups": [
                {
                    "properties": [{**prop, "value": [value], "operator": "exact"}],
                    "rollout_percentage": 100,
                    "aggregation_group_type_index": aggregation,
                }
            ]
        },
    }


@time_machine.travel(NOW, tick=False)
class TestWorkflowEmailLog(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow_id = str(create_workflow_for_test(team_id=self.team.id, name="Onboarding").id)
        self.team.workflows_config.capture_workflows_engagement_events = True
        self.team.workflows_config.save()
        self.flag_enabled = self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

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

    def _sent_log(
        self,
        run_id: str,
        step: str,
        at: datetime,
        *,
        distinct_id: str = "jane",
        workflow_id: str | None = None,
        team: Team | None = None,
    ) -> None:
        sync_execute(
            INSERT_LOG_ENTRY_SQL,
            {
                "team_id": (team or self.team).id,
                "log_source": "hog_flow",
                "log_source_id": workflow_id or self.workflow_id,
                "instance_id": run_id,
                "timestamp": at.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "level": "info",
                "message": f"[Action:{step}] Email sent to {distinct_id}@example.com from Hedgebox <hi@example.com>",
            },
        )

    def _sent(self, run_id: str, step: str, at: datetime, **kwargs) -> None:
        self._sent_log(run_id, step, at, **kwargs)
        self._email_event("sent", run_id, step, at, **kwargs)

    def _run_id(self, started: datetime) -> str:
        return str(UUIDT(unix_time_ms=int(started.timestamp() * 1000)))

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/workflow_email_log/{suffix}"

    @parameterized.expand([("restricted", True), ("granted", False)])
    def test_send_log_follows_property_access(self, access: PropertyAccess, blocked: bool) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)
        run_id = self._run_id(NOW - timedelta(days=1))

        responses = [
            self.client.get(self._url(), {"workflow_id": self.workflow_id}),
            self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"}),
            self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"}),
        ]

        assert [response.status_code == 403 for response in responses] == [blocked] * 3

    def test_lists_each_step_of_a_run_as_its_own_send(self):
        run_started = NOW - timedelta(days=2)
        run_id = self._run_id(run_started)
        welcome_at = run_started + timedelta(minutes=1)
        nudge_at = run_started + timedelta(days=1)
        self._sent(run_id, "welcome", welcome_at)
        self._sent_log(run_id, "welcome", welcome_at + timedelta(seconds=30))
        self._email_event("delivered", run_id, "welcome", welcome_at + timedelta(seconds=5))
        self._email_event("link_clicked", run_id, "welcome", welcome_at + timedelta(hours=1))
        self._sent(run_id, "nudge", nudge_at)
        self._email_event("bounced", run_id, "nudge", nudge_at + timedelta(seconds=5))
        other_workflow = str(create_workflow_for_test(team_id=self.team.id, name="Other").id)
        self._sent(self._run_id(run_started), "welcome", welcome_at, workflow_id=other_workflow)
        older_run = self._run_id(NOW - timedelta(days=20))
        self._sent(older_run, "welcome", NOW - timedelta(days=20))
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
            self._sent(run_id, "welcome", sent_at, distinct_id=f"person-{i}")
            for event in ("delivered", "opened", "link_clicked"):
                self._email_event(event, run_id, "welcome", sent_at + timedelta(minutes=1), distinct_id=f"person-{i}")
        flush_persons_and_events()

        body = self.client.get(self._url(), {"workflow_id": self.workflow_id, "limit": "50"}).json()

        assert len(body["results"]) == 40
        assert all((s["status"], s["opened"], s["clicked"]) == ("delivered", True, True) for s in body["results"])

    def test_lists_sends_without_engagement_when_engagement_events_are_off(self):
        self.team.workflows_config.capture_workflows_engagement_events = False
        self.team.workflows_config.save()
        self._sent_log(self._run_id(NOW - timedelta(hours=2)), "welcome", NOW - timedelta(hours=1))

        body = self.client.get(self._url(), {"workflow_id": self.workflow_id}).json()

        assert [(s["recipient"], s["subject"], s["distinct_id"], s["status"]) for s in body["results"]] == [
            ("jane@example.com", "", "", "sent")
        ]
        assert body["engagement_events_enabled"] is False

    @parameterized.expand(
        [
            ("the_project_uuid_the_app_targets", PROJECT_KEY, lambda t: t.team.uuid, status.HTTP_200_OK),
            ("the_organization", ORGANIZATION_KEY, lambda t: t.team.organization_id, status.HTTP_200_OK),
            ("the_users_email", EMAIL, lambda t: t.user.email, status.HTTP_200_OK),
            ("the_project_id_property", PROJECT_ID, lambda t: t.team.id, status.HTTP_200_OK),
            ("the_numeric_team_id_as_project_key", PROJECT_KEY, lambda t: t.team.id, status.HTTP_404_NOT_FOUND),
            ("another_project", PROJECT_KEY, lambda _t: UUIDT(), status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_opens_only_for_what_the_flag_targets(
        self,
        _name: str,
        condition: FlagCondition,
        targeted: Callable[["TestWorkflowEmailLog"], object],
        expected: int,
    ):
        run_id = self._run_id(NOW - timedelta(hours=2))
        self._sent(run_id, "welcome", NOW - timedelta(hours=1))
        flush_persons_and_events()
        flags = Client("phc_test", send=False, enable_local_evaluation=False)
        self.addCleanup(flags.shutdown)
        flags.group_type_mapping = {
            str(ORGANIZATION): "organization",
            str(INSTANCE): "instance",
            str(PROJECT): "project",
        }
        flags.feature_flags = [_email_activity_flag(condition, str(targeted(self)))]
        self.flag_enabled.side_effect = lambda *args, **kwargs: flags.feature_enabled(
            *args, **{**kwargs, "only_evaluate_locally": True}
        )

        listed = self.client.get(self._url(), {"workflow_id": self.workflow_id})
        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert {listed.status_code, detail.status_code, activity.status_code} == {expected}

    def test_pages_through_sends_logged_at_the_same_moment_without_repeats(self):
        sent_at = NOW - timedelta(hours=1)
        for i in range(6):
            self._sent_log(self._run_id(sent_at), "welcome", sent_at, distinct_id=f"person-{i}")

        pages = [
            self.client.get(self._url(), {"workflow_id": self.workflow_id, "limit": "2", "offset": str(offset)}).json()
            for offset in (0, 2, 4)
        ]

        recipients = [send["recipient"] for page in pages for send in page["results"]]
        assert sorted(recipients) == sorted(f"person-{i}@example.com" for i in range(6))

    def test_a_broadcast_send_belongs_to_its_workflow(self):
        batch_job_id = create_batch_job_for_test(team_id=self.team.id, workflow_id=self.workflow_id)
        run_id = self._run_id(NOW - timedelta(hours=2))
        self._sent(run_id, "welcome", NOW - timedelta(hours=1), workflow_id=batch_job_id)
        flush_persons_and_events()

        listed = self.client.get(self._url(), {"workflow_id": self.workflow_id}).json()
        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"}).json()

        assert [(s["invocation_id"], s["workflow_id"]) for s in listed["results"]] == [(run_id, self.workflow_id)]
        assert detail["workflow_id"] == self.workflow_id

    def test_a_send_whose_workflow_cannot_be_found_is_not_found(self):
        run_id = self._run_id(NOW - timedelta(hours=2))
        self._sent(run_id, "welcome", NOW - timedelta(hours=1), workflow_id=str(UUIDT()))
        flush_persons_and_events()

        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert (detail.status_code, activity.status_code) == (status.HTTP_404_NOT_FOUND, status.HTTP_404_NOT_FOUND)

    def test_a_send_event_without_the_run_s_log_line_is_not_a_send(self):
        run_id = self._run_id(NOW - timedelta(hours=2))
        self._email_event("sent", run_id, "welcome", NOW - timedelta(hours=1))
        self._email_event("opened", run_id, "welcome", NOW - timedelta(minutes=30))
        flush_persons_and_events()

        listed = self.client.get(self._url(), {"workflow_id": self.workflow_id}).json()
        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})

        assert (listed["results"], detail.status_code) == ([], status.HTTP_404_NOT_FOUND)

    def test_shows_a_send_with_its_timeline_and_what_the_recipient_did(self):
        create_person(team=self.team, distinct_ids=["jane", "jane-anonymous"])
        run_id = self._run_id(NOW - timedelta(days=200))
        sent_at = NOW - timedelta(days=3)
        self._sent(run_id, "welcome", sent_at)
        self._email_event("delivered", run_id, "welcome", sent_at + timedelta(seconds=5))
        for second in range(100):
            self._email_event("opened", run_id, "welcome", sent_at + timedelta(minutes=3, seconds=second))
        self._email_event("link_clicked", run_id, "welcome", sent_at + timedelta(minutes=5))
        self._sent(run_id, "nudge", sent_at + timedelta(minutes=10))
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
            ("a_broadcast_of_a_workflow_the_user_cannot_view", "broadcast", (404, 404, 404)),
            ("no_person_access", "person", (403, 403, 403)),
            ("no_query_access", "query", (200, 200, 403)),
        ]
    )
    def test_hides_what_the_user_cannot_see(self, _name, denied, expected_statuses):
        run_id = self._run_id(NOW - timedelta(hours=1))
        other_team = Team.objects.create(organization=self.organization)
        self._sent(run_id, "welcome", NOW - timedelta(minutes=30), team=other_team if denied == "other_team" else None)
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
                resource="hog_flow" if denied == "broadcast" else denied,
                resource_id=self.workflow_id if denied in ("hog_flow", "broadcast") else None,
                access_level="none",
                organization_member_id=self.organization_membership.id,
            )

        listed = self.client.get(self._url(), {"workflow_id": self.workflow_id})
        detail = self.client.get(self._url(f"{run_id}/"), {"action_id": "welcome"})
        activity = self.client.get(self._url(f"{run_id}/activity/"), {"action_id": "welcome"})

        assert (listed.status_code, detail.status_code, activity.status_code) == expected_statuses
