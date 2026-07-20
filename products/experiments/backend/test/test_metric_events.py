import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models import Team

from products.actions.backend.models.action import Action
from products.experiments.backend.metric_events import resolve_metric_events, scan_sessions_for_metric_events
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag

WINDOW_START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)


def _events_node(event: Optional[str], properties: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    node: dict[str, Any] = {"kind": "EventsNode", "event": event}
    if properties is not None:
        node["properties"] = properties
    return node


def _dw_node() -> dict[str, Any]:
    return {
        "kind": "ExperimentDataWarehouseNode",
        "table_name": "stripe_charges",
        "timestamp_field": "created_at",
        "data_warehouse_join_key": "customer_id",
        "events_join_key": "distinct_id",
    }


def _metric(metric_type: str, name: Optional[str] = "Metric", **type_fields: Any) -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": metric_type,
        "uuid": str(uuid.uuid4()),
        "name": name,
        **type_fields,
    }


def _retention_metric(start_event: dict[str, Any], completion_event: dict[str, Any]) -> dict[str, Any]:
    return _metric(
        "retention",
        start_event=start_event,
        completion_event=completion_event,
        retention_window_start=0,
        retention_window_end=7,
        retention_window_unit="day",
        start_handling="first_seen",
    )


class MetricEventsTestMixin(BaseTest):
    def _experiment(self, metrics: Optional[list[dict[str, Any]]] = None, **kwargs: Any) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=f"flag-{uuid.uuid4().hex[:8]}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            metrics=metrics or [],
            **kwargs,
        )


class TestResolveMetricEvents(MetricEventsTestMixin):
    @parameterized.expand(
        [
            ("mean", _metric("mean", source=_events_node("purchase")), ("purchase",)),
            (
                "funnel",
                _metric("funnel", series=[_events_node("added to cart"), _events_node("purchase")]),
                ("added to cart", "purchase"),
            ),
            (
                "ratio",
                _metric("ratio", numerator=_events_node("purchase"), denominator=_events_node("$pageview")),
                ("purchase", "$pageview"),
            ),
            (
                "retention",
                _retention_metric(_events_node("signed up"), _events_node("uploaded file")),
                ("signed up", "uploaded file"),
            ),
        ]
    )
    def test_resolves_event_sources_per_metric_type(
        self, _name: str, metric: dict[str, Any], expected_events: tuple[str, ...]
    ) -> None:
        experiment = self._experiment(metrics=[metric])

        sources = resolve_metric_events(experiment)

        assert len(sources) == 1
        assert sources[0].metric_uuid == metric["uuid"]
        assert sources[0].event_names == expected_events
        assert sources[0].session_linkable is True
        assert sources[0].matches_all_events is False
        assert sources[0].action_ids == ()

    def test_resolves_action_source_to_action_id(self) -> None:
        action = Action.objects.create(team=self.team, name="Purchased", steps_json=[{"event": "purchase"}])
        experiment = self._experiment(
            metrics=[_metric("mean", source={"kind": "ActionsNode", "id": action.pk})],
        )

        sources = resolve_metric_events(experiment)

        assert len(sources) == 1
        assert sources[0].action_ids == (action.pk,)
        assert sources[0].event_names == ()
        assert sources[0].session_linkable is True

    def test_data_warehouse_only_metric_is_not_session_linkable(self) -> None:
        experiment = self._experiment(
            metrics=[
                _metric("mean", source=_dw_node()),
                _metric("ratio", numerator=_events_node("purchase"), denominator=_dw_node()),
            ]
        )

        dw_only, mixed = resolve_metric_events(experiment)

        assert dw_only.session_linkable is False
        assert dw_only.event_names == ()
        assert mixed.session_linkable is True
        assert mixed.event_names == ("purchase",)

    def test_all_events_source_sets_matches_all_events(self) -> None:
        experiment = self._experiment(metrics=[_metric("mean", source=_events_node(None))])

        sources = resolve_metric_events(experiment)

        assert sources[0].matches_all_events is True
        assert sources[0].event_names == ()
        assert sources[0].session_linkable is True

    def test_includes_secondary_and_saved_metrics(self) -> None:
        primary = _metric("mean", source=_events_node("purchase"))
        secondary = _metric("mean", source=_events_node("refund"))
        saved_query = _metric("mean", source=_events_node("upgraded"))
        experiment = self._experiment(metrics=[primary], metrics_secondary=[secondary])
        saved = ExperimentSavedMetric.objects.create(team=self.team, name="saved", query=saved_query)
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved, metadata={})

        sources = resolve_metric_events(experiment)

        assert [source.metric_uuid for source in sources] == [
            primary["uuid"],
            secondary["uuid"],
            saved_query["uuid"],
        ]

    def test_unparseable_metric_is_skipped_not_fatal(self) -> None:
        valid = _metric("mean", source=_events_node("purchase"))
        experiment = self._experiment(
            metrics=[
                {"uuid": str(uuid.uuid4()), "metric_type": "trends"},  # legacy type unknown to build_metric
                {"uuid": str(uuid.uuid4()), "metric_type": "mean", "source": {"kind": "EventsNode", "bogus": 1}},
                valid,
            ]
        )

        sources = resolve_metric_events(experiment)

        assert [source.metric_uuid for source in sources] == [valid["uuid"]]


class TestScanSessionsForMetricEvents(ClickhouseTestMixin, MetricEventsTestMixin):
    def _create_session_event(
        self,
        event: str,
        session_id: str,
        timestamp: str = "2026-01-01T10:05:00Z",
        properties: Optional[dict[str, Any]] = None,
        team: Optional[Team] = None,
    ) -> None:
        _create_event(
            team=team or self.team,
            event=event,
            distinct_id="user1",
            timestamp=timestamp,
            properties={"$session_id": session_id, **(properties or {})},
        )

    def _scan(self, metrics: list[dict[str, Any]], session_ids: list[str]) -> dict[str, Any]:
        experiment = self._experiment(metrics=metrics)
        return scan_sessions_for_metric_events(
            self.team,
            self.user,
            metric_sources=resolve_metric_events(experiment),
            session_ids=session_ids,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )

    def test_reports_hits_only_for_metrics_and_sessions_with_events(self) -> None:
        # Two metrics force a genuine multi-branch UNION ALL — a single branch collapses to a
        # plain SelectQuery, so only this shape proves per-branch limits and no set-level LIMIT
        # compile together (a set-level LIMIT after the last branch 500ed session_context once).
        metric_a = _metric("mean", name="Purchases", source=_events_node("purchase"))
        metric_b = _metric("mean", name="Signups", source=_events_node("signup"))
        self._create_session_event("purchase", "s1", timestamp="2026-01-01T10:05:00Z")
        self._create_session_event("purchase", "s1", timestamp="2026-01-01T10:10:00Z")
        self._create_session_event("purchase", "s2", timestamp="2026-01-01T12:30:00Z")  # outside window
        flush_persons_and_events()

        hits = self._scan([metric_a, metric_b], ["s1", "s2"])

        assert set(hits) == {"s1"}
        assert len(hits["s1"]) == 1
        hit = hits["s1"][0]
        assert hit.metric_uuid == metric_a["uuid"]
        assert hit.metric_name == "Purchases"
        assert hit.event_count == 2
        assert hit.first_timestamp == datetime(2026, 1, 1, 10, 5, 0, tzinfo=UTC)

    def test_honors_source_node_property_filters(self) -> None:
        filtered = _metric(
            "mean",
            name="Premium purchases",
            source=_events_node(
                "purchase", properties=[{"key": "plan", "value": ["premium"], "operator": "exact", "type": "event"}]
            ),
        )
        unfiltered = _metric("mean", name="Purchases", source=_events_node("purchase"))
        self._create_session_event("purchase", "s1", properties={"plan": "free"})
        flush_persons_and_events()

        hits = self._scan([filtered, unfiltered], ["s1"])

        assert [hit.metric_uuid for hit in hits["s1"]] == [unfiltered["uuid"]]

    def test_all_events_source_matches_any_event(self) -> None:
        all_events = _metric("mean", name="Anything", source=_events_node(None))
        purchases = _metric("mean", name="Purchases", source=_events_node("purchase"))
        self._create_session_event("$pageview", "s1")
        flush_persons_and_events()

        hits = self._scan([all_events, purchases], ["s1"])

        assert [hit.metric_uuid for hit in hits["s1"]] == [all_events["uuid"]]

    def test_team_isolation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        metric_a = _metric("mean", source=_events_node("purchase"))
        metric_b = _metric("mean", source=_events_node("signup"))
        self._create_session_event("purchase", "s1", team=other_team)
        flush_persons_and_events()

        hits = self._scan([metric_a, metric_b], ["s1"])

        assert hits == {}

    def test_missing_action_matches_nothing(self) -> None:
        broken = _metric("mean", name="Broken", source={"kind": "ActionsNode", "id": 999_999})
        purchases = _metric("mean", name="Purchases", source=_events_node("purchase"))
        self._create_session_event("purchase", "s1")
        flush_persons_and_events()

        hits = self._scan([broken, purchases], ["s1"])

        assert [hit.metric_uuid for hit in hits["s1"]] == [purchases["uuid"]]
