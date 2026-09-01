import json
import datetime as dt
from datetime import UTC, datetime

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend.logs_url_params import build_pattern_logs_url_params
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent, LogsAlertSeenPattern
from products.logs.backend.pattern_alert_check_query import (
    GroupedPatternCheckQuery,
    PatternGroupCount,
    PatternGroupsResult,
    StampingProbeResult,
)
from products.logs.backend.pattern_alert_evaluator import (
    LAST_SEEN_REFRESH_MIN_AGE,
    PatternAlertCheckError,
    evaluate_pattern_alert,
    pattern_alert_fingerprint,
)
from products.logs.backend.temporal.activities import _cohort_manifests_from_alerts
from products.logs.backend.test.test_alert_check_query import _log_row
from products.logs.backend.test.test_logs_alerting_activities import _evaluate_and_save_one, _make_stats

NOW = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)


def _group(service: str = "api", pattern: str = "Error in Foo.bar", version: int = 3, count: int = 1):
    return PatternGroupCount(service_name=service, pattern=pattern, pattern_version=version, occurrences=count)


def _mock_query(mock_query_cls, results: list[PatternGroupsResult], *, probe: tuple[int, int] = (0, 0)):
    instance = mock_query_cls.return_value
    instance.execute_groups.side_effect = results
    instance.execute_stamping_probe.return_value = StampingProbeResult(
        total=probe[0], stamped=probe[1], query_duration_ms=1
    )
    return instance


def _groups_result(*groups: PatternGroupCount, truncated: bool = False) -> PatternGroupsResult:
    return PatternGroupsResult(groups=list(groups), truncated=truncated, query_duration_ms=1)


class TestPatternAlertFingerprint(unittest.TestCase):
    def test_fingerprint_is_a_stable_persisted_contract(self):
        # Fingerprints live in Postgres seen-sets: changing the digest input shape
        # silently invalidates every existing set, so the exact value is pinned.
        assert pattern_alert_fingerprint("api", "Error in <num>", 3) == "e8e3289dda18cbdd4b14f03468295601"

    @parameterized.expand(
        [
            ("service", ("worker", "Error in <num>", 3)),
            ("pattern", ("api", "Error out <num>", 3)),
            ("version", ("api", "Error in <num>", 4)),
        ]
    )
    def test_fingerprint_distinguishes_each_component(self, _name, other):
        assert pattern_alert_fingerprint("api", "Error in <num>", 3) != pattern_alert_fingerprint(*other)


class TestBuildPatternLogsUrlParams(unittest.TestCase):
    def test_scopes_to_service_and_pattern_and_keeps_existing_filters(self):
        existing_group = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": "env", "value": "prod", "operator": "exact", "type": "log_attribute"}],
                }
            ],
        }
        params = build_pattern_logs_url_params(
            {"severityLevels": ["error"], "serviceNames": ["api", "worker"], "filterGroup": existing_group},
            service_name="api",
            pattern="Error in Foo.bar",
            date_from=NOW - dt.timedelta(minutes=5),
            date_to=NOW,
        )
        assert "serviceNames=%5B%22api%22%5D" in params
        assert "Error+in+Foo.bar" in params or "Error%20in%20Foo.bar" in params
        assert "env" in params
        assert "dateRange" in params


class TestCohortManifestsSplitByTrigger(unittest.TestCase):
    def test_pattern_and_count_alerts_never_share_a_cohort(self):
        # A mixed cohort would run pattern alerts through the batched countIf
        # query and evaluate them as count triggers.
        base = {
            "team_id": 1,
            "window_minutes": 5,
            "evaluation_periods": 1,
            "check_interval_minutes": 5,
            "filters": {},
            "next_check_at": NOW,
            "schedule_restriction": None,
        }
        rows = [
            {**base, "id": "a1", "trigger_type": "count"},
            {**base, "id": "a2", "trigger_type": "new_pattern"},
        ]
        manifests = _cohort_manifests_from_alerts(rows, now=NOW, checkpoint=None)
        assert sorted(len(m.alert_ids) for m in manifests) == [1, 1]


@patch("products.logs.backend.pattern_alert_evaluator.GroupedPatternCheckQuery")
class TestEvaluatePatternAlert(APIBaseTest):
    def _make_alert(self, trigger_type: str, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Pattern Alert",
            "trigger_type": trigger_type,
            "threshold_count": 1,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"severityLevels": ["error"]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _seen(self, alert: LogsAlertConfiguration, group: PatternGroupCount, *, last_seen_at: datetime | None = None):
        return LogsAlertSeenPattern.objects.for_team(self.team.id).create(
            team=self.team,
            alert=alert,
            fingerprint=pattern_alert_fingerprint(group.service_name, group.pattern, group.pattern_version),
            service_name=group.service_name,
            pattern=group.pattern,
            pattern_version=group.pattern_version,
            last_seen_at=last_seen_at or NOW,
        )

    def test_first_check_seeds_without_alerting(self, mock_query_cls):
        alert = self._make_alert("new_pattern")
        _mock_query(mock_query_cls, [_groups_result(_group(count=50), _group(pattern="Boom in Baz.qux"))])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.seeded is True
        assert outcome.threshold_breached is False
        assert len(outcome.staged_new) == 2
        # Seed window is days, not the check window.
        call = mock_query_cls.call_args.kwargs
        assert call["date_to"] - call["date_from"] == dt.timedelta(days=7)

    def test_new_fingerprint_breaches_and_known_one_does_not(self, mock_query_cls):
        alert = self._make_alert("new_pattern")
        known = _group()
        novel = _group(service="worker", pattern="Panic in Delayed.handler", count=3)
        self._seen(alert, known)
        _mock_query(mock_query_cls, [_groups_result(known, novel)])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is True
        assert [g.pattern for g in outcome.breaching] == [novel.pattern]
        assert [s.pattern for s in outcome.staged_new] == [novel.pattern]

    def test_same_pattern_in_a_different_service_is_a_new_fingerprint(self, mock_query_cls):
        # A rollup pattern like "Error in <*>" spans services, so it must not
        # suppress the first occurrence in a service not seen before.
        alert = self._make_alert("new_pattern")
        known = _group(service="api")
        other_service = _group(service="worker")
        self._seen(alert, known)
        _mock_query(mock_query_cls, [_groups_result(known, other_service)])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is True
        assert outcome.breaching[0].service_name == "worker"

    def test_below_floor_novel_fingerprint_is_staged_but_does_not_breach(self, mock_query_cls):
        alert = self._make_alert("new_pattern", threshold_count=5)
        self._seen(alert, _group())
        novel = _group(pattern="Rare in One.off", count=2)
        _mock_query(mock_query_cls, [_groups_result(novel)])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is False
        assert [s.pattern for s in outcome.staged_new] == [novel.pattern]

    def test_pattern_version_bump_stages_silently(self, mock_query_cls):
        alert = self._make_alert("new_pattern")
        self._seen(alert, _group(version=3))
        reminted = _group(pattern="Error in Foo.bar!", version=4, count=10)
        _mock_query(mock_query_cls, [_groups_result(reminted)])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is False
        assert [s.pattern_version for s in outcome.staged_new] == [4]

    def test_stale_seen_fingerprints_are_marked_for_refresh(self, mock_query_cls):
        alert = self._make_alert("new_pattern")
        stale = _group()
        fresh = _group(pattern="Other in Two.three")
        self._seen(alert, stale, last_seen_at=NOW - LAST_SEEN_REFRESH_MIN_AGE)
        self._seen(alert, fresh, last_seen_at=NOW)
        _mock_query(mock_query_cls, [_groups_result(stale, fresh)])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.refresh_fingerprints == (
            pattern_alert_fingerprint(stale.service_name, stale.pattern, stale.pattern_version),
        )

    def test_truncated_groups_raise_actionable_error(self, mock_query_cls):
        alert = self._make_alert("pattern_threshold")
        _mock_query(mock_query_cls, [_groups_result(_group(), truncated=True)])

        with self.assertRaises(PatternAlertCheckError) as ctx:
            evaluate_pattern_alert(alert, date_to=NOW, now=NOW)
        assert "Narrow the filters" in ctx.exception.user_message
        assert ctx.exception.is_transient is False

    def test_unstamped_logs_raise_actionable_error(self, mock_query_cls):
        alert = self._make_alert("pattern_threshold")
        _mock_query(mock_query_cls, [_groups_result()], probe=(100, 0))

        with self.assertRaises(PatternAlertCheckError) as ctx:
            evaluate_pattern_alert(alert, date_to=NOW, now=NOW)
        assert "stamping" in ctx.exception.user_message

    def test_no_matching_logs_is_a_quiet_ok_check(self, mock_query_cls):
        alert = self._make_alert("pattern_threshold")
        _mock_query(mock_query_cls, [_groups_result()], probe=(0, 0))

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is False
        assert outcome.result_count == 0

    def test_seen_set_cap_raises_actionable_error(self, mock_query_cls):
        alert = self._make_alert("new_pattern")
        self._seen(alert, _group())
        _mock_query(mock_query_cls, [_groups_result(_group(pattern="Fresh in Cap.blow"))])

        with patch("products.logs.backend.pattern_alert_evaluator.MAX_SEEN_PATTERNS_PER_ALERT", 1):
            with self.assertRaises(PatternAlertCheckError) as ctx:
                evaluate_pattern_alert(alert, date_to=NOW, now=NOW)
        assert "distinct patterns" in ctx.exception.user_message

    @parameterized.expand([("breaches", 10, True), ("stays_quiet", 9, False)])
    def test_pattern_threshold_compares_per_fingerprint_occurrences(self, mock_query_cls, _name, count, should_fire):
        alert = self._make_alert("pattern_threshold", threshold_count=10)
        _mock_query(mock_query_cls, [_groups_result(_group(count=count))])

        outcome = evaluate_pattern_alert(alert, date_to=NOW, now=NOW)

        assert outcome.threshold_breached is should_fire
        assert outcome.staged_new == ()


@freeze_time("2025-01-01T00:01:00Z")
@patch("products.logs.backend.pattern_alert_evaluator.GroupedPatternCheckQuery")
@patch("products.alerts.backend.destinations.produce_internal_event")
class TestPatternAlertPipeline(APIBaseTest):
    """End-to-end through eval -> dispatch -> save: the wiring existing count-trigger
    tests can't cover -- pattern payloads on the fired event and the seen-set's
    commit-only-after-delivery contract."""

    def setUp(self):
        super().setUp()
        for target in (
            "products.logs.backend.temporal.activities.record_check_duration",
            "products.logs.backend.temporal.activities.record_scheduler_lag",
            "products.logs.backend.temporal.activities.record_clickhouse_duration",
            "products.logs.backend.temporal.activities.record_cohort_save_duration",
            "products.logs.backend.temporal.activities.record_cohort_event_insert_duration",
            "products.logs.backend.temporal.activities.record_cohort_update_duration",
            "products.logs.backend.temporal.activities.increment_checks_total",
            "products.logs.backend.temporal.activities.increment_check_errors",
        ):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "New pattern alert",
            "trigger_type": "new_pattern",
            "threshold_count": 1,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"severityLevels": ["error"], "serviceNames": ["api"]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def test_seed_then_new_fingerprint_fires_with_pattern_payload(self, mock_produce, mock_query_cls):
        alert = self._make_alert()
        seeded = _group(count=4)
        novel = _group(service="api", pattern="Panic in Checkout.pay", count=2)
        _mock_query(mock_query_cls, [_groups_result(seeded), _groups_result(seeded, novel)])

        _evaluate_and_save_one(alert, NOW, _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert not mock_produce.called
        assert LogsAlertSeenPattern.objects.for_team(self.team.id).filter(alert=alert).count() == 1

        alert.next_check_at = None
        stats = _make_stats()
        _evaluate_and_save_one(alert, NOW + dt.timedelta(minutes=5), stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["fired"] == 1
        props = mock_produce.call_args.kwargs["event"].properties
        assert props["trigger_type"] == "new_pattern"
        assert props["pattern_count"] == 1
        assert props["patterns"][0]["pattern"] == "Panic in Checkout.pay"
        assert "pattern" in props["patterns"][0]["logs_url_params"]
        assert LogsAlertSeenPattern.objects.for_team(self.team.id).filter(alert=alert).count() == 2

    def test_failed_notification_keeps_fingerprints_new_for_retry(self, mock_produce, mock_query_cls):
        # Seed emits nothing, so the first produce call is check 2's FIRE (fails
        # at enqueue), the second is check 3's retried FIRE (succeeds).
        mock_produce.side_effect = [Exception("kafka down"), unittest.mock.DEFAULT]
        alert = self._make_alert()
        novel = _group(pattern="Panic in Checkout.pay", count=2)
        _mock_query(
            mock_query_cls,
            [_groups_result(_group()), _groups_result(novel), _groups_result(novel)],
        )

        _evaluate_and_save_one(alert, NOW, _make_stats())  # seed

        alert.next_check_at = None
        _evaluate_and_save_one(alert, NOW + dt.timedelta(minutes=5), _make_stats())
        alert.refresh_from_db()
        # Enqueue failed: state rolled back, fingerprint NOT committed.
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert (
            LogsAlertSeenPattern.objects.for_team(self.team.id).filter(alert=alert, pattern=novel.pattern).count() == 0
        )

        alert.next_check_at = None
        stats = _make_stats()
        _evaluate_and_save_one(alert, NOW + dt.timedelta(minutes=10), stats)
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["fired"] == 1
        assert (
            LogsAlertSeenPattern.objects.for_team(self.team.id).filter(alert=alert, pattern=novel.pattern).count() == 1
        )

    def test_check_error_writes_actionable_event_row(self, _mock_produce, mock_query_cls):
        alert = self._make_alert(trigger_type="pattern_threshold", threshold_count=10)
        instance = mock_query_cls.return_value
        instance.execute_groups.return_value = _groups_result(_group(), truncated=True)

        _evaluate_and_save_one(alert, NOW, _make_stats())

        event = LogsAlertEvent.objects.get(alert=alert)
        assert event.error_message is not None
        assert "Narrow the filters" in event.error_message


class TestGroupedPatternCheckQueryClickhouse(ClickhouseTestMixin, APIBaseTest):
    """Real-ClickHouse guard: the grouped HogQL query must resolve the `pattern`
    column, group per (service, pattern), and exclude unstamped rows."""

    def _insert(self, rows: list[dict]) -> None:
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))

    def test_groups_by_service_and_pattern_excluding_unstamped(self):
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        ts = (base + dt.timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        rows = []
        for idx, (service, pattern) in enumerate(
            [("api", "Error in Foo.bar"), ("api", "Error in Foo.bar"), ("worker", "Error in Foo.bar"), ("api", "")]
        ):
            row = _log_row(self.team.pk, f"0194ff00-0000-0000-0000-00000000000{idx}", ts, service, severity="error")
            row["pattern"] = pattern
            row["pattern_version"] = 3 if pattern else 0
            rows.append(row)
        self._insert(rows)

        alert = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="pattern query",
            trigger_type="pattern_threshold",
            filters={"severityLevels": ["error"]},
        )
        result = GroupedPatternCheckQuery(
            team=self.team,
            alert=alert,
            date_from=base,
            date_to=base + dt.timedelta(minutes=5),
        ).execute_groups()

        assert result.truncated is False
        assert [(g.service_name, g.pattern, g.occurrences) for g in result.groups] == [
            ("api", "Error in Foo.bar", 2),
            ("worker", "Error in Foo.bar", 1),
        ]

    def test_truncation_flag_set_past_limit(self):
        base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        ts = (base + dt.timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        rows = []
        for idx in range(3):
            row = _log_row(self.team.pk, f"0194ff00-0000-0000-0000-00000000001{idx}", ts, "api", severity="error")
            row["pattern"] = f"Error in Distinct.callsite{idx}"
            row["pattern_version"] = 3
            rows.append(row)
        self._insert(rows)

        alert = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="pattern query",
            trigger_type="pattern_threshold",
            filters={"severityLevels": ["error"]},
        )
        result = GroupedPatternCheckQuery(
            team=self.team,
            alert=alert,
            date_from=base,
            date_to=base + dt.timedelta(minutes=5),
        ).execute_groups(limit=2)

        assert result.truncated is True
        assert len(result.groups) == 2
