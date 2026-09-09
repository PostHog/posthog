from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.repo_routing_rule import RepoRoutingRule

from products.tasks.backend.presentation.views.repo_routing_rules_api import RepoRoutingRuleSerializer


class TestRepoRoutingRuleSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_slash", "posthog"),
            ("extra_segment", "a/b/c"),
            ("space_in_repo", "posthog/my repo"),
            ("empty_owner", "/repo"),
            ("empty_repo", "posthog/"),
        ]
    )
    def test_rejects_malformed_repository(self, _name: str, repository: str) -> None:
        serializer = RepoRoutingRuleSerializer(data={"rule_text": "dashboards", "repository": repository})
        assert not serializer.is_valid()
        assert "repository" in serializer.errors

    def test_rejects_overlong_rule_text(self) -> None:
        serializer = RepoRoutingRuleSerializer(data={"rule_text": "x" * 301, "repository": "posthog/posthog"})
        assert not serializer.is_valid()
        assert "rule_text" in serializer.errors


class TestRepoRoutingRulesAPI(APIBaseTest):
    def _url(self, rule_id=None) -> str:
        base = f"/api/projects/{self.team.id}/tasks/repo_routing_rules/"
        return f"{base}{rule_id}/" if rule_id else base

    def test_create_appends_priority_and_sets_created_by(self):
        RepoRoutingRule.objects.create(team=self.team, rule_text="existing", repository="posthog/posthog", priority=4)
        response = self.client.post(self._url(), {"rule_text": "docs and website", "repository": "PostHog/posthog.com"})
        assert response.status_code == status.HTTP_201_CREATED
        rule = RepoRoutingRule.objects.get(id=response.json()["id"])
        assert rule.team == self.team
        assert rule.created_by == self.user
        assert rule.priority == 5
        assert rule.repository == "PostHog/posthog.com"

    def test_create_rejects_overlong_rule_text(self):
        response = self.client.post(self._url(), {"rule_text": "x" * 301, "repository": "posthog/posthog"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "rule_text"
        assert RepoRoutingRule.objects.count() == 0

    def test_list_is_team_scoped_and_priority_ordered(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        RepoRoutingRule.objects.create(team=other_team, rule_text="other", repository="acme/other", priority=0)
        second = RepoRoutingRule.objects.create(team=self.team, rule_text="b", repository="posthog/b", priority=2)
        first = RepoRoutingRule.objects.create(team=self.team, rule_text="a", repository="posthog/a", priority=1)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.json()] == [str(first.id), str(second.id)]

    def test_detail_actions_cannot_reach_another_teams_rule(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        rule = RepoRoutingRule.objects.create(team=other_team, rule_text="other", repository="acme/other")
        assert self.client.patch(self._url(rule.id), {"rule_text": "hijack"}).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.delete(self._url(rule.id)).status_code == status.HTTP_404_NOT_FOUND
        rule.refresh_from_db()
        assert rule.rule_text == "other"

    def test_patch_edits_text_and_repo_but_not_priority(self):
        rule = RepoRoutingRule.objects.create(team=self.team, rule_text="old", repository="posthog/old", priority=3)
        response = self.client.patch(
            self._url(rule.id), {"rule_text": "new", "repository": "posthog/new", "priority": 0}
        )
        assert response.status_code == status.HTTP_200_OK
        rule.refresh_from_db()
        assert (rule.rule_text, rule.repository, rule.priority) == ("new", "posthog/new", 3)

    def test_delete_removes_rule(self):
        rule = RepoRoutingRule.objects.create(team=self.team, rule_text="temp", repository="posthog/temp")
        assert self.client.delete(self._url(rule.id)).status_code == status.HTTP_204_NO_CONTENT
        assert not RepoRoutingRule.objects.filter(id=rule.id).exists()
