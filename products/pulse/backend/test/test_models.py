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
            )
        assert brief.status == ProductBrief.Status.GENERATING
        assert brief.sections == []
        assert brief.period == {"type": "last_n_days", "days": 7}

    def test_opportunity_defaults(self) -> None:
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND)
            opp = Opportunity.objects.create(
                team=self.team,
                first_seen_brief=brief,
                kind=Opportunity.Kind.BUILD,
                title="Fix mobile Safari signup drop",
                summary="Signup conversion dropped 12% on mobile Safari",
                fingerprint="abc123:trend:2026-06-25",
            )
        assert opp.status == Opportunity.Status.OPEN
        assert opp.evidence == []

    def test_hard_deleting_brief_cascades_to_opportunities(self) -> None:
        with team_scope(self.team.pk, canonical=True):
            brief = ProductBrief.objects.create(team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND)
            Opportunity.objects.create(
                team=self.team,
                first_seen_brief=brief,
                kind=Opportunity.Kind.BUILD,
                title="t",
                summary="s",
                fingerprint="fp1",
            )
        brief.delete()
        assert Opportunity.objects.for_team(self.team.pk).count() == 0

    def test_hard_deleting_config_cascades_to_briefs(self) -> None:
        with team_scope(self.team.pk, canonical=True):
            config = BriefConfig.objects.create(team=self.team, name="Focus")
            ProductBrief.objects.create(team=self.team, config=config, trigger=ProductBrief.Trigger.ON_DEMAND)
        config.delete()
        assert ProductBrief.objects.for_team(self.team.pk).count() == 0
