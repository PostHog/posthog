import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.integration_resolver import routable_projects
from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES

WORKSPACE = "T_WS"
SLACK_USER = "U001"


class TestRoutableProjects:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        from django.core.cache import cache

        from products.slack_app.backend.services.slack_auth import write_auth_state_ok

        cache.clear()
        self.organization = Organization.objects.create(name="Org")
        self.other_organization = Organization.objects.create(name="Other org")
        self.default_team = Team.objects.create(organization=self.organization, name="Production")
        self.other_team = Team.objects.create(organization=self.organization, name="Staging")
        self.unreachable_team = Team.objects.create(organization=self.other_organization, name="Someone else")

        self.user = User.objects.create(email="dev@example.com", distinct_id="u-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.default = self._integration(self.default_team)
        self.other = self._integration(self.other_team)
        self.unreachable = self._integration(self.unreachable_team)
        # Seed every install as healthy so `load_integrations` short-circuits on a cache
        # hit rather than filtering the whole candidate list away on a failed `auth.test`,
        # which would make a broken rule look like a passing one.
        for candidate in (self.default, self.other, self.unreachable):
            write_auth_state_ok(candidate.id, bot_user_id="U_BOT")
        yield
        cache.clear()

    def _integration(self, team: Team, *, scopes: frozenset[str] = REQUIRED_SLACK_SCOPES) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"scope": ",".join(sorted(scopes))},
            sensitive_config={"access_token": "xoxb"},
        )

    def _routable(self):
        return routable_projects(slack_team_id=WORKSPACE, slack_user_id=SLACK_USER, user=self.user)

    def test_offers_every_project_the_mentioner_can_reach(self):
        offered = self._routable()
        assert {project.team_id for project in offered} == {self.default_team.id, self.other_team.id}
        assert {project.id for project in offered} == {self.default.id, self.other.id}

    @pytest.mark.parametrize(
        "reason",
        [
            "only_one_reachable_project",
            # Routing onto an install without the mention scopes would trade a working
            # run for one that cannot post its answer.
            "candidate_is_missing_scopes",
        ],
    )
    def test_routing_is_withheld(self, reason):
        if reason == "only_one_reachable_project":
            self.other.delete()
        if reason == "candidate_is_missing_scopes":
            self.other.config = {"scope": "chat:write"}
            self.other.save()

        assert self._routable() == []
