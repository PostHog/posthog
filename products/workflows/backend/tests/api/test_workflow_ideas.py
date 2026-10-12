from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.workflows.backend.facade.contracts import NewWorkflowIdea
from products.workflows.backend.facade.workflow_ideas import create_ideas
from products.workflows.backend.models import HogFlow, WorkflowIdea


def _idea(key: str, *, priority: int | None = None, value_tier: str = "activation") -> NewWorkflowIdea:
    evidence: dict = {
        "trigger_event": "trial started",
        "goal_events": ["plan purchased"],
        "baseline_rate": 0.2,
        "reachable_people": 120,
        "measured_at": "2026-01-05",
    }
    if priority is not None:
        evidence["priority"] = priority
    return NewWorkflowIdea(
        key=key,
        title=f"Idea {key}",
        rationale="People who start a trial rarely buy a plan in the first week.",
        value_tier=value_tier,
        definition={"actions": [], "edges": []},
        evidence=evidence,
    )


def _stored(idea_id: UUID) -> WorkflowIdea:
    return WorkflowIdea.objects.unscoped().get(id=idea_id)


class TestWorkflowIdeasAPI(APIBaseTest):
    def _url(self, suffix: str = "", team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/workflow_ideas/{suffix}"

    def _flow(self, *, team: Team | None = None, origin_product: str | None = "ideas") -> HogFlow:
        return HogFlow.objects.create(team=team or self.team, name="Drafted", origin_product=origin_product)

    def test_list_orders_by_priority_then_tier_and_hides_other_projects(self):
        create_ideas(
            team_id=self.team.id,
            items=[
                _idea("engagement", value_tier="engagement"),
                _idea("revenue", value_tier="revenue"),
                _idea("first", priority=1, value_tier="retention"),
            ],
            source="manual",
        )
        other_team = Team.objects.create(organization=self.organization, name="Other")
        create_ideas(team_id=other_team.id, items=[_idea("elsewhere")], source="manual")

        response = self.client.get(self._url())

        assert response.status_code == 200, response.json()
        assert [row["key"] for row in response.json()["results"]] == ["first", "revenue", "engagement"]

    def test_a_dismissed_key_is_never_suggested_again(self):
        [row] = create_ideas(team_id=self.team.id, items=[_idea("winback")], source="manual")
        response = self.client.post(self._url(f"{row.id}/dismiss/"), {"reason": "We send this already"})
        assert response.status_code == 200, response.json()

        assert create_ideas(team_id=self.team.id, items=[_idea("winback")], source="manual") == []
        assert self.client.get(self._url()).json()["results"] == []
        stored_row = _stored(row.id)
        assert (stored_row.status, stored_row.dismiss_reason) == (WorkflowIdea.Status.DISMISSED, "We send this already")

    def test_accept_links_the_draft_and_closes_the_idea(self):
        [row] = create_ideas(team_id=self.team.id, items=[_idea("winback")], source="manual")
        flow = self._flow()

        response = self.client.post(
            self._url(f"{row.id}/accept/"), {"hog_flow_id": str(flow.id), "site_url": "https://shop.example.com"}
        )

        assert response.status_code == 200, response.json()
        assert response.json()["hog_flow_id"] == str(flow.id)
        stored_row = _stored(row.id)
        assert (
            stored_row.status,
            stored_row.hog_flow_id,
            stored_row.resolved_by_id,
            stored_row.evidence["site_url"],
        ) == (
            WorkflowIdea.Status.ACCEPTED,
            flow.id,
            self.user.id,
            "https://shop.example.com",
        )
        again = self.client.post(self._url(f"{row.id}/accept/"), {"hog_flow_id": str(flow.id)})
        assert again.status_code == 409

    @parameterized.expand([("draft", True), ("active", False), ("archived", False)])
    @patch("products.workflows.backend.presentation.views.workflow_ideas.people_reached_since", return_value=37)
    def test_a_used_idea_stays_listed_while_its_workflow_is_a_draft(
        self, status: str, listed: bool, _mock_reach
    ) -> None:
        [used, _waiting] = create_ideas(
            team_id=self.team.id, items=[_idea("used", priority=5), _idea("waiting", priority=1)], source="manual"
        )
        flow = self._flow()
        self.client.post(self._url(f"{used.id}/accept/"), {"hog_flow_id": str(flow.id)})
        HogFlow.objects.filter(id=flow.id).update(status=status)

        results = self.client.get(self._url()).json()["results"]

        if listed:
            assert [(r["key"], r["hog_flow_status"], r["reached_since_used"]) for r in results] == [
                ("used", "draft", 37),
                ("waiting", None, None),
            ]
        else:
            assert [r["key"] for r in results] == ["waiting"]

    @parameterized.expand(
        [("another project's workflow", "other_team"), ("a workflow not made from an idea", "manual")]
    )
    def test_accept_refuses(self, _name: str, case: str):
        [row] = create_ideas(team_id=self.team.id, items=[_idea("winback")], source="manual")
        if case == "other_team":
            flow = self._flow(team=Team.objects.create(organization=self.organization, name="Other"))
        else:
            flow = self._flow(origin_product=None)

        response = self.client.post(self._url(f"{row.id}/accept/"), {"hog_flow_id": str(flow.id)})

        assert response.status_code == 400, response.json()
        stored_row = _stored(row.id)
        assert stored_row.status == WorkflowIdea.Status.SUGGESTED

    @parameterized.expand([("accept",), ("dismiss",)])
    def test_another_projects_idea_is_not_found(self, action: str):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        [row] = create_ideas(team_id=other_team.id, items=[_idea("winback")], source="manual")

        response = self.client.post(self._url(f"{row.id}/{action}/"), {"hog_flow_id": str(self._flow().id)})
        malformed = self.client.post(self._url(f"not-an-id/{action}/"), {"hog_flow_id": str(self._flow().id)})

        assert (response.status_code, malformed.status_code) == (404, 404)
        stored_row = _stored(row.id)
        assert stored_row.status == WorkflowIdea.Status.SUGGESTED

    def test_viewed_stamps_only_this_projects_ideas_once(self):
        [own] = create_ideas(team_id=self.team.id, items=[_idea("own")], source="manual")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        [other] = create_ideas(team_id=other_team.id, items=[_idea("other")], source="manual")

        response = self.client.post(self._url("viewed/"), {"ids": [str(own.id), str(other.id)]}, format="json")
        assert response.status_code == 204
        stored_own = _stored(own.id)
        first_seen = stored_own.first_viewed_at
        self.client.post(self._url("viewed/"), {"ids": [str(own.id)]}, format="json")

        stored_own = _stored(own.id)
        stored_other = _stored(other.id)
        assert first_seen is not None and stored_own.first_viewed_at == first_seen
        assert stored_other.first_viewed_at is None
