# Sweeps the alert-filter config space through the hoisted batched query.
#
# Customers author these configs, so the input space is theirs, not ours:
# hand-picked cases cover the shapes we thought of, and the ILLEGAL_COLUMN
# incident came from a combination nobody picked (body filter + resource
# attribute filter + a scan selecting zero parts). These sweeps enumerate the
# space instead: every operator the filter builder supports (single leaves),
# every pair and triple of expression *shapes* (indexHint, attribute map,
# fingerprint IN/NOT IN subqueries, nested groups), each on both seeded data
# and an empty scan. The property throughout is per-alert equivalence: the
# batched hoisted query must return exactly what `AlertCheckQuery` returns,
# and must not error where it doesn't.
import os
import json
import random
import datetime as dt
import itertools
from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend.alert_check_query import AlertCheckQuery, BatchedAlertCheckQuery
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.test.test_alert_check_query import _log_row

NCA = datetime(2026, 3, 5, 10, 5, 0, tzinfo=UTC)
DATE_FROM = NCA - dt.timedelta(minutes=15)

SERVICE = "sweep_payments_api"
OTHER_SERVICE = "sweep_background_jobs"

BODY_NEEDLE = "export failed"
BODY_EXACT = "task_crashed"
ATTR_KEY = "job_kind"
ATTR_VALUE = "usage-rollup"
NUM_ATTR_KEY = "retry_count"
RESOURCE_KEY = "deployment.environment"
RESOURCE_VALUE = "production"


def _leaf(key: str, operator: str, value, type_: str = "log") -> dict:
    leaf: dict = {"key": key, "operator": operator, "type": type_}
    if value is not None:
        leaf["value"] = value
    return leaf


def _filters(*leaves: dict, services: list[str] | None = None, severities: list[str] | None = None) -> dict:
    filters: dict = {}
    if services is not None:
        filters["serviceNames"] = services
    if severities is not None:
        filters["severityLevels"] = severities
    if leaves:
        filters["filterGroup"] = {"type": "AND", "values": [{"type": "AND", "values": list(leaves)}]}
    return filters


# Every operator surface the filter builder exposes, one leaf per case.
# expect_matches pins the seeded sweep against vacuous all-zero equivalence.
OPERATOR_CATALOG: list[tuple[str, dict, bool]] = [
    ("body_exact", _leaf("message", "exact", BODY_EXACT), True),
    ("body_exact_list", _leaf("message", "exact", [BODY_EXACT, "never_logged"]), True),
    ("body_is_not", _leaf("message", "is_not", BODY_EXACT), True),
    ("body_icontains", _leaf("message", "icontains", BODY_NEEDLE), True),
    ("body_not_icontains", _leaf("message", "not_icontains", BODY_NEEDLE), True),
    ("body_regex", _leaf("message", "regex", "export failed|task_crashed"), True),
    ("body_not_regex", _leaf("message", "not_regex", "task_crashed"), True),
    ("attr_exact", _leaf(ATTR_KEY, "exact", ATTR_VALUE, "log_attribute"), True),
    ("attr_exact_list", _leaf(ATTR_KEY, "exact", [ATTR_VALUE, "never-set"], "log_attribute"), True),
    ("attr_numeric_gt", _leaf(NUM_ATTR_KEY, "gt", "2", "log_attribute"), True),
    ("attr_icontains", _leaf(ATTR_KEY, "icontains", "rollup", "log_attribute"), True),
    ("attr_regex", _leaf(ATTR_KEY, "regex", "usage-.*", "log_attribute"), True),
    ("attr_is_set", _leaf(ATTR_KEY, "is_set", None, "log_attribute"), True),
    ("attr_is_not_set", _leaf(ATTR_KEY, "is_not_set", None, "log_attribute"), True),
    ("resource_exact", _leaf(RESOURCE_KEY, "exact", RESOURCE_VALUE, "log_resource_attribute"), True),
    ("resource_exact_list", _leaf(RESOURCE_KEY, "exact", [RESOURCE_VALUE], "log_resource_attribute"), True),
    ("resource_is_not", _leaf(RESOURCE_KEY, "is_not", "staging", "log_resource_attribute"), True),
    ("resource_icontains", _leaf(RESOURCE_KEY, "icontains", "prod", "log_resource_attribute"), True),
    ("severity_level_leaf", _leaf("severity_level", "exact", ["error"]), True),
    ("trace_id_exact", _leaf("trace_id", "exact", "0123456789abcdef0123456789abcdef"), False),
    (
        "nested_or_attr_group",
        {
            "type": "OR",
            "values": [
                _leaf(ATTR_KEY, "exact", ATTR_VALUE, "log_attribute"),
                _leaf("logtag", "exact", "F", "log_attribute"),
            ],
        },
        True,
    ),
]

# Representatives of each distinct expression shape the builder can emit; the
# interaction sweep crosses these. The incident was body_index_hint ×
# resource_subquery_in on an empty scan — a pair, not a single leaf.
SHAPE_CLASSES: dict[str, dict] = {
    "body_index_hint": _leaf("message", "icontains", BODY_NEEDLE),
    "attr_map": _leaf(ATTR_KEY, "exact", ATTR_VALUE, "log_attribute"),
    "resource_subquery_in": _leaf(RESOURCE_KEY, "exact", RESOURCE_VALUE, "log_resource_attribute"),
    "resource_subquery_not_in": _leaf(RESOURCE_KEY, "is_not", "staging", "log_resource_attribute"),
    "nested_or_group": {
        "type": "OR",
        "values": [
            _leaf(ATTR_KEY, "exact", ATTR_VALUE, "log_attribute"),
            _leaf("logtag", "exact", "F", "log_attribute"),
        ],
    },
}

SHAPE_PAIRS = list(itertools.combinations(sorted(SHAPE_CLASSES), 2))
SHAPE_TRIPLES = list(itertools.combinations(sorted(SHAPE_CLASSES), 3))


def _make_alert(team, filters: dict, name: str) -> LogsAlertConfiguration:
    return LogsAlertConfiguration.objects.create(
        team=team,
        name=name,
        threshold_count=0,
        threshold_operator="above",
        window_minutes=5,
        evaluation_periods=3,
        filters=filters,
    )


class _HoistingSweepBase(ClickhouseTestMixin, APIBaseTest):
    class Meta:
        abstract = True

    def _assert_batched_matches_per_alert(self, alerts: list[LogsAlertConfiguration]) -> dict[str, int]:
        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=alerts, date_from=DATE_FROM, date_to=NCA, projection_eligible=False
        ).execute_rolling_checks(nca=NCA, window_minutes=5, cadence_minutes=5, period_count=3)

        totals: dict[str, int] = {}
        for alert in alerts:
            single = AlertCheckQuery(
                team=self.team, alert=alert, date_from=DATE_FROM, date_to=NCA
            ).execute_rolling_checks(nca=NCA, window_minutes=5, cadence_minutes=5, period_count=3)
            assert batched.per_alert[str(alert.id)] == single, f"alert={alert.name}"
            totals[alert.name] = sum(b.count for b in single)
        return totals


def _seed_sweep_rows(team_id: int) -> None:
    prod = {RESOURCE_KEY: RESOURCE_VALUE}
    staging = {RESOURCE_KEY: "staging"}
    rows = [
        _log_row(
            team_id,
            "sweep-1",
            "2026-03-05 10:01:10",
            SERVICE,
            severity="error",
            body=BODY_EXACT,
            # The numeric value feeds the MATERIALIZED attributes_map_float
            # column (derived from the str map), which the numeric-gt leaf reads.
            attributes={f"{ATTR_KEY}__str": ATTR_VALUE, "logtag__str": "F", f"{NUM_ATTR_KEY}__str": "3"},
            resource_attributes=prod,
        ),
        _log_row(
            team_id,
            "sweep-2",
            "2026-03-05 10:02:20",
            SERVICE,
            severity="error",
            body=f"nightly {BODY_NEEDLE}: connection reset",
            attributes={f"{ATTR_KEY}__str": "cleanup"},
            resource_attributes=prod,
        ),
        _log_row(
            team_id,
            "sweep-3",
            "2026-03-05 10:03:30",
            SERVICE,
            severity="error",
            body="routine heartbeat",
            resource_attributes=staging,
        ),
        _log_row(
            team_id,
            "sweep-4",
            "2026-03-05 10:04:40",
            SERVICE,
            severity="info",
            body=f"{BODY_NEEDLE}: retrying",
            attributes={f"{ATTR_KEY}__str": ATTR_VALUE},
            resource_attributes=prod,
        ),
        _log_row(
            team_id,
            "sweep-5",
            "2026-03-05 10:01:50",
            OTHER_SERVICE,
            severity="error",
            body=BODY_EXACT,
            attributes={f"{ATTR_KEY}__str": ATTR_VALUE},
            resource_attributes=prod,
        ),
    ]
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in rows))


class TestHoistedOperatorSweepSeeded(_HoistingSweepBase):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _seed_sweep_rows(cls.team.id)

    @parameterized.expand([(name, leaf, expect_matches) for name, leaf, expect_matches in OPERATOR_CATALOG])
    def test_operator_leaf(self, _name: str, leaf: dict, expect_matches: bool):
        alert = _make_alert(self.team, _filters(leaf, services=[SERVICE], severities=["error", "fatal"]), _name)
        totals = self._assert_batched_matches_per_alert([alert])
        if expect_matches:
            assert totals[_name] > 0, f"vacuous case: {_name} matched nothing in the seeded window"

        batched = BatchedAlertCheckQuery(
            team=self.team, alerts=[alert], date_from=DATE_FROM, date_to=NCA, projection_eligible=False
        ).execute_bucketed(interval_minutes=5)
        single = AlertCheckQuery(team=self.team, alert=alert, date_from=DATE_FROM, date_to=NCA).execute_bucketed(
            interval_minutes=5
        )
        non_zero = [b for b in batched.per_alert[str(alert.id)] if b.count > 0]
        assert non_zero == single


# No fixture rows anywhere in this class: the scan must select zero parts so
# a constant-folded predicate column meets an empty source stream — the
# trigger condition for the ILLEGAL_COLUMN plan failure.
class TestHoistedOperatorSweepEmptyScan(_HoistingSweepBase):
    @parameterized.expand([(name, leaf) for name, leaf, _ in OPERATOR_CATALOG])
    def test_operator_leaf(self, _name: str, leaf: dict):
        alert = _make_alert(self.team, _filters(leaf, services=[SERVICE], severities=["error", "fatal"]), _name)
        totals = self._assert_batched_matches_per_alert([alert])
        assert totals[_name] == 0


class TestHoistedShapeInteractionsSeeded(_HoistingSweepBase):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _seed_sweep_rows(cls.team.id)

    @parameterized.expand([("_".join(pair), pair) for pair in SHAPE_PAIRS])
    def test_shape_pair_same_alert(self, _name: str, pair: tuple[str, str]):
        leaves = [SHAPE_CLASSES[s] for s in pair]
        alert = _make_alert(self.team, _filters(*leaves, services=[SERVICE], severities=["error", "fatal"]), _name)
        self._assert_batched_matches_per_alert([alert])

    @parameterized.expand([("_".join(pair), pair) for pair in SHAPE_PAIRS])
    def test_shape_pair_across_cohort(self, _name: str, pair: tuple[str, str]):
        # The hoisted WHERE ORs the two alerts' predicates together, so shapes
        # interact across alerts too, not only within one alert's AND.
        alerts = [
            _make_alert(self.team, _filters(SHAPE_CLASSES[s], services=[SERVICE], severities=["error", "fatal"]), s)
            for s in pair
        ]
        self._assert_batched_matches_per_alert(alerts)


class TestHoistedShapeInteractionsEmptyScan(_HoistingSweepBase):
    @parameterized.expand([("_".join(pair), pair) for pair in SHAPE_PAIRS])
    def test_shape_pair_same_alert(self, _name: str, pair: tuple[str, str]):
        leaves = [SHAPE_CLASSES[s] for s in pair]
        alert = _make_alert(self.team, _filters(*leaves, services=[SERVICE], severities=["error", "fatal"]), _name)
        totals = self._assert_batched_matches_per_alert([alert])
        assert all(t == 0 for t in totals.values())

    @parameterized.expand([("_".join(pair), pair) for pair in SHAPE_PAIRS])
    def test_shape_pair_across_cohort(self, _name: str, pair: tuple[str, str]):
        alerts = [
            _make_alert(self.team, _filters(SHAPE_CLASSES[s], services=[SERVICE], severities=["error", "fatal"]), s)
            for s in pair
        ]
        totals = self._assert_batched_matches_per_alert(alerts)
        assert all(t == 0 for t in totals.values())

    @parameterized.expand([("_".join(triple), triple) for triple in SHAPE_TRIPLES])
    def test_shape_triple_same_alert(self, _name: str, triple: tuple[str, str, str]):
        leaves = [SHAPE_CLASSES[s] for s in triple]
        alert = _make_alert(self.team, _filters(*leaves, services=[SERVICE], severities=["error", "fatal"]), _name)
        totals = self._assert_batched_matches_per_alert([alert])
        assert all(t == 0 for t in totals.values())

    def test_random_cohort_compositions(self):
        # Fixed-seed random cohorts probe combinations the pair/triple grids
        # don't enumerate: mixed cohort sizes, repeated shapes, alerts with and
        # without service/severity scoping.
        rng = random.Random(2026)
        shape_names = sorted(SHAPE_CLASSES)
        for trial in range(12):
            alerts = []
            for i in range(rng.randint(1, 3)):
                leaves = [SHAPE_CLASSES[rng.choice(shape_names)] for _ in range(rng.randint(1, 3))]
                services = [SERVICE] if rng.random() < 0.7 else None
                severities = ["error", "fatal"] if rng.random() < 0.7 else None
                alerts.append(
                    _make_alert(
                        self.team,
                        _filters(*leaves, services=services, severities=severities),
                        f"trial{trial}_alert{i}",
                    )
                )
            totals = self._assert_batched_matches_per_alert(alerts)
            assert all(t == 0 for t in totals.values()), f"trial {trial}"


# Adversarial-value property test. Slow (every example round-trips ClickHouse),
# so gated like the other PBT suites. Run manually with:
#   RUN_PBT=1 pytest products/logs/backend/test/test_alert_hoisting_sweep.py -k Properties
if os.environ.get("RUN_PBT"):
    from hypothesis import (
        HealthCheck,
        given,
        settings as hypothesis_settings,
        strategies as st,
    )
    from hypothesis.extra.django import TestCase as HypothesisDjangoTestCase

    _value_text = st.text(
        alphabet=st.characters(blacklist_characters="\0", blacklist_categories=["Cs"]),
        min_size=1,
        max_size=40,
    )
    _safe_regex = st.text(alphabet="abcdef.*|+?()[]\\^$", min_size=1, max_size=20)

    @st.composite
    def _leaf_st(draw):
        kind = draw(st.sampled_from(["body", "attr", "resource"]))
        if kind == "body":
            operator = draw(st.sampled_from(["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex"]))
            value = draw(_safe_regex if "regex" in operator else _value_text)
            return _leaf("message", operator, value)
        if kind == "attr":
            operator = draw(st.sampled_from(["exact", "is_not", "icontains", "regex", "is_set", "is_not_set"]))
            value = None if "set" in operator else draw(_safe_regex if operator == "regex" else _value_text)
            return _leaf(ATTR_KEY, operator, value, "log_attribute")
        operator = draw(st.sampled_from(["exact", "is_not", "icontains"]))
        return _leaf(RESOURCE_KEY, operator, draw(_value_text), "log_resource_attribute")

    _alert_filters_st = st.builds(
        lambda leaves, services, severities: _filters(*leaves, services=services, severities=severities),
        st.lists(_leaf_st(), min_size=1, max_size=3),
        st.sampled_from([None, [SERVICE]]),
        st.sampled_from([None, ["error", "fatal"]]),
    )

    class TestHoistedConfigProperties(ClickhouseTestMixin, HypothesisDjangoTestCase, APIBaseTest):
        # hypothesis's TestCase displaces Django's _pre_setup in the MRO, so the
        # HTTP test client never gets built; these tests never call the API.
        CONFIG_AUTO_LOGIN = False

        @hypothesis_settings(
            max_examples=250,
            deadline=None,
            suppress_health_check=[HealthCheck.differing_executors, HealthCheck.too_slow],
        )
        @given(cohort=st.lists(_alert_filters_st, min_size=1, max_size=3))
        def test_hoisted_batched_behaves_like_per_alert(self, cohort: list[dict]):
            # Property: for ANY customer-authorable config, the hoisted batched
            # query and the per-alert query either both succeed with identical
            # results, or both fail. A config that errors identically on both
            # paths is a customer problem; one that errors only when batched is
            # ours.
            alerts = [_make_alert(self.team, filters, f"pbt{i}") for i, filters in enumerate(cohort)]

            singles: dict[str, list] = {}
            per_alert_error: Exception | None = None
            for alert in alerts:
                try:
                    singles[str(alert.id)] = AlertCheckQuery(
                        team=self.team, alert=alert, date_from=DATE_FROM, date_to=NCA
                    ).execute_rolling_checks(nca=NCA, window_minutes=5, cadence_minutes=5, period_count=3)
                except Exception as e:
                    per_alert_error = e
                    break

            # Both construction (e.g. invalid regex rejected while building the
            # predicate) and execution can raise; either counts, as long as the
            # batched path fails whenever the per-alert path does.
            def run_batched():
                query = BatchedAlertCheckQuery(
                    team=self.team, alerts=alerts, date_from=DATE_FROM, date_to=NCA, projection_eligible=False
                )
                return query.execute_rolling_checks(nca=NCA, window_minutes=5, cadence_minutes=5, period_count=3)

            if per_alert_error is not None:
                with pytest.raises(Exception):
                    run_batched()
                return

            batched = run_batched()
            for alert in alerts:
                assert batched.per_alert[str(alert.id)] == singles[str(alert.id)]
