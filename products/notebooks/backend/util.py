import json
import uuid
from collections.abc import Iterator
from typing import Any

# Type aliases for TipTap editor nodes
TipTapNode = dict[str, Any]
TipTapContent = list[TipTapNode]

# ProseMirror node type used by NotebookNodeQuery on the frontend.
# Keep in sync with `NotebookNodeType.Query` in frontend/src/scenes/notebooks/types.ts.
QUERY_NODE_TYPE = "ph-query"
# QuerySchema kind that points at a saved insight by its short_id.
SAVED_INSIGHT_NODE_KIND = "SavedInsightNode"


def _coerce_query_attr(raw: Any) -> dict | None:
    """Resolve a notebook ph-query node's `query` attribute to a dict.

    Notebooks save attrs through tiptap, which can serialize complex attrs as JSON strings
    (the `jsonAttr` wrapper in `NodeWrapper.tsx` round-trips through `JSON.stringify` /
    `JSON.parse`). Older notebooks were also saved with stringified queries before the
    `convertInsightQueryStringsToObjects` frontend migration normalized them. Accept either form.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def iter_prosemirror_nodes(doc: Any) -> Iterator[TipTapNode]:
    """Yield every node in a ProseMirror document, depth-first.

    Tolerates malformed input — anything that isn't a dict with a `content` list is skipped.
    """
    if not isinstance(doc, dict):
        return
    yield doc
    children = doc.get("content")
    if not isinstance(children, list):
        return
    for child in children:
        yield from iter_prosemirror_nodes(child)


def extract_referenced_insight_short_ids(content: Any) -> set[str]:
    """Walk a notebook's ProseMirror document and collect every saved-insight short_id it embeds.

    Only ``ph-query`` nodes whose query is a ``SavedInsightNode`` reference an insight by id.
    Inline (ad-hoc) queries store the full query in node attrs — see
    :func:`extract_inline_query_nodes` for those.
    """
    short_ids: set[str] = set()
    for node in iter_prosemirror_nodes(content):
        if node.get("type") != QUERY_NODE_TYPE:
            continue
        attrs = node.get("attrs")
        if not isinstance(attrs, dict):
            continue
        query = _coerce_query_attr(attrs.get("query"))
        if query is None:
            continue
        if query.get("kind") != SAVED_INSIGHT_NODE_KIND:
            continue
        short_id = query.get("shortId")
        if isinstance(short_id, str) and short_id:
            short_ids.add(short_id)
    return short_ids


def extract_inline_query_nodes(content: Any) -> list[tuple[str, dict]]:
    """Walk a notebook's ProseMirror document and collect every inline (non-saved-insight) query.

    Returns a list of ``(nodeId, query_dict)`` pairs. Used by the shared-notebook payload
    builder to pre-compute results for ad-hoc queries (DataTableNode, HogQLQuery, InsightVizNode
    without a saved insight reference, etc.) so the shared viewer can render them without
    POSTing to ``/api/projects/<id>/query/`` — a path sharing tokens cannot reach.

    Saved insights are deliberately excluded; they go through
    :func:`extract_referenced_insight_short_ids` and the existing
    ``InsightSerializer`` shared-mode path.

    Nodes whose ``nodeId`` is missing are skipped; without it the frontend has no key to look
    the cached result up by, so we'd risk attaching the wrong result to the wrong node.
    """
    inline_nodes: list[tuple[str, dict]] = []
    for node in iter_prosemirror_nodes(content):
        if node.get("type") != QUERY_NODE_TYPE:
            continue
        attrs = node.get("attrs")
        if not isinstance(attrs, dict):
            continue
        query = _coerce_query_attr(attrs.get("query"))
        if query is None:
            continue
        if query.get("kind") == SAVED_INSIGHT_NODE_KIND:
            continue
        node_id = attrs.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            continue
        inline_nodes.append((node_id, query))
    return inline_nodes


def create_bullet_list(items: list[str] | list[TipTapContent] | TipTapContent) -> TipTapNode:
    """Create a bullet list with list items. Items can be strings or content arrays."""
    list_items = []
    for item in items:
        if isinstance(item, str):
            list_items.append({"type": "listItem", "content": [create_paragraph_with_text(item)]})
        elif isinstance(item, list):
            # item is already a content array (could be paragraph + nested list)
            list_items.append({"type": "listItem", "content": item})
        else:
            # item is a single content node
            list_items.append({"type": "listItem", "content": [create_paragraph_with_content([item])]})

    return {"type": "bulletList", "content": list_items}


def create_heading_with_text(text: str, level: int, *, collapsed: bool = False) -> TipTapNode:
    """Create a heading node with sanitized text content."""
    heading_id = str(uuid.uuid4())
    return {
        "type": "heading",
        "attrs": {"id": heading_id, "level": level, "data-toc-id": heading_id, "collapsed": collapsed},
        "content": [{"type": "text", "text": sanitize_text_content(text)}],
    }


def create_paragraph_with_text(text: str, marks: list[dict[str, Any]] | None = None) -> TipTapNode:
    """Create a paragraph node with sanitized text content and optional marks."""
    content_node: dict[str, Any] = {"type": "text", "text": sanitize_text_content(text)}
    if marks:
        content_node["marks"] = marks
    return {
        "type": "paragraph",
        "content": [content_node],
    }


def create_paragraph_with_content(content: TipTapContent) -> TipTapNode:
    """Create a paragraph node with a list of content items."""
    return {
        "type": "paragraph",
        "content": content,
    }


def create_text_content(text: str, is_bold: bool = False, is_italic: bool = False) -> TipTapNode:
    """Create a text node with optional marks."""
    node: dict[str, Any] = {"type": "text", "text": text}
    marks = []
    if is_bold:
        marks.append({"type": "bold"})
    if is_italic:
        marks.append({"type": "italic"})
    if marks:
        node["marks"] = marks
    return node


def create_empty_paragraph() -> TipTapNode:
    """Create a paragraph node with no content to add spacing."""
    return {"type": "paragraph"}


def create_task_list(items: list[tuple[str, bool]]) -> TipTapNode:
    """Create a bullet list with checkbox-style items.

    Args:
        items: List of tuples (task_text, is_completed)
    """
    list_items = []
    for task_text, is_completed in items:
        checkbox = "[x]" if is_completed else "[ ]"
        task_content = f"{checkbox} {task_text}"
        list_items.append({"type": "listItem", "content": [create_paragraph_with_text(task_content)]})

    return {"type": "bulletList", "content": list_items}


def sanitize_text_content(text: str) -> str:
    """Sanitize text content to ensure it's valid for TipTap editor."""
    if not text or not text.strip():
        raise ValueError("Empty text should not be passed to create heading or paragraph")
    return text.strip()
