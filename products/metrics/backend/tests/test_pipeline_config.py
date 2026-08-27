import pytest

from parameterized import parameterized

from products.metrics.backend.facade.contracts import MAX_PIPELINE_EDGES
from products.metrics.backend.facade.enums import HealthState, MetricAggregation
from products.metrics.backend.pipeline_config import parse_pipeline_config, parse_relative_offset

VALID_CONFIG = {
    "variables": [
        {
            "key": "environment",
            "label": "Environment",
            "filter_key": "k8s.cluster.name",
            "options": ["prod-us", "prod-eu"],
            "default": "prod-us",
        }
    ],
    "nodes": [
        {
            "id": "capture",
            "name": "Capture",
            "kind": "capture-rs",
            "stats": [
                {
                    "id": "accept_rate",
                    "label": "accept",
                    "format": "rate",
                    "metric_name": "envoy_cluster_upstream_rq",
                    "aggregation": "rate",
                    "thresholds": {"warn": {"upper": 20000}, "crit": {"upper": 50000}},
                },
                {
                    "id": "p99_accept",
                    "label": "p99 accept",
                    "format": "duration",
                    "metric_name": "envoy_cluster_upstream_rq_time",
                    "aggregation": "histogram_quantile",
                    "quantile": 0.99,
                },
            ],
            "headline_stat_ids": ["accept_rate"],
            "links": [{"label": "Runbook", "url": "https://example.com/runbook"}],
        },
        {
            "id": "kafka",
            "name": "Kafka",
            "kind": "broker",
            "stats": [
                {
                    "id": "lag",
                    "label": "consumer lag",
                    "format": "count",
                    "metric_name": "kminion_kafka_consumer_group_topic_partition_lag",
                    "aggregation": "sum",
                    "filters": [{"key": "group_id", "op": "eq", "value": "ingestion-logs"}],
                    "thresholds": {"warn": {"upper": 30000}, "crit": {"upper": 100000}},
                    "breakdown": {"group_by_key": "partition_id", "top_n": 5},
                }
            ],
        },
    ],
    "edges": [
        {
            "source": "capture",
            "target": "kafka",
            "metric_name": "envoy_cluster_upstream_rq",
            "aggregation": "rate",
            "baseline_offset": "-7d",
            "hot_multiplier": 2.0,
        }
    ],
}


def config_with(**overrides):
    data = {**VALID_CONFIG, **overrides}
    return data


class TestParsePipelineConfig:
    def test_valid_config_round_trips(self):
        config = parse_pipeline_config(VALID_CONFIG)
        assert [n.id for n in config.nodes] == ["capture", "kafka"]
        assert config.nodes[0].stats[1].aggregation == MetricAggregation.HISTOGRAM_QUANTILE
        assert config.nodes[0].stats[1].quantile == 0.99
        assert config.nodes[1].stats[0].filters[0].value == "ingestion-logs"
        assert config.nodes[1].stats[0].breakdown is not None
        assert config.nodes[1].stats[0].breakdown.top_n == 5
        assert config.edges[0].source == "capture"
        assert config.edges[0].hot_multiplier == 2.0
        assert config.variables[0].filter_key == "k8s.cluster.name"

    def test_empty_nodes_rejected(self):
        with pytest.raises(ValueError, match="at least one node"):
            parse_pipeline_config(config_with(nodes=[], edges=[]))

    def test_duplicate_node_ids_rejected(self):
        nodes = [dict(VALID_CONFIG["nodes"][0]), dict(VALID_CONFIG["nodes"][0])]
        with pytest.raises(ValueError, match="duplicate node id"):
            parse_pipeline_config(config_with(nodes=nodes, edges=[]))

    def test_duplicate_stat_ids_within_node_rejected(self):
        node = dict(VALID_CONFIG["nodes"][0])
        node["stats"] = [dict(node["stats"][0]), dict(node["stats"][0])]
        with pytest.raises(ValueError, match="duplicate stat id"):
            parse_pipeline_config(config_with(nodes=[node], edges=[]))

    @parameterized.expand(
        [
            ("dangling_source", {"source": "missing", "target": "kafka"}),
            ("dangling_target", {"source": "capture", "target": "missing"}),
            ("self_edge", {"source": "capture", "target": "capture"}),
        ]
    )
    def test_bad_edge_refs_rejected(self, _name, edge_override):
        edge = {**VALID_CONFIG["edges"][0], **edge_override}
        with pytest.raises(ValueError):
            parse_pipeline_config(config_with(edges=[edge]))

    def test_cycle_rejected(self):
        back_edge = {**VALID_CONFIG["edges"][0], "source": "kafka", "target": "capture"}
        with pytest.raises(ValueError, match="cycle"):
            parse_pipeline_config(config_with(edges=[VALID_CONFIG["edges"][0], back_edge]))

    def test_unknown_headline_stat_rejected(self):
        node = dict(VALID_CONFIG["nodes"][0])
        node["headline_stat_ids"] = ["nope"]
        with pytest.raises(ValueError, match="headline"):
            parse_pipeline_config(config_with(nodes=[node], edges=[]))

    def test_quantile_required_for_histogram_quantile(self):
        node = dict(VALID_CONFIG["nodes"][0])
        stat = dict(node["stats"][1])
        del stat["quantile"]
        node["stats"] = [node["stats"][0], stat]
        with pytest.raises(ValueError, match="quantile"):
            parse_pipeline_config(config_with(nodes=[node], edges=[]))

    def test_duplicate_edges_rejected(self):
        edge = VALID_CONFIG["edges"][0]
        with pytest.raises(ValueError, match="duplicate edge"):
            parse_pipeline_config(config_with(edges=[edge, dict(edge)]))

    def test_too_many_edges_rejected(self):
        # Every edge costs two ClickHouse queries per refresh tick.
        edge = VALID_CONFIG["edges"][0]
        nodes = VALID_CONFIG["nodes"]
        many = [{**edge, "target": f"n{i}"} for i in range(MAX_PIPELINE_EDGES + 1)]
        extra = [{**dict(nodes[1]), "id": f"n{i}"} for i in range(MAX_PIPELINE_EDGES + 1)]
        with pytest.raises(ValueError, match="at most"):
            parse_pipeline_config(config_with(nodes=[nodes[0], *extra], edges=many))

    def test_duplicate_variable_keys_rejected(self):
        variables = [dict(VALID_CONFIG["variables"][0]), dict(VALID_CONFIG["variables"][0])]
        with pytest.raises(ValueError, match="duplicate variable key"):
            parse_pipeline_config(config_with(variables=variables))

    def test_warn_bounds_must_be_numbers(self):
        node = dict(VALID_CONFIG["nodes"][0])
        stat = dict(node["stats"][0])
        stat["thresholds"] = {"warn": {"upper": "high"}}
        node["stats"] = [stat]
        with pytest.raises(ValueError, match="threshold"):
            parse_pipeline_config(config_with(nodes=[node], edges=[]))

    def test_unknown_aggregation_rejected(self):
        node = dict(VALID_CONFIG["nodes"][0])
        stat = dict(node["stats"][0])
        stat["aggregation"] = "median"
        node["stats"] = [stat]
        with pytest.raises(ValueError, match="aggregation"):
            parse_pipeline_config(config_with(nodes=[node], edges=[]))


class TestParseRelativeOffset:
    @parameterized.expand(
        [
            ("-7d", 7 * 24 * 3600),
            ("-1w", 7 * 24 * 3600),
            ("-24h", 24 * 3600),
            ("-30m", 30 * 60),
        ]
    )
    def test_valid_offsets(self, text, expected_seconds):
        assert parse_relative_offset(text).total_seconds() == expected_seconds

    @parameterized.expand([("7d",), ("-7x",), ("",), ("-d",), ("-0d",)])
    def test_invalid_offsets_rejected(self, text):
        with pytest.raises(ValueError):
            parse_relative_offset(text)


class TestHealthStateEnum:
    def test_worst_of_ordering(self):
        assert HealthState.worst([HealthState.HEALTHY, HealthState.DEGRADED]) == HealthState.DEGRADED
        assert HealthState.worst([HealthState.DEGRADED, HealthState.CRITICAL]) == HealthState.CRITICAL
        assert HealthState.worst([HealthState.NO_DATA, HealthState.HEALTHY]) == HealthState.HEALTHY
        assert HealthState.worst([HealthState.NO_DATA]) == HealthState.NO_DATA
        assert HealthState.worst([]) == HealthState.NO_DATA
