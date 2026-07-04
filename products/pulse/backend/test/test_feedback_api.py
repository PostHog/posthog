import json
import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team
from posthog.models.user import User

from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief

_OTHER_VOTER_VOTE = {"helpful": True, "at": "2026-07-01T00:00:00+00:00"}


class TestPulseFeedbackAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        brief_report_patcher = patch("products.pulse.backend.api.brief.report_user_action")
        self.mock_brief_report = brief_report_patcher.start()
        self.addCleanup(brief_report_patcher.stop)
        opportunity_report_patcher = patch("products.pulse.backend.api.opportunity.report_user_action")
        self.mock_opportunity_report = opportunity_report_patcher.start()
        self.addCleanup(opportunity_report_patcher.stop)

    def _brief(self, team: Team | None = None, feedback: dict | None = None, **kwargs) -> ProductBrief:
        team = team or self.team
        return ProductBrief.objects.for_team(team.pk).create(
            team=team,
            status=ProductBrief.Status.READY,
            trigger=ProductBrief.Trigger.ON_DEMAND,
            feedback=feedback or {},
            **kwargs,
        )

    def _opportunity(self, team: Team | None = None, feedback: dict | None = None, **kwargs) -> Opportunity:
        team = team or self.team
        return Opportunity.objects.for_team(team.pk).create(
            team=team,
            kind=Opportunity.Kind.BUILD,
            title="Recover the signup drop",
            summary="s",
            fingerprint=f"build:{uuid.uuid4()}",
            feedback=feedback or {},
            **kwargs,
        )

    def _vote(self, resource: str, target_id: uuid.UUID, helpful: bool | None):
        return self.client.post(
            f"/api/projects/{self.team.id}/pulse/{resource}/{target_id}/feedback/", {"helpful": helpful}, format="json"
        )

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_vote_revote_clear_roundtrip(self, resource: str) -> None:
        target = self._brief() if resource == "briefs" else self._opportunity()

        response = self._vote(resource, target.id, True)
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["my_vote"] is True
        assert response.json()["helpful_count"] == 1
        assert response.json()["not_helpful_count"] == 0

        # Revote overwrites idempotently — one vote per user, never two.
        response = self._vote(resource, target.id, False)
        assert response.json()["my_vote"] is False
        assert response.json()["helpful_count"] == 0
        assert response.json()["not_helpful_count"] == 1

        # Null clears the vote entirely.
        response = self._vote(resource, target.id, None)
        assert response.json()["my_vote"] is None
        assert response.json()["helpful_count"] == 0
        assert response.json()["not_helpful_count"] == 0
        target.refresh_from_db()
        assert target.feedback == {"votes": {}}

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_counts_aggregate_other_votes_without_leaking_identities(self, resource: str) -> None:
        other_user = User.objects.create_and_join(self.organization, "voter@posthog.com", None)
        feedback = {"votes": {str(other_user.id): _OTHER_VOTER_VOTE}}
        target = self._brief(feedback=feedback) if resource == "briefs" else self._opportunity(feedback=feedback)

        response = self._vote(resource, target.id, True)

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        # Another user's earlier vote aggregates into the count but stays theirs, not mine.
        assert data["helpful_count"] == 2
        assert data["my_vote"] is True
        # The raw votes dict must never serialize (at any nesting level) — no voter identities
        # beyond counts cross the API. A bare user-id substring check would false-positive on
        # digits inside UUIDs and timestamps, so assert on the structure instead.
        assert '"votes"' not in json.dumps(data)
        assert "feedback" not in data

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_list_exposes_derived_vote_fields(self, resource: str) -> None:
        feedback = {"votes": {str(self.user.id): _OTHER_VOTER_VOTE}}
        target = self._brief(feedback=feedback) if resource == "briefs" else self._opportunity(feedback=feedback)

        response = self.client.get(f"/api/projects/{self.team.id}/pulse/{resource}/")

        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json()["results"] if row["id"] == str(target.id))
        assert row["my_vote"] is True
        assert row["helpful_count"] == 1
        assert "feedback" not in row

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_feedback_is_team_scoped(self, resource: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        target = self._brief(team=other_team) if resource == "briefs" else self._opportunity(team=other_team)

        response = self._vote(resource, target.id, True)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        target.refresh_from_db()
        assert target.feedback == {}

    @parameterized.expand(
        [
            ("missing_helpful", {}),
            ("non_boolean", {"helpful": "banana"}),
        ]
    )
    def test_invalid_payload_returns_400_without_voting(self, _name: str, payload: dict) -> None:
        opportunity = self._opportunity()

        response = self.client.post(
            f"/api/projects/{self.team.id}/pulse/opportunities/{opportunity.id}/feedback/", payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        opportunity.refresh_from_db()
        assert opportunity.feedback == {}

    def test_brief_feedback_capture_carries_context_props(self) -> None:
        config = BriefConfig.objects.for_team(self.team.pk).create(team=self.team, name="Focus", goal="Grow usage")
        brief = self._brief(
            config=config,
            sections=[{"kind": "what_happened", "title": "t"}, {"kind": "goal_progress", "title": "g"}],
            investigation=[{"question": "q", "hogql": "SELECT 1", "result_summary": "1", "succeeded": True}],
        )

        response = self._vote("briefs", brief.id, True)

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.mock_brief_report.assert_called_once()
        assert self.mock_brief_report.call_args.args[1] == "product_brief_feedback"
        assert self.mock_brief_report.call_args.args[2] == {
            "brief_id": str(brief.id),
            "helpful": True,
            "status": ProductBrief.Status.READY,
            "trigger": ProductBrief.Trigger.ON_DEMAND,
            "has_goal": True,
            "section_kinds": ["goal_progress", "what_happened"],
            "has_investigation": True,
        }

    def test_opportunity_feedback_capture_carries_context_props(self) -> None:
        opportunity = self._opportunity(
            goal_relevant=True,
            proposed_experiment={
                "hypothesis": "h",
                "flag_key_suggestion": "f",
                "target_metric": None,
                "variant_sketch": "v",
            },
        )

        response = self._vote("opportunities", opportunity.id, False)

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.mock_opportunity_report.assert_called_once()
        assert self.mock_opportunity_report.call_args.args[1] == "opportunity_feedback"
        assert self.mock_opportunity_report.call_args.args[2] == {
            "opportunity_id": str(opportunity.id),
            "helpful": False,
            "kind": Opportunity.Kind.BUILD,
            "status": Opportunity.Status.OPEN,
            "goal_relevant": True,
            "has_proposed_experiment": True,
        }
