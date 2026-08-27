import datetime as dt

from parameterized import parameterized

from products.metrics.backend.facade.contracts import MetricPoint, MetricQueryRequest, MetricSeries
from products.metrics.backend.facade.enums import HealthState
from products.metrics.backend.pipeline_config import parse_pipeline_config
from products.metrics.backend.pipeline_evaluation import evaluate_pipeline

DATE_FROM = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
DATE_TO = dt.datetime(2026, 8, 26, 12, 30, tzinfo=dt.UTC)


def make_config(stat_overrides=None, second_node_stats=None, edges=None, variables=None):
    stat = {
        "id": "s1",
        "label": "stat one",
        "format": "rate",
        "metric_name": "m1",
        "aggregation": "rate",
        "thresholds": {"warn": {"upper": 100}, "crit": {"upper": 200}},
        **(stat_overrides or {}),
    }
    nodes = [{"id": "a", "name": "A", "kind": "svc", "stats": [stat]}]
    if second_node_stats is not None:
        nodes.append({"id": "b", "name": "B", "kind": "svc", "stats": second_node_stats})
    return parse_pipeline_config(
        {"variables": variables or [], "nodes": nodes, "edges": edges or []},
    )


def series(values, labels=None, clause="s1", metric_name="m1"):
    points = tuple(
        MetricPoint(time=(DATE_FROM + dt.timedelta(minutes=i)).isoformat(), value=v) for i, v in enumerate(values)
    )
    return MetricSeries(labels=labels or {}, points=points, metric_name=metric_name, clause=clause)


class RecordingRunner:
    def __init__(self, responder):
        self.requests: list[MetricQueryRequest] = []
        self._responder = responder

    def __call__(self, request: MetricQueryRequest) -> list[MetricSeries]:
        self.requests.append(request)
        return self._responder(request)


def respond_with(values_by_clause):
    def responder(request):
        result = []
        for clause in request.clauses:
            value_spec = values_by_clause[clause.name]
            if callable(value_spec):
                result.extend(value_spec(request, clause))
            else:
                result.append(series(value_spec, clause=clause.name, metric_name=clause.metric_name))
        return result

    return responder


def evaluate(config, responder, variable_values=None):
    runner = RecordingRunner(responder)
    evaluation = evaluate_pipeline(
        config=config,
        run_query=runner,
        date_from=DATE_FROM,
        date_to=DATE_TO,
        variable_values=variable_values,
    )
    return evaluation, runner


class TestEvaluatePipeline:
    @parameterized.expand(
        [
            ("healthy", [10.0, 50.0], HealthState.HEALTHY),
            ("degraded_above_warn", [10.0, 150.0], HealthState.DEGRADED),
            ("critical_above_crit", [10.0, 250.0], HealthState.CRITICAL),
        ]
    )
    def test_stat_upper_bound_verdicts(self, _name, values, expected_state):
        evaluation, _ = evaluate(make_config(), respond_with({"s1": values}))
        stat = evaluation.nodes[0].stats[0]
        assert stat.state == expected_state
        assert stat.value == values[-1]
        assert evaluation.nodes[0].state == expected_state

    def test_stat_lower_bound_verdict(self):
        config = make_config(stat_overrides={"thresholds": {"warn": {"lower": 10}, "crit": {"lower": 2}}})
        evaluation, _ = evaluate(config, respond_with({"s1": [50.0, 5.0]}))
        assert evaluation.nodes[0].stats[0].state == HealthState.DEGRADED
        evaluation, _ = evaluate(config, respond_with({"s1": [50.0, 1.0]}))
        assert evaluation.nodes[0].stats[0].state == HealthState.CRITICAL

    def test_stat_without_thresholds_is_healthy_when_reporting(self):
        config = make_config(stat_overrides={"thresholds": None})
        evaluation, _ = evaluate(config, respond_with({"s1": [7.0]}))
        assert evaluation.nodes[0].stats[0].state == HealthState.HEALTHY

    def test_stat_with_no_points_is_no_data(self):
        evaluation, _ = evaluate(make_config(), respond_with({"s1": []}))
        stat = evaluation.nodes[0].stats[0]
        assert stat.state == HealthState.NO_DATA
        assert stat.value is None
        assert evaluation.nodes[0].state == HealthState.NO_DATA

    def test_trailing_gap_falls_back_to_last_reported_value(self):
        evaluation, _ = evaluate(make_config(), respond_with({"s1": [50.0, None]}))
        assert evaluation.nodes[0].stats[0].value == 50.0
        assert evaluation.nodes[0].stats[0].state == HealthState.HEALTHY

    def test_node_state_is_worst_stat_and_ignores_no_data(self):
        second = [
            {"id": "ok", "label": "ok", "format": "count", "metric_name": "m2", "aggregation": "sum"},
            {
                "id": "bad",
                "label": "bad",
                "format": "count",
                "metric_name": "m3",
                "aggregation": "sum",
                "thresholds": {"crit": {"upper": 1}},
            },
            {"id": "silent", "label": "silent", "format": "count", "metric_name": "m4", "aggregation": "sum"},
        ]
        config = make_config(second_node_stats=second)
        evaluation, _ = evaluate(
            config,
            respond_with({"s1": [1.0], "ok": [1.0], "bad": [9.0], "silent": []}),
        )
        node_b = evaluation.nodes[1]
        assert node_b.state == HealthState.CRITICAL
        assert {s.id: s.state for s in node_b.stats}["silent"] == HealthState.NO_DATA

    def test_edge_multiplier_and_hot(self):
        edges = [
            {
                "source": "a",
                "target": "b",
                "metric_name": "edge_m",
                "aggregation": "rate",
                "baseline_offset": "-7d",
                "hot_multiplier": 2.0,
            }
        ]

        def edge_values(request, clause):
            is_baseline = request.date_from < DATE_FROM
            return [series([10.0, 10.0] if is_baseline else [30.0, 30.0], clause=clause.name)]

        config = make_config(
            second_node_stats=[
                {"id": "s2", "label": "x", "format": "count", "metric_name": "m2", "aggregation": "sum"}
            ],
            edges=edges,
        )
        evaluation, runner = evaluate(config, respond_with({"s1": [1.0], "s2": [1.0], "edge": edge_values}))
        edge = evaluation.edges[0]
        assert edge.baseline_value == 10.0
        assert edge.current_value == 30.0
        assert edge.multiplier == 3.0
        assert edge.hot is True
        assert [p.value for p in edge.points] == [30.0, 30.0]
        baseline_requests = [r for r in runner.requests if r.date_from < DATE_FROM]
        assert len(baseline_requests) == 1
        assert baseline_requests[0].date_from == DATE_FROM - dt.timedelta(days=7)
        assert baseline_requests[0].date_to == DATE_TO - dt.timedelta(days=7)

    def test_edge_with_zero_baseline_has_no_multiplier(self):
        edges = [{"source": "a", "target": "b", "metric_name": "edge_m", "aggregation": "rate"}]

        def edge_values(request, clause):
            is_baseline = request.date_from < DATE_FROM
            return [series([0.0] if is_baseline else [30.0], clause=clause.name)]

        config = make_config(
            second_node_stats=[
                {"id": "s2", "label": "x", "format": "count", "metric_name": "m2", "aggregation": "sum"}
            ],
            edges=edges,
        )
        evaluation, _ = evaluate(config, respond_with({"s1": [1.0], "s2": [1.0], "edge": edge_values}))
        assert evaluation.edges[0].multiplier is None
        assert evaluation.edges[0].hot is False

    def test_variable_values_inject_filters_into_every_request(self):
        variables = [{"key": "environment", "label": "Env", "filter_key": "k8s.cluster.name", "options": ["prod-us"]}]
        config = make_config(variables=variables)
        _, runner = evaluate(config, respond_with({"s1": [1.0]}), variable_values={"environment": "prod-us"})
        for request in runner.requests:
            for clause in request.clauses:
                injected = [f for f in clause.filters if f.key == "k8s.cluster.name"]
                assert [f.value for f in injected] == ["prod-us"]

    def test_unknown_variable_value_rejected(self):
        variables = [{"key": "environment", "label": "Env", "filter_key": "k8s.cluster.name", "options": ["prod-us"]}]
        config = make_config(variables=variables)
        runner = RecordingRunner(respond_with({"s1": [1.0]}))
        try:
            evaluate_pipeline(
                config=config,
                run_query=runner,
                date_from=DATE_FROM,
                date_to=DATE_TO,
                variable_values={"environment": "prod-eu"},
            )
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_each_stat_queries_on_its_own_grid(self):
        # Clauses sharing one request share one zero-filled bucket grid, so a
        # slow-reporting stat would inherit trailing zeros from a fast
        # neighbour and read as reporting zero instead of NO_DATA.
        second = [
            {"id": f"s{i}", "label": f"stat {i}", "format": "count", "metric_name": f"m{i}", "aggregation": "sum"}
            for i in range(4)
        ]
        config = make_config(second_node_stats=second)
        _, runner = evaluate(config, respond_with({"s1": [1.0], "s0": [1.0], "s2": [1.0], "s3": [1.0]}))
        assert runner.requests, "expected at least one query"
        assert all(len(request.clauses) == 1 for request in runner.requests)

    def test_alerts_derived_from_breached_stats(self):
        second = [
            {
                "id": "bad",
                "label": "consumer lag",
                "format": "count",
                "metric_name": "m3",
                "aggregation": "sum",
                "thresholds": {"warn": {"upper": 5}, "crit": {"upper": 8}},
            }
        ]
        config = make_config(second_node_stats=second)
        evaluation, _ = evaluate(config, respond_with({"s1": [150.0], "bad": [9.0]}))
        by_stat = {(a.node_id, a.stat_id): a.severity for a in evaluation.alerts}
        assert by_stat[("a", "s1")] == "warning"
        assert by_stat[("b", "bad")] == "critical"
        assert all("consumer lag" in a.message for a in evaluation.alerts if a.stat_id == "bad")

    def test_breakdown_rows_top_n_with_others_rollup(self):
        stat = {
            "id": "s1",
            "label": "lag",
            "format": "count",
            "metric_name": "m1",
            "aggregation": "sum",
            "breakdown": {"group_by_key": "partition", "top_n": 2},
        }

        def breakdown_values(request, clause):
            if clause.group_by:
                return [
                    series([100.0], labels={"partition": "p1"}, clause=clause.name),
                    series([300.0], labels={"partition": "p2"}, clause=clause.name),
                    series([50.0], labels={"partition": "p3"}, clause=clause.name),
                    series([25.0], labels={"partition": "p4"}, clause=clause.name),
                ]
            return [series([475.0], clause=clause.name)]

        config = make_config(stat_overrides=stat)
        evaluation, _ = evaluate(config, respond_with({"s1": breakdown_values}))
        result_stat = evaluation.nodes[0].stats[0]
        assert [(r.label, r.value) for r in result_stat.breakdown_rows] == [("p2", 300.0), ("p1", 100.0)]
        assert result_stat.breakdown_others is not None
        assert result_stat.breakdown_others.value == 75.0
        assert "2" in result_stat.breakdown_others.label
