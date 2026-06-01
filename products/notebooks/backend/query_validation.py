from typing import Any

import structlog

logger = structlog.get_logger(__name__)


PH_QUERY_NODE_TYPE = "ph-query"

# Kinds the frontend's NotebookNodeQuery accepts as a top-level `attrs.query`.
# Anything else inside a ph-query node is almost certainly a programmatic mistake — an AI
# agent producing notebook content via the MCP API has no Pydantic guard between it and
# storage, so we apply one here.
_VALID_TOP_LEVEL_QUERY_KINDS = frozenset(
    {
        "DataVisualizationNode",
        "DataTableNode",
        "SavedInsightNode",
        "InsightVizNode",
    }
)

# Source kinds that an InsightVizNode is actually allowed to wrap (matches the Pydantic
# schema at posthog/schema.py — InsightVizNode.source).
_VALID_INSIGHT_VIZ_SOURCE_KINDS = frozenset(
    {
        "TrendsQuery",
        "FunnelsQuery",
        "RetentionQuery",
        "PathsQuery",
        "StickinessQuery",
        "LifecycleQuery",
        "WebStatsTableQuery",
        "WebOverviewQuery",
    }
)


class InvalidNotebookQueryError(ValueError):
    """Raised when a ph-query node carries a query shape we can't safely store.

    The message is exposed to the API caller (and therefore to AI agents constructing
    notebook content), so it must spell out the expected shape clearly enough for the
    caller to fix on retry.
    """


def normalize_notebook_query_nodes(content: Any) -> Any:
    """Walk a ProseMirror notebook document and validate every ph-query node.

    For known, recoverable LLM mistakes (e.g. wrapping a SQL chart in an InsightVizNode)
    we auto-correct in place and log. For anything else that fails validation, we raise
    InvalidNotebookQueryError so the write is rejected with a helpful message.

    The function is structure-preserving: it returns a new tree with corrections applied,
    leaves nodes that aren't ph-query untouched, and is a no-op if `content` is not a dict.
    """
    if not isinstance(content, dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        if node.get("type") == PH_QUERY_NODE_TYPE:
            attrs = node.get("attrs")
            if isinstance(attrs, dict) and "query" in attrs:
                normalized_query = _normalize_query(attrs["query"])
                if normalized_query is not attrs["query"]:
                    node = {**node, "attrs": {**attrs, "query": normalized_query}}

        children = node.get("content")
        if isinstance(children, list):
            node = {**node, "content": [walk(child) for child in children]}

        return node

    return walk(content)


def _normalize_query(query: Any) -> Any:
    if not isinstance(query, dict):
        return query

    kind = query.get("kind")
    if not isinstance(kind, str):
        # No kind — likely a legacy or hand-crafted node. Leave it alone; older notebooks
        # may rely on the frontend's tolerant handling and we don't want to break them.
        return query

    if kind == "InsightVizNode":
        return _normalize_insight_viz_node(query)

    if kind == "DataVisualizationNode":
        return _normalize_data_visualization_node(query)

    if kind not in _VALID_TOP_LEVEL_QUERY_KINDS:
        # Other QuerySchema kinds (HogQLQuery, EventsQuery, ...) can be used as a top-level
        # `attrs.query` in some legacy notebooks, so we don't reject — but we also don't
        # try to auto-fix.
        return query

    return query


def _normalize_insight_viz_node(query: dict[str, Any]) -> dict[str, Any]:
    source = query.get("source")
    if not isinstance(source, dict):
        raise InvalidNotebookQueryError(
            "ph-query node has an InsightVizNode without a `source`. "
            "InsightVizNode.source must be a TrendsQuery, FunnelsQuery, RetentionQuery, "
            "PathsQuery, StickinessQuery, LifecycleQuery, WebStatsTableQuery, or WebOverviewQuery."
        )

    source_kind = source.get("kind")

    if source_kind == "DataVisualizationNode":
        # This is the bug we keep seeing from AI agents: a SQL chart got wrapped in an
        # InsightVizNode (which is only valid for product-analytics insights). The inner
        # DataVisualizationNode is already the correct top-level shape, so unwrap it.
        logger.warning(
            "notebook_query_auto_unwrapped_insight_viz_node",
            reason="InsightVizNode wrapping DataVisualizationNode",
        )
        return _normalize_data_visualization_node(source)

    if source_kind == "HogQLQuery":
        # Same shape of mistake, one level up: agent wrapped a raw HogQLQuery in an
        # InsightVizNode. The correct shell for a SQL chart is DataVisualizationNode.
        logger.warning(
            "notebook_query_auto_rewrapped_hogql_query",
            reason="InsightVizNode wrapping HogQLQuery",
        )
        return {"kind": "DataVisualizationNode", "source": source}

    if source_kind not in _VALID_INSIGHT_VIZ_SOURCE_KINDS:
        raise InvalidNotebookQueryError(
            f"ph-query node has an InsightVizNode wrapping `{source_kind}`, which is not "
            "a valid insight source. InsightVizNode.source must be one of: "
            f"{', '.join(sorted(_VALID_INSIGHT_VIZ_SOURCE_KINDS))}."
        )

    return query


def _normalize_data_visualization_node(query: dict[str, Any]) -> dict[str, Any]:
    source = query.get("source")
    if not isinstance(source, dict):
        raise InvalidNotebookQueryError(
            "ph-query node has a DataVisualizationNode without a `source`. "
            "DataVisualizationNode.source must be a HogQLQuery."
        )

    source_kind = source.get("kind")
    if source_kind != "HogQLQuery":
        raise InvalidNotebookQueryError(
            f"ph-query node has a DataVisualizationNode wrapping `{source_kind}`, which "
            "is not a valid SQL chart source. DataVisualizationNode.source must be a HogQLQuery."
        )

    return query
