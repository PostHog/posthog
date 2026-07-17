from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.skills.backend.management.commands.backfill_llm_skill_access_control import Command

from ee.models import Role
from ee.models.rbac.access_control import AccessControl


class TestBackfillLlmSkillAccessControl(BaseTest):
    def _run_backfill(self, *, team_id=None, live_run=True):
        Command().handle(live_run=live_run, team_id=team_id)

    def _skill_rows(self, team_id: int) -> list[AccessControl]:
        return list(AccessControl.objects.filter(team_id=team_id, resource="llm_skill"))

    @parameterized.expand(
        [
            ("team_wide_default", None, None),
            ("member_scoped", "organization_member", None),
            ("role_scoped", None, "role"),
        ]
    )
    def test_backfill_mirrors_llm_analytics_row_shape(self, _label, member_attr, role_attr):
        membership = self.organization_membership if member_attr else None
        role = Role.objects.create(name="oncall", organization=self.organization) if role_attr else None
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=membership,
            role=role,
        )

        self._run_backfill(team_id=self.team.pk)

        rows = self._skill_rows(self.team.pk)
        assert len(rows) == 1
        assert rows[0].access_level == "viewer"
        assert rows[0].organization_member_id == (membership.id if membership else None)
        assert rows[0].role_id == (role.id if role else None)

    def test_dry_run_does_not_write(self):
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="none")

        self._run_backfill(team_id=self.team.pk, live_run=False)

        assert self._skill_rows(self.team.pk) == []

    def test_covers_teams_that_never_used_skills(self):
        # llm_skill is also review_hog's scope_object (blind spots/perspectives/validators config) -
        # a team that only uses that, and never created an LLMSkill, must still be covered.
        review_hog_only_team = Team.objects.create(organization=self.organization, name="review_hog only")
        AccessControl.objects.create(
            team=review_hog_only_team, resource="llm_analytics", resource_id=None, access_level="none"
        )

        self._run_backfill()

        rows = self._skill_rows(review_hog_only_team.pk)
        assert len(rows) == 1
        assert rows[0].access_level == "none"

    def test_skips_teams_with_no_llm_analytics_access_controls(self):
        untouched_team = Team.objects.create(organization=self.organization, name="Never configured RBAC")

        self._run_backfill()

        assert self._skill_rows(untouched_team.pk) == []

    def test_rerun_is_idempotent(self):
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="none")

        self._run_backfill(team_id=self.team.pk)
        self._run_backfill(team_id=self.team.pk)

        rows = self._skill_rows(self.team.pk)
        assert len(rows) == 1
        assert rows[0].access_level == "none"

    def test_team_id_scopes_to_one_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="none")
        AccessControl.objects.create(team=other_team, resource="llm_analytics", resource_id=None, access_level="none")

        self._run_backfill(team_id=self.team.pk)

        assert len(self._skill_rows(self.team.pk)) == 1
        assert self._skill_rows(other_team.pk) == []
