import json
from typing import Any

from django.db.models import F

from posthog.hogql.cohort_membership_rewrite import (
    SavedQueryRewrite,
    SqlRewrite,
    rewrite_query_nodes,
    rewrite_saved_rows,
)

from .models import Notebook
from .util import QUERY_NODE_TYPE, _coerce_query_attr, iter_prosemirror_nodes


def _rewrite_content(content: Any) -> tuple[Any, list[SqlRewrite]]:
    rewritten, rewrites = rewrite_query_nodes(content)
    # Tiptap can store a `ph-query` node's query as a JSON string, which `rewrite_query_nodes` does not open.
    for node in iter_prosemirror_nodes(rewritten):
        attrs = node.get("attrs")
        if (
            node.get("type") != QUERY_NODE_TYPE
            or not isinstance(attrs, dict)
            or not isinstance(attrs.get("query"), str)
        ):
            continue
        query = _coerce_query_attr(attrs["query"])
        if query is None:
            continue
        rewritten_query, query_rewrites = rewrite_query_nodes(query)
        rewrites.extend(query_rewrites)
        if any(not rewrite.needs_manual_fix for rewrite in query_rewrites):
            attrs["query"] = json.dumps(rewritten_query)
    return rewritten, rewrites


def rewrite_cohort_membership_queries(team_id: int, apply: bool) -> list[SavedQueryRewrite]:
    return rewrite_saved_rows(
        Notebook._base_manager.filter(team_id=team_id),
        "content",
        "notebook",
        _rewrite_content,
        apply,
        # An editor holding the old version then gets a conflict instead of saving over the rewrite.
        extra_updates=lambda: {"version": F("version") + 1},
    )
