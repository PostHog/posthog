from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode, TeamFeatureFlagsConfig


class TestAuditFlagEvaluationsMode(BaseTest):
    def _run(self) -> str:
        out = StringIO()
        call_command("audit_flag_evaluations_mode", stdout=out)
        return out.getvalue()

    def test_lists_mixed_organizations_and_counts_a_team_without_a_row_as_events(self) -> None:
        TeamFeatureFlagsConfig.objects.filter(team=self.team).update(
            flag_evaluations_mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )
        legacy_team = Team.objects.create(organization=self.organization, name="Legacy")
        TeamFeatureFlagsConfig.objects.filter(team=legacy_team).delete()
        uniform_organization = Organization.objects.create(name="Uniform")
        Team.objects.create(organization=uniform_organization, name="First")
        Team.objects.create(organization=uniform_organization, name="Second")

        output = self._run()

        self.assertIn(f"organization {self.organization.id}: mode 0: 1 team(s), mode 1: 1 team(s)", output)
        self.assertNotIn(str(uniform_organization.id), output)
