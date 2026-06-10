from typing import Any

import pytest

from parameterized import parameterized

from products.notebooks.backend.query_validation import InvalidNotebookQueryError, normalize_notebook_query_nodes

HOGQL_SOURCE: dict[str, Any] = {"kind": "HogQLQuery", "query": "SELECT 1"}
VALID_DATA_VIZ: dict[str, Any] = {
    "kind": "DataVisualizationNode",
    "source": HOGQL_SOURCE,
    "display": "ActionsBar",
}
VALID_INSIGHT_VIZ: dict[str, Any] = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": []},
}


def _wrap(query: dict | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {"nodeId": "n1"}
    if query is not None:
        attrs["query"] = query
    return {
        "type": "doc",
        "content": [{"type": "ph-query", "attrs": attrs}],
    }


def _extract_query(doc: dict[str, Any]) -> dict | None:
    return doc["content"][0]["attrs"].get("query")


class TestNormalizeNotebookQueryNodes:
    def test_returns_non_dict_input_unchanged(self) -> None:
        assert normalize_notebook_query_nodes(None) is None
        assert normalize_notebook_query_nodes("plain") == "plain"
        assert normalize_notebook_query_nodes([1, 2, 3]) == [1, 2, 3]

    def test_passes_through_doc_without_ph_query_nodes(self) -> None:
        doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}]}
        assert normalize_notebook_query_nodes(doc) == doc

    def test_passes_through_ph_query_without_query_attr(self) -> None:
        doc = {"type": "doc", "content": [{"type": "ph-query", "attrs": {"nodeId": "x"}}]}
        assert normalize_notebook_query_nodes(doc) == doc

    def test_passes_through_valid_data_visualization_node(self) -> None:
        doc = _wrap(VALID_DATA_VIZ)
        assert _extract_query(normalize_notebook_query_nodes(doc)) == VALID_DATA_VIZ

    def test_passes_through_valid_insight_viz_node(self) -> None:
        doc = _wrap(VALID_INSIGHT_VIZ)
        assert _extract_query(normalize_notebook_query_nodes(doc)) == VALID_INSIGHT_VIZ

    def test_unwraps_insight_viz_node_wrapping_data_visualization_node(self) -> None:
        # The exact bug observed in notebook wUll: AI agent wrapped a SQL chart in an
        # InsightVizNode shell. The inner DataVisualizationNode is the correct shape.
        bad = {"kind": "InsightVizNode", "source": VALID_DATA_VIZ}
        result = _extract_query(normalize_notebook_query_nodes(_wrap(bad)))
        assert result == VALID_DATA_VIZ

    def test_rewraps_insight_viz_node_wrapping_hogql_query(self) -> None:
        bad = {"kind": "InsightVizNode", "source": HOGQL_SOURCE}
        result = _extract_query(normalize_notebook_query_nodes(_wrap(bad)))
        assert result == {"kind": "DataVisualizationNode", "source": HOGQL_SOURCE}

    def test_rejects_insight_viz_node_wrapping_unknown_kind(self) -> None:
        bad = {"kind": "InsightVizNode", "source": {"kind": "MadeUpQuery"}}
        with pytest.raises(InvalidNotebookQueryError, match="MadeUpQuery"):
            normalize_notebook_query_nodes(_wrap(bad))

    def test_rejects_insight_viz_node_without_source(self) -> None:
        bad = {"kind": "InsightVizNode"}
        with pytest.raises(InvalidNotebookQueryError, match="without a `source`"):
            normalize_notebook_query_nodes(_wrap(bad))

    def test_rejects_data_visualization_node_with_non_hogql_source(self) -> None:
        bad = {"kind": "DataVisualizationNode", "source": {"kind": "TrendsQuery"}}
        with pytest.raises(InvalidNotebookQueryError, match="TrendsQuery"):
            normalize_notebook_query_nodes(_wrap(bad))

    def test_rejects_data_visualization_node_without_source(self) -> None:
        bad = {"kind": "DataVisualizationNode"}
        with pytest.raises(InvalidNotebookQueryError, match="without a `source`"):
            normalize_notebook_query_nodes(_wrap(bad))

    @parameterized.expand(
        [
            ("SavedInsightNode", {"kind": "SavedInsightNode", "shortId": "abc"}),
            ("DataTableNode", {"kind": "DataTableNode", "source": {"kind": "EventsQuery"}}),
            # Bare data node kinds — legacy notebooks set these directly as the top-level query.
            ("HogQLQuery", HOGQL_SOURCE),
            ("EventsQuery", {"kind": "EventsQuery", "select": ["*"]}),
        ]
    )
    def test_passes_through_other_known_kinds(self, _name: str, query: dict) -> None:
        assert _extract_query(normalize_notebook_query_nodes(_wrap(query))) == query

    def test_passes_through_query_without_kind(self) -> None:
        # Older notebooks may have hand-crafted query attrs without a discriminator.
        doc = _wrap({"foo": "bar"})
        assert _extract_query(normalize_notebook_query_nodes(doc)) == {"foo": "bar"}

    def test_walks_nested_content(self) -> None:
        bad = {"kind": "InsightVizNode", "source": VALID_DATA_VIZ}
        nested = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "ph-query", "attrs": {"nodeId": "deep", "query": bad}},
                            ],
                        },
                    ],
                },
            ],
        }
        result = normalize_notebook_query_nodes(nested)
        deep_node = result["content"][0]["content"][0]["content"][0]
        assert deep_node["attrs"]["query"] == VALID_DATA_VIZ

    def test_does_not_mutate_input(self) -> None:
        bad = {"kind": "InsightVizNode", "source": VALID_DATA_VIZ}
        doc = _wrap(bad)
        original_query = doc["content"][0]["attrs"]["query"]
        normalize_notebook_query_nodes(doc)
        # Original object reference unchanged
        assert doc["content"][0]["attrs"]["query"] is original_query
        assert doc["content"][0]["attrs"]["query"]["kind"] == "InsightVizNode"

    def test_multiple_ph_query_nodes_handled_independently(self) -> None:
        bad = {"kind": "InsightVizNode", "source": VALID_DATA_VIZ}
        doc = {
            "type": "doc",
            "content": [
                {"type": "ph-query", "attrs": {"nodeId": "a", "query": bad}},
                {"type": "paragraph"},
                {"type": "ph-query", "attrs": {"nodeId": "b", "query": VALID_INSIGHT_VIZ}},
            ],
        }
        result = normalize_notebook_query_nodes(doc)
        assert result["content"][0]["attrs"]["query"] == VALID_DATA_VIZ
        assert result["content"][2]["attrs"]["query"] == VALID_INSIGHT_VIZ
