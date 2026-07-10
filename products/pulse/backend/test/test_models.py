from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from posthog.models.scoping import team_scope

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.models import (
    ActionStatus,
    ActionType,
    BriefConfig,
    Opportunity,
    ProductBrief,
    ResourceLink,
    ResourceType,
)


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
        # A fresh opportunity carries the default proposed-advisory action envelope.
        assert opp.action == {
            "type": ActionType.ADVISORY.value,
            "summary": "",
            "params": {},
            "status": ActionStatus.PROPOSED.value,
        }

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

    def _opportunity(self) -> Opportunity:
        brief = ProductBrief.objects.create(team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND)
        return Opportunity.objects.create(
            team=self.team,
            first_seen_brief=brief,
            kind=Opportunity.Kind.BUILD,
            title="t",
            summary="s",
            fingerprint="fp-link",
        )

    def test_resource_link_survives_insight_delete_via_set_null(self) -> None:
        # Evidence history must outlive the cited resource: deleting the insight nulls the FK but
        # keeps the link and its cached ref/label so the opportunity still shows what it cited.
        with team_scope(self.team.pk, canonical=True):
            insight = Insight.objects.create(team=self.team, name="Pageviews")
            opportunity = self._opportunity()
            link = ResourceLink.objects.create(
                team=self.team,
                opportunity=opportunity,
                insight=insight,
                resource_type=ResourceType.INSIGHT,
                ref=insight.short_id,
                label="Pageviews",
                url=f"/project/{self.team.id}/insights/{insight.short_id}",
            )
        insight.delete()
        link.refresh_from_db()
        assert link.insight_id is None
        assert link.resource_type == ResourceType.INSIGHT
        assert link.ref == insight.short_id
        assert link.label == "Pageviews"

    def test_resource_link_clean_rejects_type_without_matching_fk(self) -> None:
        # A DB-modeled resource_type must carry its FK at write time (clean), even though the DB
        # itself can't enforce it (SET_NULL would break a hard constraint).
        with team_scope(self.team.pk, canonical=True):
            opportunity = self._opportunity()
            link = ResourceLink(
                team=self.team,
                opportunity=opportunity,
                resource_type=ResourceType.INSIGHT,
                ref="abc",
                label="l",
            )
        with self.assertRaises(ValidationError):
            link.clean()

    def test_resource_link_clean_allows_event_without_fk(self) -> None:
        # Events have no Django model, so an event link legitimately carries no FK.
        with team_scope(self.team.pk, canonical=True):
            opportunity = self._opportunity()
            link = ResourceLink(
                team=self.team,
                opportunity=opportunity,
                resource_type=ResourceType.EVENT,
                ref="$pageview",
                label="$pageview",
            )
            link.clean()  # must not raise
