from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.test.persons import create_person

from products.access_control.backend.models.access_control import AccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.tests.api.test_message_assets import create_message_asset

RECORD = "early_access:01a12371-a927-0000-839b-7b96b8563565"
TRIGGER = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {"type": "event", "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events"}]}},
}


class TestPreviousRecipients(ClickhouseTestMixin, APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/workflow_previous_recipients/"

    def _sent(self, flow: HogFlow, distinct_id: str, **kwargs) -> None:
        create_message_asset(
            team_id=flow.team_id,
            function_id=str(flow.id),
            invocation_id=f"{flow.id}-{distinct_id}-{kwargs.get('kind', 'email')}",
            distinct_id=distinct_id,
            **kwargs,
        )

    def _members(self, cohort_id: int) -> list[str]:
        rows = sync_execute(
            "SELECT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
            {"team_id": self.team.pk, "cohort_id": cohort_id},
        )
        return sorted(str(row[0]) for row in rows)

    def test_returns_no_cohort_when_nobody_was_emailed_about_the_record(self) -> None:
        HogFlow.objects.create(team=self.team, name="Earlier", source_record=RECORD)

        response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"cohort_id": None, "people": 0}

    def test_saves_only_people_this_teams_flows_for_the_record_emailed(self) -> None:
        emailed = [str(create_person(team_id=self.team.pk, distinct_ids=[f"emailed-{i}"]).uuid) for i in range(2)]
        # A second profile with an address already emailed would get the next send, because sends dedupe by email.
        emailed.append(
            str(
                create_person(
                    team_id=self.team.pk, distinct_ids=["same-address"], properties={"email": " Emailed-0@Example.com"}
                ).uuid
            )
        )
        create_person(team_id=self.team.pk, distinct_ids=["other"], properties={"email": "other@example.com"})
        create_person(team_id=self.team.pk, distinct_ids=["deleted-send"])
        first = HogFlow.objects.create(team=self.team, name="First", source_record=RECORD)
        second = HogFlow.objects.create(team=self.team, name="Second", source_record=RECORD)
        other_record = HogFlow.objects.create(team=self.team, name="Other", source_record="cohort:42")
        other_team = Team.objects.create(organization=self.organization)
        other_team_flow = HogFlow.objects.create(team=other_team, name="Elsewhere", source_record=RECORD)
        self._sent(first, "emailed-0", recipient="emailed-0@example.com")
        self._sent(first, "deleted-send")
        self._sent(first, "deleted-send", is_deleted=1, version=2)
        # The person this send went to merged into another one since, so the stored person ID is stale.
        self._sent(second, "emailed-1", person_id="00000000-0000-0000-0000-000000000000")
        self._sent(second, "other", asset_status="failed")
        self._sent(second, "other", kind="push")
        self._sent(other_record, "other")
        self._sent(other_team_flow, "other")

        response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        cohort = Cohort.objects.get(pk=response.json()["cohort_id"])
        assert cohort.is_static and not cohort.is_calculating
        assert cohort.team_id == self.team.pk
        assert response.json()["people"] == 3
        assert self._members(cohort.pk) == sorted(emailed)

    def test_leaves_out_sends_from_workflows_the_caller_cannot_see(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        visible_person = str(create_person(team_id=self.team.pk, distinct_ids=["visible"]).uuid)
        create_person(team_id=self.team.pk, distinct_ids=["hidden"])
        visible = HogFlow.objects.create(team=self.team, name="Visible", source_record=RECORD)
        hidden = HogFlow.objects.create(team=self.team, name="Hidden", source_record=RECORD)
        self._sent(visible, "visible")
        self._sent(hidden, "hidden")
        member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(hidden.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(member)

        response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._members(response.json()["cohort_id"]) == [visible_person]

    @parameterized.expand(
        [
            ("repeat sends to one person stay within the limit", ["one", "one", "one"], status.HTTP_200_OK),
            ("more people than the limit are rejected", ["one", "two"], status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_limits_people_not_sends(self, _name: str, sends: list[str], expected: int) -> None:
        for distinct_id in set(sends):
            create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
        flow = HogFlow.objects.create(team=self.team, name="Repeated", source_record=RECORD)
        for index, distinct_id in enumerate(sends):
            create_message_asset(
                team_id=self.team.pk,
                function_id=str(flow.id),
                invocation_id=f"{flow.id}-{index}",
                distinct_id=distinct_id,
                recipient=f"{distinct_id}@example.com",
            )

        with patch("products.workflows.backend.services.previous_recipients.MAX_PREVIOUS_RECIPIENTS", 1):
            response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == expected, response.json()

    def test_a_population_past_its_deadline_fails_and_leaves_no_cohort(self) -> None:
        flow = HogFlow.objects.create(team=self.team, name="Slow", source_record=RECORD)
        for distinct_id in ["one", "two"]:
            create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            self._sent(flow, distinct_id)

        with (
            patch("products.workflows.backend.services.previous_recipients.DEFAULT_COHORT_INSERT_BATCH_SIZE", 1),
            patch("products.workflows.backend.services.previous_recipients.POPULATION_DEADLINE_SECONDS", -1),
        ):
            response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.json()
        assert not Cohort.objects.filter(team_id=self.team.pk, name="Already emailed").exists()

    def test_records_the_source_record_on_create_and_keeps_it_on_update(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {"name": "From a link", "source_record": RECORD, "actions": [TRIGGER]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flow_id = response.json()["id"]

        update = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/", {"source_record": "cohort:1"}, format="json"
        )
        assert update.status_code == status.HTTP_200_OK, update.json()

        assert HogFlow.objects.get(pk=flow_id).source_record == RECORD
