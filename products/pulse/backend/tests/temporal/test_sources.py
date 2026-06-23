from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync

from posthog.schema import PulseScanConfig

from products.pulse.backend.temporal.sources import (
    DeterministicSource,
    _adapt_anomaly_to_finding,
    _dedup_findings,
    gather_findings,
)
from products.pulse.backend.temporal.types import Finding, MetricDescriptor
from products.signals.backend.facade.api import AnomalyFinding

SOURCES = "products.pulse.backend.temporal.sources"
INSIGHT_OBJECTS = "products.product_analytics.backend.models.insight.Insight.objects"
RESOLVED_CONFIG = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)


def _anomaly(short_id="abc123", weight=0.86):
    return AnomalyFinding(
        insight_short_id=short_id,
        weight=weight,
        confidence=0.9,
        hypothesis="deploy regression",
        severity="P1",
        description="Signups dropped.",
        time_range=("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z"),
        finding_id="f1",
        scout_run_id="r1",
    )


class TestAdaptAnomalyToFinding:
    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    def test_none_when_no_short_id(self, mock_counter):
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly(short_id=None), RESOLVED_CONFIG)
        assert result is None
        mock_counter.assert_called_once_with("unresolvable_insight")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(INSIGHT_OBJECTS)
    def test_none_when_insight_missing(self, mock_objects, mock_counter):
        mock_objects.filter.return_value.first.return_value = None
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("missing"), RESOLVED_CONFIG)
        assert result is None
        mock_counter.assert_called_once_with("unresolvable_insight")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(INSIGHT_OBJECTS)
    def test_none_when_insight_not_trends_query(self, mock_objects, mock_counter):
        # A non-TrendsQuery insight (e.g. a funnel) can't be re-scored — count + skip, don't build.
        fake_insight = SimpleNamespace(
            id=1, name="Funnel", derived_name=None, short_id="abc123", query={"kind": "FunnelsQuery"}
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), RESOLVED_CONFIG)
        assert result is None
        mock_counter.assert_called_once_with("unsupported_query_kind")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(f"{SOURCES}.run_trends_query_sync", new_callable=AsyncMock)
    @patch(INSIGHT_OBJECTS)
    def test_none_when_trends_query_raises(self, mock_objects, mock_trends, mock_counter):
        # The most likely production failure: the re-score query itself raises (timeout, transient CH error).
        fake_insight = SimpleNamespace(
            id=1,
            name="Signups",
            derived_name=None,
            short_id="abc123",
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "signup", "math": "total"}]},
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        mock_trends.side_effect = RuntimeError("clickhouse timeout")
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), RESOLVED_CONFIG)
        assert result is None
        mock_counter.assert_called_once_with("query_failed")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(f"{SOURCES}.run_trends_query_sync", new_callable=AsyncMock)
    @patch(INSIGHT_OBJECTS)
    def test_unwraps_nested_source_query(self, mock_objects, mock_trends, mock_counter):
        # An InsightVizNode-wrapped query must unwrap to the inner TrendsQuery and still resolve.
        fake_insight = SimpleNamespace(
            id=1,
            name="Signups",
            derived_name=None,
            short_id="abc123",
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "signup", "math": "total"}],
                },
            },
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        mock_trends.return_value = {"results": [{"data": [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]}]}
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), RESOLVED_CONFIG)
        assert result is not None
        assert result.descriptor.query["kind"] == "TrendsQuery"  # unwrapped, not the InsightVizNode wrapper
        mock_counter.assert_called_once_with("resolved")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(f"{SOURCES}.run_trends_query_sync", new_callable=AsyncMock)
    @patch(INSIGHT_OBJECTS)
    def test_builds_finding_without_regating(self, mock_objects, mock_trends, mock_counter):
        # +5% move — BELOW the 25% gate — must STILL produce a Finding (scout already decided; no re-gate).
        fake_insight = SimpleNamespace(
            id=1,
            name="Signups",
            derived_name=None,
            short_id="abc123",
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "signup", "math": "total"}]},
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        mock_trends.return_value = {"results": [{"data": [100.0, 101.0, 99.0, 100.0, 105.0, 0.0]}]}
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), RESOLVED_CONFIG)
        assert result is not None
        assert result.descriptor.source == "scout_anomaly"
        assert result.descriptor.url == "/insights/abc123"
        assert result.current_value == 105.0
        assert round(result.change_pct, 3) == 0.05
        mock_counter.assert_called_once_with("resolved")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(f"{SOURCES}.run_trends_query_sync", new_callable=AsyncMock)
    @patch(INSIGHT_OBJECTS)
    def test_volume_floor_does_not_suppress_low_volume_anomaly(self, mock_objects, mock_trends, mock_counter):
        # baseline median 3 is below the config's min_baseline_value=5 — the deterministic gate would zero
        # this out, but the scout owns the surface decision so the adapter must still report the +100% move.
        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=5.0)
        fake_insight = SimpleNamespace(
            id=1,
            name="Niche",
            derived_name=None,
            short_id="abc123",
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "x", "math": "total"}]},
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        mock_trends.return_value = {"results": [{"data": [3.0, 3.0, 3.0, 3.0, 6.0, 0.0]}]}
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), config)
        assert result is not None
        assert round(result.change_pct, 3) == 1.0  # +100%, not suppressed to 0 by the volume floor
        mock_counter.assert_called_once_with("resolved")

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch(f"{SOURCES}.run_trends_query_sync", new_callable=AsyncMock)
    @patch(INSIGHT_OBJECTS)
    def test_zero_baseline_skipped_without_dividing(self, mock_objects, mock_trends, mock_counter):
        # A flat-zero baseline (0→N rise) has no defined % change — must skip cleanly, not raise ZeroDivisionError.
        fake_insight = SimpleNamespace(
            id=1,
            name="New metric",
            derived_name=None,
            short_id="abc123",
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "x", "math": "total"}]},
        )
        mock_objects.filter.return_value.first.return_value = fake_insight
        mock_trends.return_value = {"results": [{"data": [0.0, 0.0, 0.0, 0.0, 10.0, 0.0]}]}
        result = async_to_sync(_adapt_anomaly_to_finding)(MagicMock(id=1), _anomaly("abc123"), RESOLVED_CONFIG)
        assert result is None  # skipped, not crashed
        mock_counter.assert_called_once_with("zero_baseline")


class TestScoutAnomalySource:
    @patch("posthog.models.Team.objects")
    @patch(f"{SOURCES}._adapt_anomaly_to_finding", new_callable=AsyncMock)
    @patch("products.signals.backend.facade.api.get_team_anomalies", new_callable=AsyncMock)
    def test_maps_anomalies_dropping_unresolvable(self, mock_get_anomalies, mock_adapt, mock_team_objects):
        from products.pulse.backend.temporal.sources import (  # noqa: PLC0415 — imported after patches are installed
            ScoutAnomalySource,
        )

        team = MagicMock(id=7)
        mock_team_objects.get.return_value = team
        mock_get_anomalies.return_value = [_anomaly("resolves"), _anomaly(None)]
        sentinel = MagicMock()
        mock_adapt.side_effect = [sentinel, None]  # first anomaly resolves, second doesn't

        findings = async_to_sync(ScoutAnomalySource().get_findings)(
            7, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", RESOLVED_CONFIG
        )
        assert findings == [sentinel]  # the None is dropped
        assert mock_adapt.call_count == 2
        mock_get_anomalies.assert_awaited_once_with(team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert all(call.args[0] is team for call in mock_adapt.await_args_list)  # team threaded to each adapt

    @patch(f"{SOURCES}.increment_scout_anomaly_outcome")
    @patch("posthog.models.Team.objects")
    @patch(f"{SOURCES}._adapt_anomaly_to_finding", new_callable=AsyncMock)
    @patch("products.signals.backend.facade.api.get_team_anomalies", new_callable=AsyncMock)
    def test_one_raising_anomaly_does_not_abort_the_scan(
        self, mock_get_anomalies, mock_adapt, mock_team_objects, mock_counter
    ):
        from products.pulse.backend.temporal.sources import (  # noqa: PLC0415 — imported after patches are installed
            ScoutAnomalySource,
        )

        mock_team_objects.get.return_value = MagicMock(id=7)
        mock_get_anomalies.return_value = [_anomaly("boom"), _anomaly("ok")]
        sentinel = MagicMock()
        mock_adapt.side_effect = [RuntimeError("db down"), sentinel]  # first raises, second resolves

        findings = async_to_sync(ScoutAnomalySource().get_findings)(
            7, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", RESOLVED_CONFIG
        )
        assert findings == [sentinel]  # the raising anomaly is skipped, not fatal
        mock_counter.assert_called_once_with("adapter_error")

    @patch("posthog.models.Team.objects")
    @patch(f"{SOURCES}._adapt_anomaly_to_finding", new_callable=AsyncMock)
    @patch("products.signals.backend.facade.api.get_team_anomalies", new_callable=AsyncMock)
    def test_truncates_to_cap_keeping_highest_weight(self, mock_get_anomalies, mock_adapt, mock_team_objects):
        from products.pulse.backend.temporal.sources import (  # noqa: PLC0415 — imported after patches are installed
            MAX_ANOMALIES_PER_SCAN,
            ScoutAnomalySource,
        )

        mock_team_objects.get.return_value = MagicMock(id=7)
        # Ascending weights; only the top MAX_ANOMALIES_PER_SCAN should be re-scored, lowest dropped.
        mock_get_anomalies.return_value = [
            _anomaly(f"i{i}", weight=float(i)) for i in range(MAX_ANOMALIES_PER_SCAN + 5)
        ]
        mock_adapt.return_value = None

        async_to_sync(ScoutAnomalySource().get_findings)(
            7, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", RESOLVED_CONFIG
        )
        assert mock_adapt.await_count == MAX_ANOMALIES_PER_SCAN
        scored_weights = {call.args[1].weight for call in mock_adapt.await_args_list}
        assert min(scored_weights) == 5.0  # weights 0..4 (the 5 lowest) were dropped


def _finding(url: str | None, source: str) -> Finding:
    return Finding(
        descriptor=MetricDescriptor(source=source, source_id="1", label="x", query={"kind": "TrendsQuery"}, url=url),
        current_value=1.0,
        baseline_value=1.0,
        change_pct=0.0,
        impact=0.0,
        robust_z=0.0,
        series=[1.0],
    )


class TestDeterministicSource:
    @patch(f"{SOURCES}.detect_changes", new_callable=AsyncMock)
    @patch(f"{SOURCES}.select_candidates", new_callable=AsyncMock)
    def test_selects_then_detects(self, mock_select, mock_detect):
        candidates = [MagicMock()]
        findings = [_finding("/insights/a", "recent_insight")]
        mock_select.return_value = candidates
        mock_detect.return_value = findings
        result = async_to_sync(DeterministicSource().get_findings)(7, "s", "e", RESOLVED_CONFIG)
        assert result == findings
        mock_select.assert_awaited_once_with(7, RESOLVED_CONFIG)
        mock_detect.assert_awaited_once_with(7, candidates, RESOLVED_CONFIG)


class TestDedupFindings:
    def test_scout_wins_over_deterministic_for_same_insight(self):
        det = _finding("/insights/abc", "recent_insight")
        scout = _finding("/insights/abc", "scout_anomaly")
        for ordering in ([det, scout], [scout, det]):  # scout wins regardless of order
            out = _dedup_findings(ordering)
            assert len(out) == 1
            assert out[0].descriptor.source == "scout_anomaly"

    def test_distinct_insights_both_kept(self):
        out = _dedup_findings([_finding("/insights/a", "recent_insight"), _finding("/insights/b", "scout_anomaly")])
        assert {f.descriptor.url for f in out} == {"/insights/a", "/insights/b"}

    def test_urlless_findings_all_kept(self):
        # top-event metrics have no insight url — they can't collide, so none are deduped
        out = _dedup_findings([_finding(None, "top_event"), _finding(None, "top_event")])
        assert len(out) == 2


class TestGatherFindings:
    @staticmethod
    def _source(findings=None, raises=None):
        src = MagicMock()
        src.get_findings = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=findings or [])
        return src

    def test_merges_and_dedups_across_sources(self):
        det = self._source([_finding("/insights/abc", "recent_insight")])
        scout = self._source([_finding("/insights/abc", "scout_anomaly")])
        out = async_to_sync(gather_findings)(7, "s", "e", RESOLVED_CONFIG, sources=[det, scout])
        assert len(out) == 1
        assert out[0].descriptor.source == "scout_anomaly"  # same insight, scout preferred
        # args (incl. config) must thread through to every source intact
        det.get_findings.assert_awaited_once_with(7, "s", "e", RESOLVED_CONFIG)
        scout.get_findings.assert_awaited_once_with(7, "s", "e", RESOLVED_CONFIG)

    def test_one_failing_source_degrades_to_the_others(self):
        bad = self._source(raises=RuntimeError("boom"))
        good = self._source([_finding("/insights/a", "scout_anomaly")])
        out = async_to_sync(gather_findings)(7, "s", "e", RESOLVED_CONFIG, sources=[bad, good])
        assert [f.descriptor.url for f in out] == ["/insights/a"]  # bad source isolated, good survives
