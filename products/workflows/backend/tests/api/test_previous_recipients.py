from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.team.team import Team
from posthog.test.persons import create_person

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

    def _sent(self, flow: HogFlow, person_id: str, **kwargs) -> None:
        create_message_asset(
            team_id=flow.team_id,
            function_id=str(flow.id),
            invocation_id=f"{flow.id}-{person_id}-{kwargs.get('kind', 'email')}",
            person_id=person_id,
            **kwargs,
        )

    def test_returns_no_cohort_when_nobody_was_emailed_about_the_record(self) -> None:
        HogFlow.objects.create(team=self.team, name="Earlier", source_record=RECORD)

        response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"cohort_id": None, "people": 0}

    def test_saves_only_people_this_teams_flows_for_the_record_emailed(self) -> None:
        emailed = [str(create_person(team_id=self.team.pk, distinct_ids=[f"emailed-{i}"]).uuid) for i in range(2)]
        not_emailed = str(create_person(team_id=self.team.pk, distinct_ids=["other"]).uuid)
        first = HogFlow.objects.create(team=self.team, name="First", source_record=RECORD)
        second = HogFlow.objects.create(team=self.team, name="Second", source_record=RECORD)
        other_record = HogFlow.objects.create(team=self.team, name="Other", source_record="cohort:42")
        other_team = Team.objects.create(organization=self.organization)
        other_team_flow = HogFlow.objects.create(team=other_team, name="Elsewhere", source_record=RECORD)
        self._sent(first, emailed[0])
        self._sent(second, emailed[1])
        self._sent(second, not_emailed, asset_status="failed")
        self._sent(second, not_emailed, kind="push")
        self._sent(other_record, not_emailed)
        self._sent(other_team_flow, not_emailed)

        response = self.client.post(self._url(), {"source_record": RECORD, "cohort_name": "Already emailed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        cohort = Cohort.objects.get(pk=response.json()["cohort_id"])
        assert cohort.is_static and not cohort.is_calculating
        assert cohort.team_id == self.team.pk
        assert response.json()["people"] == 2
        members = sync_execute(
            "SELECT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
            {"team_id": self.team.pk, "cohort_id": cohort.pk},
        )
        assert sorted(str(row[0]) for row in members) == sorted(emailed)

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
