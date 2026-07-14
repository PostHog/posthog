from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertState

from products.alerts.backend.models import AlertConfiguration
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.generation.accountability import MAX_STATUS_LINES
from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.persist import _fingerprint, persist_brief_output
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut, ProposedExperimentOut
from products.pulse.backend.models import (
    ActionStatus,
    ActionType,
    Opportunity,
    ProductBrief,
    ResourceLink,
    ResourceType,
)
from products.pulse.backend.sources.anchored_insights import InsightResultsCache
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind

_EVIDENCE = EvidenceRef(type=EvidenceType.INSIGHT, ref="abc", label="Pageviews", url="/project/1/insights/abc")

_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}

_CALCULATE_PATH = "products.pulse.backend.sources.anchored_insights.calculate_for_query_based_insight"


def _proposed_experiment(target_short_id: str = "abc") -> ProposedExperimentOut:
    return ProposedExperimentOut(
        hypothesis="Moving the entry point above the fold lifts subscription creation",
        flag_key_suggestion="subscription-entry-point",
        target_metric_insight_short_id=target_short_id,
        variant_sketch="Control keeps the sidebar entry; test adds a button above the insights list.",
    )


def _out(
    fingerprint_hint: str = "abc:0",
    evidence_refs: list[str] | None = None,
    goal_relevant: bool = False,
    proposed_experiment: ProposedExperimentOut | None = None,
) -> BriefOut:
    refs = ["c1"] if evidence_refs is None else evidence_refs
    return BriefOut(
        sections=[BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["c1"], confidence=0.9)],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=refs,
                fingerprint_hint=fingerprint_hint,
                confidence=0.9,
                goal_relevant=goal_relevant,
                proposed_experiment=proposed_experiment,
            )
        ],
    )


def _item(fingerprint_hint: str = "abc:0") -> SourceItem:
    return SourceItem(
        source="anchored_insights",
        kind=SourceItemKind.MOVEMENT,
        title="Pageviews dropped 30%",
        description="d",
        metrics={"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0},
        evidence=[_EVIDENCE],
        fingerprint_hint=fingerprint_hint,
    )


class TestPersistBriefOutput(BaseTest):
    def _brief(self) -> ProductBrief:
        return ProductBrief.objects.for_team(self.team.pk).create(
            team=self.team, trigger=ProductBrief.Trigger.ON_DEMAND
        )

    def _opportunities(self):
        return Opportunity.objects.for_team(self.team.pk)

    def _links(self):
        return ResourceLink.objects.for_team(self.team.pk)

    def test_resolves_citation_ids_to_resource_links_and_action(self) -> None:
        # A real insight with the cited short_id so the link resolves its FK.
        with team_scope(self.team.pk, canonical=True):
            insight = Insight.objects.create(team=self.team, name="Pageviews", short_id="abc")
        brief = persist_brief_output(brief=self._brief(), out=_out(goal_relevant=True), items=[_item()])
        assert brief.status == ProductBrief.Status.READY
        assert len(brief.sections) == 1
        # Section citations resolve to structured refs the client renders directly — no id parsing.
        assert brief.sections[0]["citations"] == [_EVIDENCE.citation]
        assert brief.sources_used == ["anchored_insights"]
        opportunity = self._opportunities().get()
        assert opportunity.baseline == {"pct_change": -30.0, "baseline_total": 700.0, "current_total": 490.0}
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        assert opportunity.goal_relevant is True
        # The LLM summary is wrapped in the structured advisory action envelope.
        assert opportunity.action == {
            "type": ActionType.ADVISORY.value,
            "summary": "a",
            "params": {},
            "status": ActionStatus.PROPOSED.value,
        }
        # The cited id 'c1' resolves to a ResourceLink with the right type, cached columns, and FK.
        link = self._links().get()
        assert link.resource_type == ResourceType.INSIGHT
        assert link.ref == "abc"
        assert link.label == "Pageviews"
        assert link.url == "/project/1/insights/abc"
        assert link.insight_id == insight.id

    def test_link_created_even_when_insight_ref_does_not_resolve(self) -> None:
        # No insight with short_id 'abc' exists — the link is still created (cached columns only),
        # with a null FK, so a deleted/renamed resource does not drop the evidence.
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        link = self._links().get()
        assert link.resource_type == ResourceType.INSIGHT
        assert link.ref == "abc"
        assert link.insight_id is None

    def test_event_evidence_link_has_no_fk(self) -> None:
        # An event ref has no Django model, so _build_links takes the fk_field-is-None branch: the
        # link stores cached columns only (resource_type=event, every FK null).
        event_item = SourceItem(
            source="anchored_insights",
            kind=SourceItemKind.MOVEMENT,
            title="Signups from $pageview",
            description="d",
            metrics={},
            evidence=[EvidenceRef(type=EvidenceType.EVENT, ref="$pageview", label="Pageview", url="")],
            fingerprint_hint="evt:0",
        )
        persist_brief_output(brief=self._brief(), out=_out(fingerprint_hint="evt:0"), items=[event_item])
        link = self._links().get()
        assert link.resource_type == ResourceType.EVENT
        assert link.ref == "$pageview"
        assert link.label == "Pageview"
        assert link.insight_id is None
        assert link.dashboard_id is None

    def test_unknown_citation_id_creates_no_link(self) -> None:
        # The model cited an id that maps to no gathered evidence — it is dropped, not fabricated.
        persist_brief_output(brief=self._brief(), out=_out(evidence_refs=["c1", "c99"]), items=[_item()])
        assert self._opportunities().count() == 1
        assert [link.ref for link in self._links()] == ["abc"]

    @patch("products.pulse.backend.generation.persist._existing_fingerprints", return_value=set())
    def test_persist_survives_lost_fingerprint_race(self, _mock_seen: MagicMock) -> None:
        # A concurrent persist inserts the same (team, fingerprint) between our dedup read and our
        # bulk_create — simulated by forcing the dedup read empty while the winner row already exists.
        # Our in-memory opportunity's uuid is never inserted, so links must NOT be built against it
        # (that would violate the ResourceLink FK and abort the whole brief).
        with team_scope(self.team.pk, canonical=True):
            Insight.objects.create(team=self.team, name="Pageviews", short_id="abc")
            winner = Opportunity.objects.create(
                team=self.team,
                first_seen_brief=self._brief(),
                kind=Opportunity.Kind.BUILD,
                title="winner",
                summary="s",
                fingerprint=_fingerprint("build", "abc:0"),
            )
        brief = persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert brief.status == ProductBrief.Status.READY
        # Only the pre-existing winner survives; our phantom opportunity was never inserted, and no
        # links reference it.
        assert self._opportunities().count() == 1
        assert self._opportunities().get().id == winner.id
        assert self._links().count() == 0

    @patch(_CALCULATE_PATH)
    def test_goal_relevant_proposed_experiment_roundtrips_to_the_stored_shape(self, mock_calculate: MagicMock) -> None:
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment())
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment == {
            "hypothesis": "Moving the entry point above the fold lifts subscription creation",
            "flag_key_suggestion": "subscription-entry-point",
            "target_metric": {"insight_short_id": "abc"},
            "variant_sketch": "Control keeps the sidebar entry; test adds a button above the insights list.",
        }
        # The item resolved a metric of its own — promotion must not touch it or run an insight.
        assert opportunity.metric_ref == {"insight_short_id": "abc"}
        assert opportunity.baseline == _item().metrics
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_promotes_validated_target_metric_for_metricless_opportunity(self, mock_calculate: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        mock_calculate.return_value = MagicMock(result=[{"data": [1.0] * 7 + [2.0] * 7}])
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref == {"insight_short_id": insight.short_id}
        assert opportunity.baseline == {"current_total": 14.0, "period_days": 7}
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}

    @patch(_CALCULATE_PATH)
    def test_invented_target_metric_on_fallback_path_is_dropped_and_never_promoted(
        self, mock_calculate: MagicMock
    ) -> None:
        # No item resolved, so the LLM-authored evidence refs cite the invented id too — only
        # the server-side insight resolution can reject it.
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment("zzz9"),
            evidence_refs=["insight:zzz9"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment["target_metric"] is None
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_uncited_target_metric_on_item_path_is_dropped(self, mock_calculate: MagicMock) -> None:
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment("other1"))
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        opportunity = self._opportunities().get()
        assert opportunity.proposed_experiment["target_metric"] is None
        assert opportunity.metric_ref == {"insight_short_id": "abc"}  # the item's own metric is untouched
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("execution_raises", RuntimeError("clickhouse down")),
            ("non_trends_shape", [{"no": "data"}]),
            ("too_little_data", [{"data": [1.0]}]),
        ]
    )
    @patch(_CALCULATE_PATH)
    def test_promotion_degrades_all_or_nothing(
        self, _name: str, calculation: Exception | list, mock_calculate: MagicMock
    ) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        if isinstance(calculation, Exception):
            mock_calculate.side_effect = calculation
        else:
            mock_calculate.return_value = MagicMock(result=calculation)
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        # All-or-nothing: an unreadable snapshot must set NEITHER field, and never raise.
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}

    @patch(_CALCULATE_PATH)
    def test_promotion_skips_an_insight_deleted_after_gather(self, mock_calculate: MagicMock) -> None:
        # Item path: membership passes via the gathered evidence, but the insight row is gone by
        # persist time — the promotion's own resolution is what catches it.
        item = SourceItem(
            source="anchored_insights",
            kind="movement",
            title="t",
            description="d",
            metrics={"pct_change": -30.0},
            evidence=[
                {"type": "dashboard", "ref": "7", "label": "Home"},
                {"type": "insight", "ref": "abc", "label": ""},
            ],
            fingerprint_hint="abc:0",
        )
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment("abc"))
        persist_brief_output(brief=self._brief(), out=out, items=[item])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref is None
        assert opportunity.baseline == item.metrics
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": "abc"}
        mock_calculate.assert_not_called()

    @patch(_CALCULATE_PATH)
    def test_promotes_validated_target_on_item_that_resolved_no_metric_of_its_own(
        self, mock_calculate: MagicMock
    ) -> None:
        # Item path, but the item's own metric_ref is None because its first evidence is a
        # dashboard, not an insight. The proposal targets the item's insight evidence, which still
        # resolves, so promotion runs and overrides the None baseline — the combinatorial gap
        # between the fallback path (items=[]) and the metric-carrying item path.
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        mock_calculate.return_value = MagicMock(result=[{"data": [1.0] * 7 + [3.0] * 7}])
        item = SourceItem(
            source="anchored_insights",
            kind="movement",
            title="t",
            description="d",
            metrics={"pct_change": -30.0},
            evidence=[
                {"type": "dashboard", "ref": "7", "label": "Home"},
                {"type": "insight", "ref": insight.short_id, "label": "Subscriptions created"},
            ],
            fingerprint_hint="abc:0",
        )
        out = _out(goal_relevant=True, proposed_experiment=_proposed_experiment(insight.short_id))
        persist_brief_output(brief=self._brief(), out=out, items=[item])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref == {"insight_short_id": insight.short_id}
        assert opportunity.baseline == {"current_total": 21.0, "period_days": 7}
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}

    @patch(_CALCULATE_PATH)
    def test_promotion_respects_the_shared_execution_budget(self, mock_calculate: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        spent_cache = InsightResultsCache(self.team)
        spent_cache.attempts = MAX_STATUS_LINES
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[], results_cache=spent_cache)
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        mock_calculate.assert_not_called()

    @patch("products.pulse.backend.generation.persist._PROMOTION_BUDGET_SECONDS", -1)
    @patch(_CALCULATE_PATH)
    def test_promotion_skips_when_wall_clock_budget_exceeded(self, mock_calculate: MagicMock) -> None:
        # A promotion that would run past the cumulative wall-clock budget is skipped so a slow run
        # degrades to a metric_ref-less proposal instead of overrunning the activity timeout.
        insight = Insight.objects.create(team=self.team, name="Subscriptions created", query=_TRENDS_QUERY)
        out = _out(
            fingerprint_hint="unknown:9",
            goal_relevant=True,
            proposed_experiment=_proposed_experiment(insight.short_id),
            evidence_refs=[f"insight:{insight.short_id}"],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[])
        opportunity = self._opportunities().get()
        assert opportunity.metric_ref is None
        assert opportunity.baseline is None
        # The proposal is kept (validated), only the snapshot is skipped — and no insight ran.
        assert opportunity.proposed_experiment["target_metric"] == {"insight_short_id": insight.short_id}
        mock_calculate.assert_not_called()

    @parameterized.expand(
        [
            ("not_goal_relevant", False, _proposed_experiment()),
            ("no_proposal", True, None),
        ]
    )
    def test_proposed_experiment_is_nulled_unless_goal_relevant(
        self, _name: str, goal_relevant: bool, proposed: ProposedExperimentOut | None
    ) -> None:
        out = _out(goal_relevant=goal_relevant, proposed_experiment=proposed)
        persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        assert self._opportunities().get().proposed_experiment is None

    def test_same_fingerprint_does_not_duplicate(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1

    def test_dismissed_fingerprint_is_suppressed(self) -> None:
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        self._opportunities().update(status=Opportunity.Status.DISMISSED)
        persist_brief_output(brief=self._brief(), out=_out(), items=[_item()])
        assert self._opportunities().count() == 1

    def test_empty_output_marks_quiet(self) -> None:
        brief = persist_brief_output(brief=self._brief(), out=BriefOut(sections=[], opportunities=[]), items=[])
        assert brief.status == ProductBrief.Status.QUIET
        assert brief.sources_used == []

    def test_opportunity_only_output_marks_ready(self) -> None:
        out = BriefOut(sections=[], opportunities=_out().opportunities)
        brief = persist_brief_output(brief=self._brief(), out=out, items=[_item()])
        assert brief.status == ProductBrief.Status.READY

    def test_alert_and_subscription_refs_resolve_to_typed_links(self) -> None:
        # Alerts (UUID pk) and subscriptions (int pk) are first-class evidence types with their own
        # FKs; a "fix" opportunity citing both must persist links with each FK resolved.
        with team_scope(self.team.pk, canonical=True):
            insight = Insight.objects.create(team=self.team, name="Signups")
            alert = AlertConfiguration.objects.create(
                team=self.team, insight=insight, name="a", state=AlertState.ERRORED, enabled=True
            )
            subscription = Subscription.objects.create(
                team=self.team,
                title="s",
                target_type="email",
                target_value="x@y.com",
                frequency="weekly",
                start_date=timezone.now() - timedelta(days=1),
            )
        item = SourceItem(
            source="resource_health",
            kind=SourceItemKind.HEALTH,
            title="t",
            description="d",
            evidence=[
                EvidenceRef(type=EvidenceType.ALERT, ref=str(alert.id), label="a", url=""),
                EvidenceRef(type=EvidenceType.SUBSCRIPTION, ref=str(subscription.id), label="s", url=""),
            ],
            fingerprint_hint="alert:x",
        )
        out = BriefOut(
            sections=[],
            opportunities=[
                OpportunityOut(
                    kind="fix",
                    title="t",
                    summary="s",
                    suggested_action="a",
                    evidence_refs=["c1", "c2"],
                    fingerprint_hint="alert:x",
                    confidence=0.9,
                    goal_relevant=False,
                )
            ],
        )
        persist_brief_output(brief=self._brief(), out=out, items=[item])
        links = {link.resource_type: link for link in self._links()}
        assert links[ResourceType.ALERT].alert_id == alert.id
        assert links[ResourceType.SUBSCRIPTION].subscription_id == subscription.id

    def test_persists_goal_status_snapshot(self) -> None:
        brief = self._brief()
        goal_status = GoalStatus(
            goal="grow signups",
            metric_state="ok",
            insight_short_id="abc",
            metric_label="Signups",
            current_rate="4.2/day avg",
            previous_rate="3.0/day avg",
            delta_pct=40.0,
        )
        persist_brief_output(brief=brief, out=_out(), items=[_item()], goal_status=goal_status)
        brief.refresh_from_db()
        assert brief.goal_status == {
            "goal": "grow signups",
            "metric_state": "ok",
            "insight_short_id": "abc",
            "metric_label": "Signups",
            "current_rate": "4.2/day avg",
            "previous_rate": "3.0/day avg",
            "delta_pct": 40.0,
        }

    def test_no_goal_status_persists_null(self) -> None:
        brief = self._brief()
        persist_brief_output(brief=brief, out=_out(), items=[_item()])
        brief.refresh_from_db()
        assert brief.goal_status is None
