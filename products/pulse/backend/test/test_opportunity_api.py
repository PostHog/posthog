import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.pulse.backend.models import Opportunity

_TRANSITION_EVENTS = {
    "dismiss": "opportunity_dismissed",
    "acted": "opportunity_acted",
    "reopen": "opportunity_reopened",
}


class TestOpportunityAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self.mock_flag = patcher.start()
        self.addCleanup(patcher.stop)
        report_patcher = patch("products.pulse.backend.api.opportunity.report_user_action")
        self.mock_report = report_patcher.start()
        self.addCleanup(report_patcher.stop)

    def _opportunity(
        self,
        opportunity_status: str = Opportunity.Status.OPEN,
        kind: str = Opportunity.Kind.BUILD,
        team: Team | None = None,
    ) -> Opportunity:
        team = team or self.team
        return Opportunity.objects.for_team(team.pk).create(
            team=team,
            kind=kind,
            status=opportunity_status,
            title="Recover the signup drop",
            summary="s",
            fingerprint=f"{kind}:{uuid.uuid4()}",
            goal_relevant=True,
        )

    def test_list_requires_flag(self) -> None:
        self.mock_flag.return_value = False
        response = self.client.get(f"/api/projects/{self.team.id}/pulse/opportunities/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("dismiss_open", "dismiss", Opportunity.Status.OPEN, status.HTTP_200_OK, Opportunity.Status.DISMISSED),
            ("acted_open", "acted", Opportunity.Status.OPEN, status.HTTP_200_OK, Opportunity.Status.ACTED),
            ("reopen_dismissed", "reopen", Opportunity.Status.DISMISSED, status.HTTP_200_OK, Opportunity.Status.OPEN),
            ("dismiss_dismissed", "dismiss", Opportunity.Status.DISMISSED, status.HTTP_400_BAD_REQUEST, None),
            ("dismiss_acted", "dismiss", Opportunity.Status.ACTED, status.HTTP_400_BAD_REQUEST, None),
            ("acted_resolved", "acted", Opportunity.Status.RESOLVED, status.HTTP_400_BAD_REQUEST, None),
            ("reopen_open", "reopen", Opportunity.Status.OPEN, status.HTTP_400_BAD_REQUEST, None),
            ("reopen_acted", "reopen", Opportunity.Status.ACTED, status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    def test_status_transitions(
        self,
        _name: str,
        transition: str,
        initial_status: str,
        expected_code: int,
        expected_status: str | None,
    ) -> None:
        opportunity = self._opportunity(opportunity_status=initial_status)

        response = self.client.post(f"/api/projects/{self.team.id}/pulse/opportunities/{opportunity.id}/{transition}/")

        assert response.status_code == expected_code, response.json()
        opportunity.refresh_from_db()
        if expected_status is not None:
            assert response.json()["status"] == expected_status
            assert opportunity.status == expected_status
            self.mock_report.assert_called_once()
            assert self.mock_report.call_args.args[1] == _TRANSITION_EVENTS[transition]
            assert self.mock_report.call_args.args[2]["status"] == expected_status
            assert self.mock_report.call_args.args[2]["goal_relevant"] is True
        else:
            assert opportunity.status == initial_status
            assert "This opportunity is" in response.json()["detail"]
            self.mock_report.assert_not_called()

    @parameterized.expand(
        [
            ("by_status", {"status": "dismissed"}, ["dismissed-build"]),
            ("by_kind", {"kind": "fix"}, ["open-fix"]),
            ("by_both", {"status": "open", "kind": "build"}, ["open-build"]),
            ("unfiltered", {}, ["dismissed-build", "open-build", "open-fix"]),
        ]
    )
    def test_list_filters(self, _name: str, params: dict[str, str], expected: list[str]) -> None:
        fixtures = {
            "open-build": (Opportunity.Status.OPEN, Opportunity.Kind.BUILD),
            "open-fix": (Opportunity.Status.OPEN, Opportunity.Kind.FIX),
            "dismissed-build": (Opportunity.Status.DISMISSED, Opportunity.Kind.BUILD),
        }
        by_id = {
            str(self._opportunity(opportunity_status=fixture_status, kind=kind).id): name
            for name, (fixture_status, kind) in fixtures.items()
        }

        response = self.client.get(f"/api/projects/{self.team.id}/pulse/opportunities/", params)

        assert response.status_code == status.HTTP_200_OK
        assert sorted(by_id[row["id"]] for row in response.json()["results"]) == sorted(expected)

    def test_list_serializes_proposed_experiment_and_null_alike(self) -> None:
        proposed = {
            "hypothesis": "h",
            "flag_key_suggestion": "entry-point",
            "target_metric": {"insight_short_id": "abc"},
            "variant_sketch": "v",
        }
        with_proposal = self._opportunity()
        Opportunity.objects.for_team(self.team.pk).filter(pk=with_proposal.pk).update(proposed_experiment=proposed)
        without_proposal = self._opportunity()

        response = self.client.get(f"/api/projects/{self.team.id}/pulse/opportunities/")

        assert response.status_code == status.HTTP_200_OK
        by_id = {row["id"]: row["proposed_experiment"] for row in response.json()["results"]}
        assert by_id[str(with_proposal.id)] == proposed
        assert by_id[str(without_proposal.id)] is None

    @parameterized.expand([("status", "bogus"), ("kind", "bogus")])
    def test_invalid_filter_value_returns_400(self, field: str, value: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/pulse/opportunities/", {field: value})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Must be one of" in str(response.json())

    def test_opportunities_are_team_scoped(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        mine = self._opportunity()
        other = self._opportunity(team=other_team)

        list_response = self.client.get(f"/api/projects/{self.team.id}/pulse/opportunities/")
        assert [row["id"] for row in list_response.json()["results"]] == [str(mine.id)]

        # A transition on another team's opportunity must 404, not mutate it.
        response = self.client.post(f"/api/projects/{self.team.id}/pulse/opportunities/{other.id}/dismiss/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other.refresh_from_db()
        assert other.status == Opportunity.Status.OPEN
