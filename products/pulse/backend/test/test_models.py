from posthog.test.base import BaseTest

from posthog.models.scoping import team_scope

from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief


class TestPulseModels(BaseTest):
    def test_brief_config_and_brief_roundtrip(self) -> None:
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(
                team=self.team,
                name="Feature flags focus",
                focus_prompt="we're the feature flags team",
                anchors={"dashboards": [1], "insights": ["abc123"]},
                created_by=self.user,
            )
            brief = ProductBrief.objects.create(
                team=self.team,
                config=config,
                trigger=ProductBrief.Trigger.ON_DEMAND,
                period_days=7,
            )
        assert brief.status == ProductBrief.Status.GENERATING
        assert brief.sections == []

    def test_opportunity_defaults(self) -> None:
        with team_scope(self.team.pk, canonical=True):
            opp = Opportunity.objects.create(
                team=self.team,
                kind=Opportunity.Kind.BUILD,
                title="Fix mobile Safari signup drop",
                summary="Signup conversion dropped 12% on mobile Safari",
                fingerprint="abc123:trend:2026-06-25",
            )
        assert opp.status == Opportunity.Status.OPEN
        assert opp.evidence == []
