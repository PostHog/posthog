import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.outcomes.backend.api import OutcomeSerializer
from products.outcomes.backend.models import Outcome, OutcomeLatch


class TestOutcomeSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_threshold", {"name": "A", "target_event": "signed_up", "threshold": 0}, "threshold"),
            ("loop_guard", {"name": "A", "target_event": "$outcome_reached", "threshold": 1}, "target_event"),
            ("missing_target_event", {"name": "A", "threshold": 1}, "target_event"),
        ]
    )
    def test_rejects_invalid_definitions(self, _name: str, data: dict, error_field: str) -> None:
        serializer = OutcomeSerializer(data=data)
        assert not serializer.is_valid()
        assert error_field in serializer.errors


class TestOutcomeAPI(APIBaseTest):
    def _create_outcome(self, team: Team | None = None, **kwargs) -> Outcome:
        team = team or self.team
        defaults = {"name": "Activated", "target_event": "uploaded_file", "threshold": 3}
        defaults.update(kwargs)
        with team_scope(team.id):
            return Outcome.objects.create(team=team, created_by=self.user, **defaults)

    def _create_latch(self, outcome: Outcome, **kwargs) -> OutcomeLatch:
        defaults = {
            "person_id": uuid.uuid4(),
            "distinct_id": "some-user",
            "reached_at": timezone.now(),
            "event_count": 3,
        }
        defaults.update(kwargs)
        with team_scope(outcome.team_id):
            return OutcomeLatch.objects.create(team_id=outcome.team_id, outcome=outcome, **defaults)

    def test_create_outcome(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/outcomes",
            data={"name": "Activated", "description": "3 uploads", "target_event": "uploaded_file", "threshold": 3},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["reached_count"] == 0
        outcome = Outcome.objects.for_team(self.team.id).get(id=data["id"])
        assert outcome.created_by == self.user
        assert outcome.threshold == 3

    def test_create_rejects_invalid_threshold(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/outcomes",
            data={"name": "Bad", "target_event": "uploaded_file", "threshold": 0},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_is_team_scoped_and_annotates_reached_count(self) -> None:
        outcome = self._create_outcome()
        self._create_latch(outcome)
        self._create_latch(outcome)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._create_outcome(team=other_team, name="Other team outcome")

        response = self.client.get(f"/api/projects/{self.team.id}/outcomes")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [r["name"] for r in results] == ["Activated"]
        assert results[0]["reached_count"] == 2

    def test_criteria_are_immutable_once_facts_exist(self) -> None:
        outcome = self._create_outcome()
        self._create_latch(outcome)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/outcomes/{outcome.id}", data={"target_event": "other_event"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = self.client.patch(f"/api/projects/{self.team.id}/outcomes/{outcome.id}", data={"name": "Renamed"})
        assert response.status_code == status.HTTP_200_OK
        outcome.refresh_from_db()
        assert outcome.name == "Renamed"
        assert outcome.target_event == "uploaded_file"

    def test_reached_lists_latches_most_recent_first(self) -> None:
        outcome = self._create_outcome()
        older = self._create_latch(outcome, reached_at=timezone.now() - timedelta(days=1))
        newer = self._create_latch(outcome)

        response = self.client.get(f"/api/projects/{self.team.id}/outcomes/{outcome.id}/reached")
        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.json()] == [str(newer.id), str(older.id)]

    def test_calculate_enqueues_task(self) -> None:
        outcome = self._create_outcome()
        with patch("products.outcomes.backend.api.calculate_outcome") as mock_task:
            response = self.client.post(f"/api/projects/{self.team.id}/outcomes/{outcome.id}/calculate")
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_task.delay.assert_called_once_with(outcome_id=str(outcome.id), team_id=self.team.id)
