import json
from typing import Any

from django.db.models import F

from posthog.models.cohortmembership.query_rewrite import (
    SavedQueryRewrite,
    SqlRewrite,
    rewrite_query_nodes,
    rewrite_saved_rows,
)

from .markdown_collab import get_markdown_notebook_markdown, publish_notebook_update
from .models import Notebook
from .util import QUERY_NODE_TYPE, _coerce_query_attr, iter_markdown_query_nodes, iter_prosemirror_nodes


def _rewrite_content(content: Any) -> tuple[Any, list[SqlRewrite]]:
    markdown = get_markdown_notebook_markdown(content)
    if markdown is not None:
        return _rewrite_markdown(content, markdown)
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


def _rewrite_markdown(content: dict[str, Any], markdown: str) -> tuple[Any, list[SqlRewrite]]:
    """Replaces each rewritten SQL string in its JSON-encoded form, so the rest of the markdown stays as written."""
    rewrites: list[SqlRewrite] = []
    spliced: set[str] = set()
    for _node_id, query in iter_markdown_query_nodes(content):
        for rewrite in rewrite_query_nodes(query)[1]:
            if rewrite.after is not None and rewrite.before not in spliced:
                next_markdown = _splice_sql(markdown, rewrite.before, rewrite.after)
                if next_markdown is None:
                    rewrite = SqlRewrite(before=rewrite.before, after=None)
                else:
                    markdown = next_markdown
                    spliced.add(rewrite.before)
            rewrites.append(rewrite)
    if not spliced:
        return content, rewrites
    [node] = content["content"]
    return {**content, "content": [{**node, "attrs": {**node["attrs"], "markdown": markdown}}]}, rewrites


def _splice_sql(markdown: str, before: str, after: str) -> str | None:
    """`query={...}` holds the SQL as a JSON string, and `query="..."` holds that JSON once more as a string."""
    for encode in (_json_string, lambda sql: _json_string(_json_string(sql))[1:-1]):
        if encode(before) in markdown:
            return markdown.replace(encode(before), encode(after))
    return None


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def rewrite_cohort_membership_queries(team_id: int, apply: bool) -> list[SavedQueryRewrite]:
    results = rewrite_saved_rows(
        Notebook._base_manager.filter(team_id=team_id),
        "content",
        "notebook",
        _rewrite_content,
        apply,
        # An editor holding the old version then gets a conflict instead of saving over the rewrite.
        extra_updates=lambda: {"version": F("version") + 1},
    )
    # Collaborative editors check their version against the stream, not Postgres, so they need the new version
    # there too, the same as after a save through the API.
    written = [row.pk for row in results if row.written]
    for short_id, version in Notebook._base_manager.filter(pk__in=written).values_list("short_id", "version"):
        publish_notebook_update(team_id, short_id, version)
    return results
