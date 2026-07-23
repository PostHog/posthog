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

from products.outcomes.backend.api import OutcomeDefinitionSerializer
from products.outcomes.backend.models import OutcomeDefinition, OutcomeLatch

from .test_criteria import atom, criteria, path

VALID_CRITERIA = criteria(
    path(
        atom("uploaded_file", threshold=3),
        atom("purchase", aggregation="sum", aggregation_property="amount", threshold=100),
        min_matches=1,
    ),
    path(atom("invited_teammate")),
)


class TestOutcomeSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_paths", {"paths": []}),
            ("empty_path", criteria({"atoms": [], "min_matches": None})),
            ("loop_guard", criteria(path(atom("$outcome_reached")))),
            ("non_monotone_aggregation", criteria(path(atom(aggregation="avg", aggregation_property="x")))),
            ("sum_without_property", criteria(path(atom(aggregation="sum", threshold=10)))),
            ("zero_threshold", criteria(path(atom(threshold=0)))),
            ("min_matches_above_atom_count", criteria(path(atom(), min_matches=2))),
        ]
    )
    def test_rejects_inadmissible_criteria(self, _name: str, criteria_dict: dict) -> None:
        serializer = OutcomeDefinitionSerializer(data={"name": "A", "criteria": criteria_dict})
        assert not serializer.is_valid()
        assert "criteria" in serializer.errors

    def test_accepts_full_grammar(self) -> None:
        serializer = OutcomeDefinitionSerializer(data={"name": "A", "criteria": VALID_CRITERIA})
        assert serializer.is_valid(), serializer.errors


class TestOutcomeAPI(APIBaseTest):
    def _create_outcome(self, team: Team | None = None, **kwargs) -> OutcomeDefinition:
        team = team or self.team
        defaults = {"name": "Activated", "criteria": criteria(path(atom("uploaded_file", threshold=3)))}
        defaults.update(kwargs)
        with team_scope(team.id):
            return OutcomeDefinition.objects.create(team=team, created_by=self.user, **defaults)

    def _create_latch(self, outcome: OutcomeDefinition, **kwargs) -> OutcomeLatch:
        defaults = {
            "person_id": uuid.uuid4(),
            "distinct_id": "some-user",
            "reached_at": timezone.now(),
            "evidence": {"winning_path": 0, "paths": []},
        }
        defaults.update(kwargs)
        with team_scope(outcome.team_id):
            return OutcomeLatch.objects.create(team_id=outcome.team_id, definition=outcome, **defaults)

    def test_create_outcome_with_full_criteria(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/outcomes",
            data={"name": "Activated", "description": "Full grammar", "criteria": VALID_CRITERIA},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["reached_count"] == 0
        assert [len(p["atoms"]) for p in data["criteria"]["paths"]] == [2, 1]
        assert data["criteria"]["paths"][0]["min_matches"] == 1
        outcome = OutcomeDefinition.objects.for_team(self.team.id).get(id=data["id"])
        assert outcome.created_by == self.user
        assert outcome.criteria["paths"][0]["atoms"][1]["aggregation"] == "sum"

    def test_create_rejects_inadmissible_criteria(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/outcomes",
            data={"name": "Bad", "criteria": criteria(path(atom(threshold=0)))},
            format="json",
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
            f"/api/projects/{self.team.id}/outcomes/{outcome.id}",
            data={"criteria": criteria(path(atom("other_event")))},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        response = self.client.patch(f"/api/projects/{self.team.id}/outcomes/{outcome.id}", data={"name": "Renamed"})
        assert response.status_code == status.HTTP_200_OK
        outcome.refresh_from_db()
        assert outcome.name == "Renamed"
        assert outcome.criteria["paths"][0]["atoms"][0]["event"] == "uploaded_file"

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

    def test_calculate_is_debounced_after_a_recent_run(self) -> None:
        outcome = self._create_outcome(last_calculated_at=timezone.now())
        with patch("products.outcomes.backend.api.calculate_outcome") as mock_task:
            response = self.client.post(f"/api/projects/{self.team.id}/outcomes/{outcome.id}/calculate")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        mock_task.delay.assert_not_called()

    def test_api_is_gated_on_the_feature_flag(self) -> None:
        self._create_outcome()
        with patch("products.outcomes.backend.api.outcomes_feature_enabled", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/outcomes")
        assert response.status_code == status.HTTP_403_FORBIDDEN
