import json
import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team
from posthog.models.user import User

from products.pulse.backend.models import BriefConfig, FeedbackVote, Opportunity, ProductBrief


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

    def _brief(self, team: Team | None = None, **kwargs) -> ProductBrief:
        team = team or self.team
        return ProductBrief.objects.for_team(team.pk).create(
            team=team,
            status=ProductBrief.Status.READY,
            trigger=ProductBrief.Trigger.ON_DEMAND,
            **kwargs,
        )

    def _opportunity(self, team: Team | None = None, **kwargs) -> Opportunity:
        team = team or self.team
        brief = ProductBrief.objects.for_team(team.pk).create(team=team, trigger=ProductBrief.Trigger.ON_DEMAND)
        return Opportunity.objects.for_team(team.pk).create(
            team=team,
            first_seen_brief=brief,
            kind=Opportunity.Kind.BUILD,
            title="Recover the signup drop",
            summary="s",
            fingerprint=f"build:{uuid.uuid4()}",
            **kwargs,
        )

    def _target(self, resource: str, **kwargs):
        return self._brief(**kwargs) if resource == "briefs" else self._opportunity(**kwargs)

    def _seed_vote(self, resource: str, target, user: User, *, helpful: bool, reason: str = "") -> FeedbackVote:
        field = "brief" if resource == "briefs" else "opportunity"
        return FeedbackVote.objects.for_team(self.team.pk).create(
            team=self.team, created_by=user, helpful=helpful, reason=reason, **{field: target}
        )

    def _my_votes(self, resource: str, target):
        field = "brief" if resource == "briefs" else "opportunity"
        return FeedbackVote.objects.for_team(self.team.pk).filter(**{field: target}, created_by=self.user)

    def _vote(self, resource: str, target_id: uuid.UUID, helpful: bool | None, reason: str | None = None):
        payload: dict = {"helpful": helpful}
        if reason is not None:
            payload["reason"] = reason
        return self.client.post(
            f"/api/projects/{self.team.id}/pulse/{resource}/{target_id}/feedback/", payload, format="json"
        )

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_vote_revote_clear_roundtrip(self, resource: str) -> None:
        target = self._target(resource)

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
        assert self._my_votes(resource, target).count() == 1

        # Null clears the vote entirely — the row is gone.
        response = self._vote(resource, target.id, None)
        assert response.json()["my_vote"] is None
        assert response.json()["helpful_count"] == 0
        assert response.json()["not_helpful_count"] == 0
        assert not self._my_votes(resource, target).exists()

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_reason_roundtrip(self, resource: str) -> None:
        target = self._target(resource)

        response = self._vote(resource, target.id, True, reason="clear and actionable")
        assert response.json()["my_reason"] == "clear and actionable"

        # Revoting updates the stored reason.
        response = self._vote(resource, target.id, False, reason="changed my mind")
        assert response.json()["my_vote"] is False
        assert response.json()["my_reason"] == "changed my mind"

        # Clearing the vote drops the reason with it.
        response = self._vote(resource, target.id, None)
        assert response.json()["my_reason"] is None

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_counts_aggregate_without_leaking_other_voters(self, resource: str) -> None:
        other_user = User.objects.create_and_join(self.organization, "voter@posthog.com", None)
        target = self._target(resource)
        self._seed_vote(resource, target, other_user, helpful=True, reason="secret reason from another user")

        response = self._vote(resource, target.id, True, reason="my own reason")

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        # Another user's vote aggregates into the count, but neither their identity nor their reason
        # crosses the API — only my own vote and reason come back.
        assert data["helpful_count"] == 2
        assert data["my_vote"] is True
        assert data["my_reason"] == "my own reason"
        # Only aggregate counts and my own vote/reason serialize — another voter's reason never does.
        # (No raw user-id substring check: small ids false-positive on digits in UUIDs/timestamps.)
        assert "secret reason from another user" not in json.dumps(data)
        assert "feedback" not in data

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_list_exposes_derived_vote_fields(self, resource: str) -> None:
        target = self._target(resource)
        self._seed_vote(resource, target, self.user, helpful=True, reason="mine")

        response = self.client.get(f"/api/projects/{self.team.id}/pulse/{resource}/")

        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json()["results"] if row["id"] == str(target.id))
        assert row["my_vote"] is True
        assert row["my_reason"] == "mine"
        assert row["helpful_count"] == 1
        assert "feedback" not in row

    @parameterized.expand([("briefs",), ("opportunities",)])
    def test_feedback_is_team_scoped(self, resource: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        target = self._target(resource, team=other_team)

        response = self._vote(resource, target.id, True)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        field = "brief" if resource == "briefs" else "opportunity"
        assert not FeedbackVote.all_teams.filter(**{field: target}).exists()

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
        assert not FeedbackVote.objects.for_team(self.team.pk).filter(opportunity=opportunity).exists()

    def test_brief_feedback_capture_carries_context_props(self) -> None:
        config = BriefConfig.objects.for_team(self.team.pk).create(team=self.team, name="Focus", goal="Grow usage")
        brief = self._brief(
            config=config,
            sections=[
                {"kind": "what_happened", "title": "t", "markdown": "m", "citations": [], "confidence": 0.9},
                {"kind": "goal_progress", "title": "g", "markdown": "m", "citations": [], "confidence": 0.9},
            ],
        )

        response = self._vote("briefs", brief.id, True, reason="the goal section nailed it")

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.mock_brief_report.assert_called_once()
        assert self.mock_brief_report.call_args.args[1] == "product_brief_feedback"
        assert self.mock_brief_report.call_args.args[2] == {
            "brief_id": str(brief.id),
            "helpful": True,
            "has_reason": True,
            "status": ProductBrief.Status.READY,
            "trigger": ProductBrief.Trigger.ON_DEMAND,
            "has_goal": True,
            "section_kinds": ["goal_progress", "what_happened"],
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
            "has_reason": False,
            "kind": Opportunity.Kind.BUILD,
            "status": Opportunity.Status.OPEN,
            "goal_relevant": True,
            "has_proposed_experiment": True,
        }
