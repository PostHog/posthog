import json
import dataclasses

from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

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
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind


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


class TestEvidenceRef:
    def test_evidence_type_matches_resource_type(self) -> None:
        # EvidenceRef.resource_type / fk_field and persist's FK resolution all assume the two enums
        # share members. A new EvidenceType without a matching ResourceType would silently route its
        # evidence to the event fallback (no FK), so pin the sync here.
        assert {t.value for t in EvidenceType} == set(ResourceType.values)

    @parameterized.expand(
        [
            (EvidenceType.INSIGHT, ResourceType.INSIGHT, "insight"),
            (EvidenceType.DASHBOARD, ResourceType.DASHBOARD, "dashboard"),
            (EvidenceType.ANNOTATION, ResourceType.ANNOTATION, "annotation"),
            (EvidenceType.EXPERIMENT, ResourceType.EXPERIMENT, "experiment"),
            (EvidenceType.EVENT, ResourceType.EVENT, None),
        ]
    )
    def test_resource_type_and_fk_field(
        self, evidence_type: EvidenceType, expected_resource_type: ResourceType, expected_fk: str | None
    ) -> None:
        ref = EvidenceRef(type=evidence_type, ref="r", label="l")
        assert ref.resource_type == expected_resource_type
        assert ref.fk_field == expected_fk

    def test_key_and_metric_ref(self) -> None:
        insight = EvidenceRef(type=EvidenceType.INSIGHT, ref="abc", label="l")
        assert insight.key == (EvidenceType.INSIGHT, "abc")
        assert insight.metric_ref == {"insight_short_id": "abc"}
        assert EvidenceRef(type=EvidenceType.EVENT, ref="$pageview", label="l").metric_ref is None

    def test_type_coerced_from_string(self) -> None:
        # The plain string that survives the Temporal round-trip rebuilds back into the enum;
        # passing a str here is the behaviour under test, so the type mismatch is expected.
        assert EvidenceRef(type="insight", ref="abc", label="l").is_insight  # type: ignore[arg-type]

    def test_source_item_survives_asdict_json_roundtrip(self) -> None:
        # The gather activity returns dataclasses.asdict(item); synthesize rebuilds SourceItem(**item)
        # across a JSON boundary. The enum must serialize as a string and coerce back, and nested
        # EvidenceRef must rebuild — exactly what __post_init__ guards.
        item = SourceItem(
            source="anchored_insights",
            kind=SourceItemKind.MOVEMENT,
            title="t",
            description="d",
            metrics={"pct_change": -30.0},
            evidence=[EvidenceRef(type=EvidenceType.INSIGHT, ref="abc", label="l", url="/u")],
            fingerprint_hint="abc:0",
        )
        rebuilt = SourceItem(**json.loads(json.dumps(dataclasses.asdict(item))))
        assert isinstance(rebuilt.kind, SourceItemKind) and rebuilt.kind == SourceItemKind.MOVEMENT
        assert isinstance(rebuilt.evidence[0], EvidenceRef)
        assert rebuilt.evidence[0].key == (EvidenceType.INSIGHT, "abc")
