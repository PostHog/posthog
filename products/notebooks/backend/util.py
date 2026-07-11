import re
import html
import json
import uuid
from collections.abc import Iterator
from typing import Any

# Type aliases for TipTap editor nodes
TipTapNode = dict[str, Any]
TipTapContent = list[TipTapNode]

# ProseMirror node type used by Markdown notebooks.
# Keep in sync with `NotebookNodeType.MarkdownNotebook` in frontend/src/scenes/notebooks/types.ts.
MARKDOWN_NOTEBOOK_NODE_TYPE = "ph-markdown-notebook"
# ProseMirror node type used by NotebookNodeQuery on the frontend.
# Keep in sync with `NotebookNodeType.Query` in frontend/src/scenes/notebooks/types.ts.
QUERY_NODE_TYPE = "ph-query"
# QuerySchema kind that points at a saved insight by its short_id.
SAVED_INSIGHT_NODE_KIND = "SavedInsightNode"
MARKDOWN_QUERY_TAG = "Query"

# Keep in sync with `SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES` in
# `frontend/src/scenes/notebooks/Nodes/sharedNodeSupport.tsx`.
SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES: frozenset[str] = frozenset(
    {
        "ph-image",
        "ph-latex",
        "ph-embed",
        "ph-query",
    }
)

SHARED_NOTEBOOK_SUPPORTED_MARKDOWN_COMPONENT_TAGS: frozenset[str] = frozenset(
    {
        "Comment",
        "Divider",
        "Embed",
        "Image",
        "Latex",
        "PythonV2",
        "Query",
        "SQLV2",
    }
)

_SHARED_NOTEBOOK_MARKDOWN_COMPONENT_PROP_TYPES: dict[str, dict[str, type | tuple[type, ...]]] = {
    "Comment": {"ref": str, "replies": list, "text": str},
    "Divider": {},
    "Embed": {"height": (int, float), "src": str, "title": str, "width": (int, float)},
    "Image": {"alt": str, "height": (int, float), "src": str, "title": str, "width": (int, float)},
    "Latex": {"content": str, "editing": bool, "title": str},
    # The V2 cells render their persisted `result` envelope read-only in shared view — the
    # walkthrough's "last saved result, no kernel". `runId` is deliberately absent: sharing
    # tokens cannot reach the run endpoints, and stripping it keeps shared clients from
    # ever polling. InputV2 stays unsupported (it exists to execute kernel code).
    "PythonV2": {
        "code": str,
        "height": (int, float),
        "nodeId": str,
        "result": dict,
        "returnVariable": str,
        "title": str,
    },
    "Query": {
        "hideFilters": bool,
        "hideResults": bool,
        "height": (int, float),
        "isDefaultFilterApplied": bool,
        "nodeId": str,
        "outputTab": str,
        "query": dict,
        "showSettings": bool,
        "title": str,
    },
    "SQLV2": {
        "code": str,
        "height": (int, float),
        "nodeId": str,
        "outputTab": str,
        "result": dict,
        "returnVariable": str,
        "title": str,
        "vizQuery": dict,
    },
}

_MARKDOWN_COMPONENT_START_REGEX = re.compile(r"^<[A-Z][A-Za-z0-9]*(\s|>|/)")
_MARKDOWN_COMPONENT_TAG_REGEX = re.compile(r"^<([A-Z][A-Za-z0-9]*)([\s\S]*?)(?:/>|>[\s\S]*</\1>)$")
_MARKDOWN_COMPONENT_PROP_NAME_REGEX = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)")
_MARKDOWN_COMPONENT_RAW_PROP_VALUE_REGEX = re.compile(r"^([^\s/>]+)")
_MARKDOWN_COMPONENT_NUMBER_REGEX = re.compile(r"^-?\d+(\.\d+)?$")


def filter_notebook_content_for_sharing(content: Any) -> Any:
    """Return a copy of a notebook's ProseMirror document with unsupported widget nodes redacted.

    Any ``ph-*`` node not in :data:`SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES` has its ``attrs`` and
    child ``content`` stripped. The original ``type`` is preserved so the frontend's allow-list
    check still renders ``UnsupportedNodePlaceholder`` without leaking the original attrs to
    anonymous viewers. Built-in ProseMirror nodes pass through unchanged.
    """
    if not isinstance(content, dict):
        return content

    node_type = content.get("type")
    if node_type == MARKDOWN_NOTEBOOK_NODE_TYPE:
        return _filter_markdown_notebook_content_for_sharing(content)

    if (
        isinstance(node_type, str)
        and node_type.startswith("ph-")
        and node_type not in SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES
    ):
        return {"type": node_type}

    filtered: dict[str, Any] = {k: v for k, v in content.items() if k != "content"}
    children = content.get("content")
    if isinstance(children, list):
        filtered["content"] = [_filter_notebook_child_content_for_sharing(child) for child in children]
    elif "content" in content:
        filtered["content"] = children
    return filtered


def _filter_notebook_child_content_for_sharing(child: Any) -> Any:
    if isinstance(child, dict) and child.get("type") == MARKDOWN_NOTEBOOK_NODE_TYPE:
        return _filter_markdown_notebook_content_for_sharing(child)
    return filter_notebook_content_for_sharing(child)


def _filter_markdown_notebook_content_for_sharing(content: TipTapNode) -> TipTapNode:
    attrs = content.get("attrs")
    if not isinstance(attrs, dict):
        return {"type": MARKDOWN_NOTEBOOK_NODE_TYPE}

    filtered_attrs: dict[str, Any] = {}
    node_id = attrs.get("nodeId")
    if isinstance(node_id, str):
        filtered_attrs["nodeId"] = node_id

    markdown = attrs.get("markdown")
    if isinstance(markdown, str):
        filtered_attrs["markdown"] = _filter_markdown_components_for_sharing(markdown)

    return {"type": MARKDOWN_NOTEBOOK_NODE_TYPE, "attrs": filtered_attrs}


def _filter_markdown_components_for_sharing(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    filtered_lines: list[str] = []
    line_index = 0

    while line_index < len(lines):
        if lines[line_index].strip().startswith("```"):
            code_block_end = _get_markdown_code_block_end(lines, line_index)
            filtered_lines.extend(lines[line_index:code_block_end])
            line_index = code_block_end
            continue

        component = _read_markdown_component_block(lines, line_index)
        if component is None:
            filtered_lines.append(lines[line_index])
            line_index += 1
            continue

        tag_name, _raw, next_line_index = component
        if tag_name in SHARED_NOTEBOOK_SUPPORTED_MARKDOWN_COMPONENT_TAGS:
            filtered_lines.append(_filter_supported_markdown_component_for_sharing(tag_name, _raw))
        else:
            filtered_lines.append(f"<{tag_name} />")
        line_index = next_line_index

    return "\n".join(filtered_lines)


def _filter_supported_markdown_component_for_sharing(tag_name: str, raw: str) -> str:
    supported_props = _SHARED_NOTEBOOK_MARKDOWN_COMPONENT_PROP_TYPES[tag_name]
    props = _parse_markdown_component_props(raw)
    filtered_props: dict[str, Any] = {}

    for prop_name, expected_type in supported_props.items():
        value = props.get(prop_name)
        if _is_markdown_component_prop_type(value, expected_type):
            filtered_props[prop_name] = value

    return _serialize_markdown_component(tag_name, filtered_props)


def _is_markdown_component_prop_type(value: Any, expected_type: type | tuple[type, ...]) -> bool:
    if isinstance(value, bool):
        return expected_type is bool or (isinstance(expected_type, tuple) and bool in expected_type)
    if isinstance(value, expected_type):
        return True
    return False


def _serialize_markdown_component(tag_name: str, props: dict[str, Any]) -> str:
    prop_source = "".join(
        _serialize_markdown_component_prop(name, props[name])
        for name in _SHARED_NOTEBOOK_MARKDOWN_COMPONENT_PROP_TYPES[tag_name]
        if name in props
    )
    return f"<{tag_name}{prop_source} />"


def _serialize_markdown_component_prop(name: str, value: Any) -> str:
    if value is True:
        return f" {name}"
    if isinstance(value, str):
        return f" {name}={json.dumps(value, ensure_ascii=False)}"
    return f" {name}={{{json.dumps(value, ensure_ascii=False, separators=(',', ':'))}}}"


def _coerce_query_attr(raw: Any) -> dict[str, Any] | None:
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
    for _node_id, query in iter_markdown_query_nodes(content):
        if query.get("kind") != SAVED_INSIGHT_NODE_KIND:
            continue
        short_id = query.get("shortId")
        if isinstance(short_id, str) and short_id:
            short_ids.add(short_id)
    return short_ids


def extract_inline_query_nodes(content: Any) -> list[tuple[str, dict[str, Any]]]:
    """Walk a notebook's ProseMirror document and collect every inline (non-saved-insight) query.

    Returns a list of ``(nodeId, query_dict)`` pairs. Used by the shared-notebook payload
    builder to pre-compute results for ad-hoc queries (DataTableNode, HogQLQuery, InsightVizNode
    without a saved insight reference, etc.) so the shared viewer can render them without
    POSTing to ``/api/projects/<id>/query/`` — a path sharing tokens cannot reach.

    Saved insights are deliberately excluded; they go through
    :func:`extract_referenced_insight_short_ids` and the existing
    ``InsightSerializer`` shared-mode path.

    Legacy ProseMirror ``ph-query`` nodes whose ``nodeId`` is missing are skipped; without it
    the frontend has no key to look the cached result up by. Markdown ``<Query>`` components
    without an explicit ``nodeId`` instead receive a content-derived stable ID (see
    :func:`iter_markdown_query_nodes`).
    """
    inline_nodes: list[tuple[str, dict[str, Any]]] = []
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
    for node_id, query in iter_markdown_query_nodes(content):
        if query.get("kind") == SAVED_INSIGHT_NODE_KIND:
            continue
        inline_nodes.append((node_id, query))
    return inline_nodes


def iter_markdown_query_nodes(content: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    markdown = _get_markdown_notebook_markdown(content)
    if markdown is None:
        return

    occurrences: dict[str, int] = {}
    for tag_name, raw, _next_line_index in _iter_markdown_component_blocks(markdown):
        if tag_name != MARKDOWN_QUERY_TAG:
            continue

        props = _parse_markdown_component_props(raw)
        fingerprint = _get_markdown_component_fingerprint(tag_name, props)
        occurrence = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = occurrence + 1

        query = _coerce_query_attr(props.get("query"))
        if query is None:
            continue

        explicit_node_id = props.get("nodeId")
        node_id = (
            explicit_node_id
            if isinstance(explicit_node_id, str) and explicit_node_id
            else _create_stable_markdown_node_id(fingerprint, occurrence)
        )
        yield node_id, query


def _get_markdown_notebook_markdown(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None

    nodes = content.get("content")
    if not isinstance(nodes, list) or len(nodes) != 1:
        return None

    node = nodes[0]
    if not isinstance(node, dict) or node.get("type") != MARKDOWN_NOTEBOOK_NODE_TYPE:
        return None

    attrs = node.get("attrs")
    markdown = attrs.get("markdown") if isinstance(attrs, dict) else None
    return markdown if isinstance(markdown, str) else None


def _iter_markdown_component_blocks(markdown: str) -> Iterator[tuple[str, str, int]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    line_index = 0

    while line_index < len(lines):
        if lines[line_index].strip().startswith("```"):
            line_index = _get_markdown_code_block_end(lines, line_index)
            continue

        component = _read_markdown_component_block(lines, line_index)
        if component is None:
            line_index += 1
            continue

        yield component
        line_index = component[2]


def _get_markdown_code_block_end(lines: list[str], line_index: int) -> int:
    next_line_index = line_index + 1
    while next_line_index < len(lines):
        if lines[next_line_index].strip().startswith("```"):
            return next_line_index + 1
        next_line_index += 1
    return next_line_index


def _read_markdown_component_block(lines: list[str], line_index: int) -> tuple[str, str, int] | None:
    first_line = lines[line_index].strip()
    if not _MARKDOWN_COMPONENT_START_REGEX.match(first_line):
        return None

    tag_match = re.match(r"^<([A-Z][A-Za-z0-9]*)", first_line)
    tag_name = tag_match.group(1) if tag_match else None
    if not tag_name:
        return None

    raw_lines: list[str] = []
    next_line_index = line_index
    found_terminator = False
    while next_line_index < len(lines) and (next_line_index == line_index or lines[next_line_index].strip()):
        raw_lines.append(lines[next_line_index])
        raw = "\n".join(raw_lines).strip()
        if raw.endswith("/>") or f"</{tag_name}>" in raw:
            found_terminator = True
            break
        next_line_index += 1

    if not found_terminator:
        return None

    return tag_name, "\n".join(raw_lines).strip(), next_line_index + 1


def _parse_markdown_component_props(raw: str) -> dict[str, Any]:
    match = _MARKDOWN_COMPONENT_TAG_REGEX.match(raw)
    if not match:
        return {}

    props: dict[str, Any] = {}
    source = match.group(2) or ""
    index = 0
    while index < len(source):
        while index < len(source) and source[index].isspace():
            index += 1
        if index >= len(source):
            break

        name_match = _MARKDOWN_COMPONENT_PROP_NAME_REGEX.match(source[index:])
        if not name_match:
            break

        name = name_match.group(1)
        index += len(name)
        while index < len(source) and source[index].isspace():
            index += 1

        if index >= len(source) or source[index] != "=":
            props[name] = True
            continue

        index += 1
        while index < len(source) and source[index].isspace():
            index += 1

        value, index = _read_markdown_component_prop_value(source, index)
        if _is_markdown_notebook_prop_value(value):
            props[name] = value

    return props


def _read_markdown_component_prop_value(source: str, index: int) -> tuple[Any, int]:
    first_char = source[index] if index < len(source) else ""

    if first_char in {"'", '"'}:
        quote = first_char
        next_index = index + 1
        value = ""
        while next_index < len(source):
            character = source[next_index]
            if character == "\\" and next_index + 1 < len(source):
                value += source[next_index + 1]
                next_index += 2
                continue
            if character == quote:
                if quote == '"':
                    try:
                        parsed_value = json.loads(source[index : next_index + 1])
                        if isinstance(parsed_value, str):
                            return html.unescape(parsed_value), next_index + 1
                    except (TypeError, ValueError):
                        pass
                return html.unescape(value), next_index + 1
            value += character
            next_index += 1
        return None, next_index

    if first_char == "{":
        balanced = _read_balanced_markdown_expression(source, index)
        if balanced is None:
            return None, len(source)
        value, next_index = balanced
        return _parse_markdown_expression_value(value), next_index

    raw_match = _MARKDOWN_COMPONENT_RAW_PROP_VALUE_REGEX.match(source[index:])
    raw = raw_match.group(1) if raw_match else ""
    return _parse_markdown_expression_value(raw), index + len(raw)


def _read_balanced_markdown_expression(source: str, index: int) -> tuple[str, int] | None:
    depth = 0
    next_index = index
    quote: str | None = None

    while next_index < len(source):
        character = source[next_index]
        if quote:
            if character == quote and not _is_escaped_markdown_expression_quote(source, next_index):
                quote = None
            next_index += 1
            continue

        if character in {"'", '"'}:
            quote = character
            next_index += 1
            continue

        if character == "{":
            depth += 1
        if character == "}":
            depth -= 1
            if depth == 0:
                return source[index : next_index + 1], next_index + 1
        next_index += 1

    return None


def _is_escaped_markdown_expression_quote(source: str, quote_index: int) -> bool:
    backslash_count = 0
    index = quote_index - 1
    while index >= 0 and source[index] == "\\":
        backslash_count += 1
        index -= 1
    return backslash_count % 2 == 1


def _parse_markdown_expression_value(raw: str) -> Any:
    trimmed = raw.strip()
    unwrapped = trimmed[1:-1].strip() if trimmed.startswith("{") and trimmed.endswith("}") else trimmed

    if unwrapped == "true":
        return True
    if unwrapped == "false":
        return False
    if unwrapped == "null":
        return None
    if _MARKDOWN_COMPONENT_NUMBER_REGEX.match(unwrapped):
        return float(unwrapped) if "." in unwrapped else int(unwrapped)

    try:
        return json.loads(unwrapped)
    except (TypeError, ValueError):
        return trimmed


def _is_markdown_notebook_prop_value(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_is_markdown_notebook_prop_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_markdown_notebook_prop_value(item) for key, item in value.items())
    return False


def _get_markdown_component_fingerprint(tag_name: str, props: dict[str, Any]) -> str:
    return json.dumps(
        {"type": "component", "tagName": tag_name, "props": _sort_markdown_component_props(props)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sort_markdown_component_props(props: dict[str, Any]) -> dict[str, Any]:
    return {key: _sort_markdown_component_prop_value(props[key]) for key in sorted(props)}


def _sort_markdown_component_prop_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_sort_markdown_component_prop_value(item) for item in value]
    if isinstance(value, dict):
        return _sort_markdown_component_props(value)
    return value


def _create_stable_markdown_node_id(fingerprint: str, occurrence: int) -> str:
    return f"mdn-{_hash_markdown_node_id_seed(fingerprint)}-{occurrence}"


def _hash_markdown_node_id_seed(value: str) -> str:
    hash_value = 5381
    encoded = value.encode("utf-16-le", "surrogatepass")
    for index in range(0, len(encoded), 2):
        code_unit = encoded[index] | (encoded[index + 1] << 8)
        hash_value = ((hash_value * 33) ^ code_unit) & 0xFFFFFFFF
    return _to_base36(hash_value)


def _to_base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result


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
