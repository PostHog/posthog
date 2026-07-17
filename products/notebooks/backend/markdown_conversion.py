import re
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

MARKDOWN_NOTEBOOK_NODE_TYPE = "ph-markdown-notebook"
MARKDOWN_NOTEBOOK_NODE_ID = "markdown-notebook-v2"
MENTION_NODE_TYPE = "ph-mention"

NotebookPropValue = str | int | float | bool | None | list["NotebookPropValue"] | dict[str, "NotebookPropValue"]
JSONContent = dict[str, Any]

NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG: Mapping[str, str] = {
    "ph-query": "Query",
    "ph-python": "Python",
    "ph-duck-sql": "DuckSQL",
    "ph-hogql-sql": "HogQLSQL",
    "ph-recording": "Recording",
    "ph-recording-playlist": "RecordingPlaylist",
    "ph-feature-flag": "FeatureFlag",
    "ph-feature-flag-code-example": "FeatureFlagCodeExample",
    "ph-experiment": "Experiment",
    "ph-early-access-feature": "EarlyAccessFeature",
    "ph-survey": "Survey",
    "ph-person": "Person",
    "ph-group": "Group",
    "ph-cohort": "Cohort",
    "ph-backlink": "Backlink",
    "ph-replay-timestamp": "ReplayTimestamp",
    "ph-image": "Image",
    "ph-person-feed": "PersonFeed",
    "ph-person-properties": "PersonProperties",
    "ph-group-properties": "GroupProperties",
    "ph-map": "Map",
    "ph-embed": "Embed",
    "ph-latex": "Latex",
    "ph-task-create": "TaskCreate",
    "ph-llm-trace": "LLMTrace",
    "ph-issues": "Issues",
    "ph-usage-metrics": "UsageMetrics",
    "ph-zendesk-tickets": "ZendeskTickets",
    "ph-related-groups": "RelatedGroups",
    "ph-customer-journey": "CustomerJourney",
    "ph-support-tickets": "SupportTickets",
}

RICH_CONTENT_NODE_TYPE_ALIASES: Mapping[str, str] = {
    "bullet_list": "bulletList",
    "ordered_list": "orderedList",
    "list_item": "listItem",
    "code_block": "codeBlock",
    "table_row": "tableRow",
    "table_cell": "tableCell",
    "table_header": "tableHeader",
}

LIST_NODE_TYPES = {"bulletList", "orderedList", "taskList"}
LIST_ITEM_NODE_TYPES = {"listItem", "taskItem"}
_SERIALIZATION_OMIT = object()


@dataclass(frozen=True)
class NotebookMarkdownConversionOptions:
    comment_replies_by_mark_id: Mapping[str, list[NotebookPropValue]] | None = None
    get_mention_label: Callable[[int], str | None] | None = None


def is_markdown_notebook_content(content: Any) -> bool:
    return _get_markdown_notebook_node(content) is not None


def get_markdown_notebook_markdown(content: Any) -> str:
    node = _get_markdown_notebook_node(content)
    if node is None:
        return ""
    attrs = node.get("attrs")
    if not isinstance(attrs, dict):
        return ""
    markdown = attrs.get("markdown")
    return markdown if isinstance(markdown, str) else ""


def notebook_content_has_comment_marks(content: Any) -> bool:
    normalized_content = _normalize_notebook_content_for_markdown_conversion(content)
    if isinstance(normalized_content, str):
        return False
    return any(_collect_comment_mark_ids(node) for node in _content_list(normalized_content))


def build_markdown_notebook_content(markdown: str, node_id: str = MARKDOWN_NOTEBOOK_NODE_ID) -> JSONContent:
    return {
        "type": "doc",
        "content": [
            {
                "type": MARKDOWN_NOTEBOOK_NODE_TYPE,
                "attrs": {
                    "nodeId": node_id,
                    "markdown": markdown,
                },
            }
        ],
    }


def convert_notebook_content_to_markdown(content: Any, options: NotebookMarkdownConversionOptions | None = None) -> str:
    options = options or NotebookMarkdownConversionOptions()
    normalized_content = _normalize_notebook_content_for_markdown_conversion(content)

    if isinstance(normalized_content, str):
        return normalized_content

    if is_markdown_notebook_content(normalized_content):
        return get_markdown_notebook_markdown(normalized_content)

    blocks: list[str] = []
    emitted_comment_mark_ids: set[str] = set()
    for node in _content_list(normalized_content):
        for mark_id in _collect_comment_mark_ids(node):
            if mark_id in emitted_comment_mark_ids:
                continue
            emitted_comment_mark_ids.add(mark_id)
            blocks.append(
                _serialize_component_node(
                    "Comment",
                    {
                        "ref": mark_id,
                        "replies": (options.comment_replies_by_mark_id or {}).get(mark_id, []),
                    },
                )
            )

        markdown = _serialize_rich_content_node(node, 0, options)
        if markdown.strip():
            blocks.append(markdown)

    return "\n\n".join(blocks)


def _normalize_notebook_content_for_markdown_conversion(content: Any) -> JSONContent | str | None:
    if isinstance(content, str):
        parsed_content = _parse_json_encoded_notebook_content(content)
        return parsed_content if parsed_content is not None else content

    if isinstance(content, list):
        return {"type": "doc", "content": content}

    if isinstance(content, dict) or content is None:
        return content

    return None


def _parse_json_encoded_notebook_content(content: str) -> JSONContent | str | None:
    trimmed_content = content.strip()
    if not trimmed_content or trimmed_content[0] not in ("{", "[", '"'):
        return None

    try:
        parsed_content = json.loads(trimmed_content)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed_content, str):
        nested = _parse_json_encoded_notebook_content(parsed_content)
        return nested if nested is not None else parsed_content

    if isinstance(parsed_content, list):
        return {"type": "doc", "content": parsed_content}

    if isinstance(parsed_content, dict):
        return parsed_content

    return None


def _get_markdown_notebook_node(content: Any) -> JSONContent | None:
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
    return node if isinstance(markdown, str) else None


def _content_list(content: JSONContent | str | None) -> list[JSONContent]:
    if not isinstance(content, dict):
        return []
    nodes = content.get("content")
    return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []


def _node_type(node: JSONContent) -> str | None:
    node_type = node.get("type")
    if not isinstance(node_type, str):
        return None
    return RICH_CONTENT_NODE_TYPE_ALIASES.get(node_type, node_type)


def _collect_comment_mark_ids(node: JSONContent) -> list[str]:
    mark_ids: list[str] = []

    def visit(current: JSONContent) -> None:
        for mark in current.get("marks") or []:
            if not isinstance(mark, dict):
                continue
            attrs = mark.get("attrs")
            mark_id = attrs.get("id") if isinstance(attrs, dict) else None
            if mark.get("type") == "comment" and isinstance(mark_id, str) and mark_id:
                mark_ids.append(mark_id)
        for child in _content_list(current):
            visit(child)

    visit(node)
    return mark_ids


def _serialize_rich_content_node(
    node: JSONContent,
    list_depth: int = 0,
    options: NotebookMarkdownConversionOptions | None = None,
) -> str:
    options = options or NotebookMarkdownConversionOptions()
    node_type = _node_type(node)

    if node_type == "text":
        return escape_markdown_block_lines(_serialize_inline_node(node, options))

    if node_type == "heading":
        level = node.get("attrs", {}).get("level") if isinstance(node.get("attrs"), dict) else None
        level = min(max(level, 1), 6) if isinstance(level, int) else 1
        return f"{'#' * level} {_serialize_inline_content(_content_list(node), options)}"

    if node_type == "paragraph":
        return escape_markdown_block_lines(_serialize_inline_content(_content_list(node), options))

    if node_type == "blockquote":
        return _serialize_blockquote_node(node, list_depth, options)

    if node_type in LIST_NODE_TYPES:
        return _serialize_list(node, node_type == "orderedList", list_depth, options)

    if node_type == "horizontalRule":
        return "---"

    if node_type == "codeBlock":
        attrs = node.get("attrs")
        language = attrs.get("language") if isinstance(attrs, dict) and isinstance(attrs.get("language"), str) else ""
        text = "".join(
            "\n" if _node_type(child) == "hardBreak" else str(child.get("text") or "") for child in _content_list(node)
        )
        return _serialize_code_node(text, language or None)

    if node_type == "table":
        return _serialize_table(node, options)

    if node_type == "ph-text":
        return _serialize_legacy_text_node(node)

    if node_type == "ph-insight":
        return _serialize_legacy_insight_node(node)

    if node_type == "ph-dashboard":
        return _serialize_legacy_dashboard_node(node)

    if node_type == "query":
        return _serialize_legacy_query_node(node)

    if node_type == "ph-link":
        return _serialize_legacy_link_node(node, options)

    if node_type == "callout":
        return _serialize_callout_node(node, options)

    if isinstance(node_type, str) and node_type in NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG:
        return _serialize_component_node(
            NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG[node_type],
            _with_default_hidden_filters(
                _get_serializable_attrs(node.get("attrs") if isinstance(node.get("attrs"), dict) else None)
            ),
        )

    child_markdown = "\n\n".join(
        block
        for block in (_serialize_rich_content_node(child, list_depth, options) for child in _content_list(node))
        if block
    )
    if child_markdown or not node_type:
        return child_markdown

    return _serialize_unknown_rich_content_node(node)


def _serialize_legacy_text_node(node: JSONContent) -> str:
    attrs = node.get("attrs")
    body = attrs.get("body") if isinstance(attrs, dict) else None
    return body if isinstance(body, str) else _serialize_unknown_rich_content_node(node)


def _serialize_legacy_insight_node(node: JSONContent) -> str:
    attrs = node.get("attrs")
    if not isinstance(attrs, dict):
        return _serialize_unknown_rich_content_node(node)
    insight_short_id = attrs.get("short_id") if isinstance(attrs.get("short_id"), str) else attrs.get("id")
    if not isinstance(insight_short_id, str) or not insight_short_id:
        return _serialize_unknown_rich_content_node(node)
    return _serialize_component_node(
        "Query",
        _with_default_hidden_filters({"query": {"kind": "SavedInsightNode", "shortId": insight_short_id}}),
    )


def _serialize_legacy_dashboard_node(node: JSONContent) -> str:
    attrs = node.get("attrs")
    dashboard_id = attrs.get("id") if isinstance(attrs, dict) else None
    if not isinstance(dashboard_id, str | int):
        return _serialize_unknown_rich_content_node(node)
    return escape_markdown_block_lines(escape_inline_markdown_text(f"Dashboard {dashboard_id}"))


def _serialize_legacy_query_node(node: JSONContent) -> str:
    props = _get_serializable_attrs(node.get("attrs") if isinstance(node.get("attrs"), dict) else None)
    query = props.get("query")
    if isinstance(query, dict) and query.get("kind") == "HogQLQuery":
        props["query"] = {"kind": "DataVisualizationNode", "source": query}
    return _serialize_component_node("Query", _with_default_hidden_filters(props))


def _serialize_legacy_link_node(node: JSONContent, options: NotebookMarkdownConversionOptions) -> str:
    attrs = node.get("attrs")
    href = attrs.get("href") if isinstance(attrs, dict) else None
    sanitized_href = sanitize_notebook_link_href(href) if isinstance(href, str) else None
    label = _serialize_inline_content(_content_list(node), options).strip()

    if sanitized_href:
        link_label = label or escape_inline_markdown_text(sanitized_href)
        return f"[{link_label}]({sanitized_href})"

    if label:
        return label

    if isinstance(href, str) and href.strip():
        return escape_markdown_block_lines(escape_inline_markdown_text(href.strip()))

    return _serialize_unknown_rich_content_node(node)


# The markdown notebook blockquote only holds inline text (and list lines), so block content
# inside a v1 blockquote or callout — embedded cards like Query/Python, headings, code blocks,
# tables, nested quotes — is emitted as standalone blocks that split the quote. Quoting those
# lines instead would produce markdown the parser can only read back as escaped literal text,
# destroying the nodes on the next save.
def _is_blockquotable_rich_content_node(node: JSONContent, serialized: str) -> bool:
    node_type = _node_type(node)
    if node_type in ("paragraph", "text"):
        return True
    # Blockquoted lists parse back (`> - item`), but only while every line is a list line — a
    # list that spilled block content into standalone blocks splits out of the quote with them.
    if node_type in LIST_NODE_TYPES:
        return "\n\n" not in serialized
    return False


def _serialize_blockquote_node(node: JSONContent, list_depth: int, options: NotebookMarkdownConversionOptions) -> str:
    blocks: list[str] = []
    pending_quote_lines: list[str] = []

    def flush_quote_lines() -> None:
        if pending_quote_lines:
            blocks.append("\n".join(f"> {line}" for line in pending_quote_lines))
            pending_quote_lines.clear()

    for child in _content_list(node):
        child_markdown = _serialize_rich_content_node(child, list_depth, options)
        if _is_blockquotable_rich_content_node(child, child_markdown):
            pending_quote_lines.extend(child_markdown.split("\n"))
        elif child_markdown.strip():
            flush_quote_lines()
            blocks.append(child_markdown)
    flush_quote_lines()

    return "\n\n".join(blocks)


def _serialize_callout_node(node: JSONContent, options: NotebookMarkdownConversionOptions) -> str:
    attrs = node.get("attrs")
    raw_emoji = attrs.get("emoji") if isinstance(attrs, dict) else None
    emoji = escape_inline_markdown_text(raw_emoji.strip()) if isinstance(raw_emoji, str) and raw_emoji.strip() else ""
    blocks: list[str] = []
    pending_quote_bodies: list[str] = []
    emoji_placed = False

    def flush_quote_bodies() -> None:
        nonlocal emoji_placed
        if not pending_quote_bodies:
            return
        body = "\n\n".join(pending_quote_bodies)
        if emoji and not emoji_placed:
            body = f"{emoji} {body}"
            emoji_placed = True
        blocks.append("\n".join(f"> {line}" for line in body.split("\n")))
        pending_quote_bodies.clear()

    for child in _content_list(node):
        child_markdown = _serialize_rich_content_node(child, 0, options)
        if not child_markdown.strip():
            continue
        if _is_blockquotable_rich_content_node(child, child_markdown):
            pending_quote_bodies.append(child_markdown)
        else:
            flush_quote_bodies()
            blocks.append(child_markdown)
    flush_quote_bodies()

    if emoji and not emoji_placed:
        blocks.insert(0, f"> {emoji}")

    if not blocks:
        return _serialize_unknown_rich_content_node(node)

    return "\n\n".join(blocks)


def _serialize_unknown_rich_content_node(node: JSONContent) -> str:
    attrs = _get_serializable_attrs(node.get("attrs") if isinstance(node.get("attrs"), dict) else None)
    node_type = node.get("type")
    props: dict[str, NotebookPropValue] = dict(attrs)
    if isinstance(node_type, str) and node_type:
        props = {"nodeType": node_type, **props}
    return _serialize_component_node("UnknownNode", props)


def _serialize_inline_content(
    content: list[JSONContent],
    options: NotebookMarkdownConversionOptions | None = None,
) -> str:
    return "".join(_serialize_inline_node(node, options) for node in content)


def _serialize_inline_node(node: JSONContent, options: NotebookMarkdownConversionOptions | None = None) -> str:
    options = options or NotebookMarkdownConversionOptions()
    node_type = _node_type(node)

    if node_type == "text":
        marks = _mark_list(node)
        is_code_text = any(mark.get("type") == "code" for mark in marks)
        text = str(node.get("text") or "")
        escaped_text = escape_code_span_text(text) if is_code_text else escape_inline_markdown_text(text)
        return _apply_marks(escaped_text, marks)

    if node_type == "hardBreak":
        return "\n"

    if node_type == MENTION_NODE_TYPE:
        return _serialize_mention_node(node, options)

    return _serialize_inline_content(_content_list(node), options)


def _serialize_mention_node(node: JSONContent, options: NotebookMarkdownConversionOptions) -> str:
    attrs = node.get("attrs")
    member_id = attrs.get("id") if isinstance(attrs, dict) else None
    attr_label = attrs.get("label") if isinstance(attrs, dict) else None
    label = attr_label.strip() if isinstance(attr_label, str) and attr_label.strip() else None
    looked_up_label = (
        options.get_mention_label(member_id) if isinstance(member_id, int) and options.get_mention_label else None
    )
    display_label = label or looked_up_label or "@member"
    if not display_label.startswith("@"):
        display_label = f"@{display_label}"
    if not isinstance(member_id, int):
        return escape_inline_markdown_text(display_label)
    return f"<mention id={json.dumps(str(member_id))}>{escape_inline_markdown_text(display_label)}</mention>"


def _apply_marks(text: str, marks: list[JSONContent]) -> str:
    comment_mark_ids = [
        mark.get("attrs", {}).get("id")
        for mark in marks
        if mark.get("type") == "comment"
        and isinstance(mark.get("attrs"), dict)
        and isinstance(mark.get("attrs", {}).get("id"), str)
        and mark.get("attrs", {}).get("id")
    ]
    formatted_text = _apply_formatting_marks(text, marks)
    for mark_id in comment_mark_ids:
        formatted_text = f"<ref id={json.dumps(mark_id)}>{formatted_text}</ref>"
    return formatted_text


def _apply_formatting_marks(text: str, marks: list[JSONContent]) -> str:
    marked_text = text
    for mark in marks:
        mark_type = mark.get("type")
        if mark_type in ("bold", "strong"):
            marked_text = f"**{marked_text}**"
        elif mark_type in ("italic", "em"):
            marked_text = f"*{marked_text}*"
        elif mark_type == "underline":
            marked_text = f"<u>{marked_text}</u>"
        elif mark_type == "strike":
            marked_text = f"~~{marked_text}~~"
        elif mark_type == "code":
            marked_text = f"`{marked_text}`"
        elif mark_type == "link" and isinstance(mark.get("attrs"), dict):
            href = mark["attrs"].get("href")
            sanitized = sanitize_notebook_link_href(href) if isinstance(href, str) else None
            if sanitized:
                marked_text = f"[{marked_text}]({sanitized})"
    return marked_text


def _serialize_list(
    node: JSONContent,
    ordered: bool,
    depth: int,
    options: NotebookMarkdownConversionOptions | None = None,
) -> str:
    options = options or NotebookMarkdownConversionOptions()
    blocks: list[str] = []
    pending_list_lines: list[str] = []

    def flush_list_lines() -> None:
        nonlocal pending_list_lines
        if pending_list_lines:
            blocks.append("\n".join(pending_list_lines))
            pending_list_lines = []

    items = [child for child in _content_list(node) if _node_type(child) in LIST_ITEM_NODE_TYPES]
    for index, item in enumerate(items):
        list_lines, trailing_blocks = _serialize_list_item(item, ordered, depth, index, options)
        pending_list_lines.extend(list_lines)
        if trailing_blocks:
            flush_list_lines()
            blocks.extend(trailing_blocks)
    flush_list_lines()

    return "\n\n".join(blocks)


def _serialize_list_item(
    item: JSONContent,
    ordered: bool,
    depth: int,
    index: int,
    options: NotebookMarkdownConversionOptions,
) -> tuple[list[str], list[str]]:
    marker = f"{index + 1}." if ordered else "-"
    children = _content_list(item)
    item_type = _node_type(item)
    first_paragraph = next((child for child in children if _node_type(child) == "paragraph"), None)
    nested_lists = [child for child in children if _node_type(child) in LIST_NODE_TYPES]
    extra_blocks = [
        child for child in children if child is not first_paragraph and _node_type(child) not in LIST_NODE_TYPES
    ]
    checked = item.get("attrs", {}).get("checked") if isinstance(item.get("attrs"), dict) else False
    checkbox = "[x] " if item_type == "taskItem" and checked else "[ ] " if item_type == "taskItem" else ""
    item_text = re.sub(
        r"\s*\n\s*", " ", _serialize_inline_content(_content_list(first_paragraph), options) if first_paragraph else ""
    )
    list_lines = [f"{'  ' * depth}{marker} {checkbox}{item_text}".rstrip()]

    for nested_list in nested_lists:
        nested_markdown = _serialize_rich_content_node(nested_list, depth + 1, options)
        if nested_markdown:
            list_lines.append(nested_markdown)

    trailing_blocks = [
        block for block in (_serialize_rich_content_node(child, 0, options) for child in extra_blocks) if block.strip()
    ]
    return list_lines, trailing_blocks


def _serialize_table(node: JSONContent, options: NotebookMarkdownConversionOptions | None = None) -> str:
    options = options or NotebookMarkdownConversionOptions()
    rows = [child for child in _content_list(node) if _node_type(child) == "tableRow"]
    if not rows:
        return ""

    serialized_rows: list[list[str]] = []
    for row in rows:
        cells = [cell for cell in _content_list(row) if _node_type(cell) in ("tableCell", "tableHeader")]
        serialized_cells: list[str] = []
        for cell in cells:
            cell_text = " ".join(_serialize_rich_content_node(child, 0, options) for child in _content_list(cell))
            cell_text = re.sub(r"\s*\n\s*", " ", cell_text)
            serialized_cells.append(_escape_table_cell(cell_text))
        serialized_rows.append(serialized_cells)

    column_count = max(len(row) for row in serialized_rows)
    header = _normalize_table_row(serialized_rows[0], column_count)
    body = [_normalize_table_row(row, column_count) for row in serialized_rows[1:]]
    separator = ["---"] * column_count
    rows_to_render = [header, separator, *body]
    return "\n".join(f"| {' | '.join(row)} |" for row in rows_to_render)


def _normalize_table_row(row: list[str] | None, column_count: int) -> list[str]:
    return [(row or [])[index] if index < len(row or []) else "" for index in range(column_count)]


def _escape_table_cell(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            output.append(text[index : index + 2])
            index += 2
            continue
        if text[index] == "|":
            output.append("\\|")
        else:
            output.append(text[index])
        index += 1
    return "".join(output)


def _get_serializable_attrs(attrs: Mapping[str, Any] | None) -> dict[str, NotebookPropValue]:
    props: dict[str, NotebookPropValue] = {}
    for key, value in (attrs or {}).items():
        serializable_value = _to_serializable_prop_value(_revive_json_encoded_attr(value))
        if serializable_value is not _SERIALIZATION_OMIT:
            props[key] = cast(NotebookPropValue, serializable_value)
    return props


def _revive_json_encoded_attr(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed.startswith(("{", "[")):
        return value
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        return value
    return parsed if isinstance(parsed, dict | list) else value


def _to_serializable_prop_value(value: Any) -> NotebookPropValue | object:
    try:
        serialized = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return _SERIALIZATION_OMIT
    return json.loads(serialized)


def _serialize_component_node(tag_name: str, props: Mapping[str, NotebookPropValue]) -> str:
    if tag_name == "Image":
        raw_src = props.get("src")
        raw_alt = props.get("alt")
        src = raw_src if isinstance(raw_src, str) else ""
        alt = raw_alt if isinstance(raw_alt, str) else ""
        return f"![{_escape_markdown_image_alt(alt)}]({_escape_markdown_image_src(src)})"
    return f"<{tag_name}{_serialize_component_props(props)} />"


def _serialize_component_props(props: Mapping[str, NotebookPropValue]) -> str:
    serializable_props = _get_serializable_component_props(props)
    entries = _get_ordered_component_prop_entries(serializable_props)
    return "".join(f" {key}" if value is True else f" {key}={_serialize_prop_value(value)}" for key, value in entries)


def _get_serializable_component_props(props: Mapping[str, NotebookPropValue]) -> dict[str, NotebookPropValue]:
    next_props = {
        key: value for key, value in props.items() if key not in ("view", "edit", "hideFilters", "hideResults")
    }
    legacy_view_panel_visible = props.get("view") if isinstance(props.get("view"), bool) else None
    legacy_edit_panel_visible = props.get("edit") if isinstance(props.get("edit"), bool) else None
    hide_filters = (
        props.get("hideFilters") if isinstance(props.get("hideFilters"), bool) else legacy_edit_panel_visible is False
    )
    hide_results = (
        props.get("hideResults") if isinstance(props.get("hideResults"), bool) else legacy_view_panel_visible is False
    )

    if hide_filters:
        next_props["hideFilters"] = True
    if hide_results:
        next_props["hideResults"] = True
    return next_props


def _with_default_hidden_filters(props: dict[str, NotebookPropValue]) -> dict[str, NotebookPropValue]:
    if isinstance(props.get("hideFilters"), bool) or isinstance(props.get("edit"), bool):
        return props
    return {**props, "hideFilters": True}


def _get_ordered_component_prop_entries(props: Mapping[str, NotebookPropValue]) -> list[tuple[str, NotebookPropValue]]:
    entries = list(props.items())
    ordered_keys = ["hideFilters", "hideResults"]
    return [
        *[(key, props[key]) for key in ordered_keys if key in props],
        *[(key, value) for key, value in entries if key not in ordered_keys],
    ]


def _serialize_prop_value(value: NotebookPropValue) -> str:
    if isinstance(value, str):
        return _json_stringify(value)
    return "{" + _json_stringify(value) + "}"


def _json_stringify(value: NotebookPropValue) -> str:
    return json.dumps(_normalize_json_numbers(value), ensure_ascii=False, separators=(",", ":"))


def _normalize_json_numbers(value: NotebookPropValue) -> NotebookPropValue:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    return value


def _serialize_code_node(text: str, language: str | None = None) -> str:
    fence = _get_code_block_fence(text)
    return f"{fence}{language or ''}\n{text}\n{fence}"


def _get_code_block_fence(text: str) -> str:
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest_run + 1)


def _mark_list(node: JSONContent) -> list[JSONContent]:
    marks = node.get("marks")
    return [mark for mark in marks if isinstance(mark, dict)] if isinstance(marks, list) else []


def sanitize_notebook_link_href(href: str) -> str | None:
    trimmed_href = href.strip()
    if not re.match(r"^https?://\S+$", trimmed_href, flags=re.IGNORECASE):
        return None
    try:
        parsed = urlparse(trimmed_href)
    except ValueError:
        return None
    return trimmed_href if parsed.scheme in ("http", "https") and parsed.netloc else None


def escape_inline_markdown_text(text: str) -> str:
    escaped = re.sub(r"[\\`*\[\]|]", lambda match: f"\\{match.group(0)}", text)
    escaped = re.sub(r"~~+", lambda match: "\\~" * len(match.group(0)), escaped)
    escaped = _escape_non_intraword_underscores(escaped)
    return re.sub(r"<(?=\/?(?:u>|ref[\s>]|mention[\s>]))", r"\\<", escaped)


def _escape_non_intraword_underscores(text: str) -> str:
    output: list[str] = []
    for index, character in enumerate(text):
        if character != "_":
            output.append(character)
            continue
        previous_character = text[index - 1] if index > 0 else ""
        next_character = text[index + 1] if index + 1 < len(text) else ""
        output.append(
            "_" if _is_ascii_alphanumeric(previous_character) and _is_ascii_alphanumeric(next_character) else "\\_"
        )
    return "".join(output)


def _is_ascii_alphanumeric(character: str) -> bool:
    return bool(character) and character.isascii() and character.isalnum()


def escape_code_span_text(text: str) -> str:
    return re.sub(r"[\\`]", lambda match: f"\\{match.group(0)}", text)


def escape_markdown_block_lines(serialized: str) -> str:
    return "\n".join(escape_markdown_line_start(line) for line in serialized.split("\n"))


def escape_markdown_line_start(line: str) -> str:
    leading_whitespace_match = re.match(r"^\s*", line)
    leading_whitespace = leading_whitespace_match.group(0) if leading_whitespace_match else ""
    content = line[len(leading_whitespace) :]

    ordered_list_match = re.match(r"^(\d+)([.)])(\s|$)", content)
    if ordered_list_match:
        return f"{leading_whitespace}{ordered_list_match.group(1)}\\{content[len(ordered_list_match.group(1)) :]}"

    if re.match(r"^(#{1,6}\s|>|[-+•](\s|$)|-{3,}\s*$|<[A-Z]|<!--)", content):
        return f"{leading_whitespace}\\{content}"

    return line


def _escape_markdown_image_alt(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _escape_markdown_image_src(text: str) -> str:
    return text.replace("\\", "\\\\").replace(")", "\\)")
