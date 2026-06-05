import re
import html
import json
from typing import Any

JsonDict = dict[str, Any]

BLOCK_TAG_PATTERN = re.compile(
    r"(?ims)<(?P<tag>query|python|hogql|ducksql|duckdb|notebooknode)\b(?P<attrs>[^>]*)>\n?(?P<body>.*?)\n?</(?P=tag)>"
)
RESOURCE_TAG_PATTERN = re.compile(
    r"(?ims)<(?P<tag>FeatureFlag|Experiment|Survey|Cohort|Person|Group|SessionReplay|Recording|Insight)\b(?P<attrs>[^>]*)/?>"
)
ATTRIBUTE_PATTERN = re.compile(r"""([A-Za-z_][\w:-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+)""")
EXECUTABLE_TAG_TO_NODE_TYPE = {
    "python": "ph-python",
    "hogql": "ph-hogql-sql",
    "ducksql": "ph-duck-sql",
    "duckdb": "ph-duck-sql",
}
RESOURCE_TAG_TO_NODE_TYPE = {
    "FeatureFlag": "ph-feature-flag",
    "Experiment": "ph-experiment",
    "Survey": "ph-survey",
    "Cohort": "ph-cohort",
    "Person": "ph-person",
    "Group": "ph-group",
    "SessionReplay": "ph-recording",
    "Recording": "ph-recording",
}
NODE_TYPE_TO_RESOURCE_TAG = {
    "ph-feature-flag": "FeatureFlag",
    "ph-experiment": "Experiment",
    "ph-survey": "Survey",
    "ph-cohort": "Cohort",
    "ph-person": "Person",
    "ph-group": "Group",
    "ph-recording": "SessionReplay",
}


def markdown_to_tiptap_doc(markdown: str | None, *, title: str | None = None) -> JsonDict:
    cleaned_markdown = _strip_title_heading(markdown or "", title)
    nodes = markdown_to_tiptap_nodes(cleaned_markdown)
    if title and not _starts_with_h1(nodes):
        nodes.insert(0, _heading(1, [{"type": "text", "text": title}]))
    if not nodes:
        nodes = [{"type": "paragraph"}]
    return {"type": "doc", "content": nodes}


def tiptap_doc_to_markdown(content: JsonDict | None) -> str:
    if not content or not isinstance(content, dict):
        return ""
    nodes = content.get("content")
    if not isinstance(nodes, list):
        return ""
    parts = [_node_to_markdown(node) for node in nodes if isinstance(node, dict)]
    return "\n\n".join(part for part in parts if part).strip()


def markdown_to_text_content(markdown: str | None, *, title: str | None = None) -> str:
    return tiptap_doc_to_text(markdown_to_tiptap_doc(markdown, title=title))


def tiptap_doc_to_text(content: JsonDict | None) -> str:
    if not content or not isinstance(content, dict):
        return ""
    nodes = content.get("content")
    if not isinstance(nodes, list):
        return ""
    return "\n".join(part for part in (_node_to_text(node) for node in nodes if isinstance(node, dict)) if part)


def markdown_to_tiptap_nodes(markdown: str) -> list[JsonDict]:
    if not markdown or not markdown.strip():
        return []

    nodes: list[JsonDict] = []
    last_end = 0
    for match in _iter_notebook_tags(markdown):
        nodes.extend(_basic_markdown_to_nodes(markdown[last_end : match.start()]))
        nodes.extend(_tag_match_to_nodes(match))
        last_end = match.end()
    nodes.extend(_basic_markdown_to_nodes(markdown[last_end:]))
    return nodes


def _iter_notebook_tags(markdown: str) -> list[re.Match[str]]:
    block_matches = list(BLOCK_TAG_PATTERN.finditer(markdown))
    resource_matches = [
        match
        for match in RESOURCE_TAG_PATTERN.finditer(markdown)
        if not any(block.start() <= match.start() < block.end() for block in block_matches)
    ]

    matches = sorted(block_matches + resource_matches, key=lambda match: match.start())
    non_overlapping: list[re.Match[str]] = []
    consumed_until = 0
    for match in matches:
        if match.start() < consumed_until:
            continue
        non_overlapping.append(match)
        consumed_until = match.end()
    return non_overlapping


def _tag_match_to_nodes(match: re.Match[str]) -> list[JsonDict]:
    tag = match.group("tag")
    if tag is None:
        return []

    if tag.lower() in {"query", "python", "hogql", "ducksql", "duckdb", "notebooknode"}:
        return [_block_tag_to_node(tag.lower(), match.group("attrs") or "", match.group("body") or "")]

    return [_resource_tag_to_node(tag, match.group("attrs") or "")]


def _block_tag_to_node(tag: str, raw_attrs: str, raw_body: str) -> JsonDict:
    attrs = _parse_attrs(raw_attrs)
    body = html.unescape(raw_body.strip("\n"))
    title = attrs.get("title")

    if tag == "query":
        try:
            query = json.loads(body)
        except ValueError:
            return _paragraph([{"type": "text", "text": "[Invalid query JSON]"}])
        if not isinstance(query, dict):
            return _paragraph([{"type": "text", "text": "[Invalid query JSON]"}])
        node_attrs: JsonDict = {"query": query}
        if title:
            node_attrs["title"] = title
        return {"type": "ph-query", "attrs": node_attrs}

    if tag == "notebooknode":
        node_type = attrs.get("type")
        if not node_type or not node_type.startswith("ph-"):
            return _paragraph([{"type": "text", "text": "[Invalid notebook node]"}])
        try:
            node_attrs = json.loads(body) if body else {}
        except ValueError:
            return _paragraph([{"type": "text", "text": "[Invalid notebook node JSON]"}])
        if not isinstance(node_attrs, dict):
            return _paragraph([{"type": "text", "text": "[Invalid notebook node JSON]"}])
        return {"type": node_type, "attrs": node_attrs}

    node_attrs = {"code": body, "__init": {"showSettings": True}}
    if title:
        node_attrs["title"] = title
    if tag in {"hogql", "ducksql", "duckdb"}:
        default_variable = "hogql_df" if tag == "hogql" else "duck_df"
        node_attrs["returnVariable"] = attrs.get("return_variable") or attrs.get("returnvariable") or default_variable
    return {"type": EXECUTABLE_TAG_TO_NODE_TYPE[tag], "attrs": node_attrs}


def _resource_tag_to_node(tag: str, raw_attrs: str) -> JsonDict:
    attrs = _parse_attrs(raw_attrs)
    if tag == "Insight":
        short_id = attrs.get("short_id") or attrs.get("shortid") or attrs.get("id")
        return {
            "type": "ph-query",
            "attrs": {
                "query": {
                    "kind": "SavedInsightNode",
                    "shortId": short_id,
                }
            },
        }

    node_type = RESOURCE_TAG_TO_NODE_TYPE.get(tag, "paragraph")
    node_attrs: JsonDict = {}
    resource_id = attrs.get("id") or attrs.get("uuid") or attrs.get("short_id") or attrs.get("shortid")
    if resource_id is not None:
        node_attrs["id"] = _coerce_numeric_id(resource_id)
    return {"type": node_type, "attrs": node_attrs}


def _basic_markdown_to_nodes(markdown: str) -> list[JsonDict]:
    if not markdown or not markdown.strip():
        return []

    lines = markdown.replace("\r\n", "\n").split("\n")
    nodes: list[JsonDict] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            node: JsonDict = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code_lines)}]}
            if language:
                node["attrs"] = {"language": language}
            nodes.append(node)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            nodes.append(_heading(len(heading_match.group(1)), _parse_inline(heading_match.group(2).strip())))
            i += 1
            continue

        if re.match(r"^\s*[-*]\s+", line):
            items: list[JsonDict] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item_text = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append({"type": "listItem", "content": [_paragraph(_parse_inline(item_text))]})
                i += 1
            nodes.append({"type": "bulletList", "content": items})
            continue

        if re.match(r"^\s*\d+[.)]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+[.)]\s+", "", lines[i])
                items.append({"type": "listItem", "content": [_paragraph(_parse_inline(item_text))]})
                i += 1
            nodes.append({"type": "orderedList", "content": items})
            continue

        paragraph_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_special_line(lines[i]):
            paragraph_lines.append(lines[i].strip())
            i += 1
        nodes.append(_paragraph(_parse_inline(" ".join(paragraph_lines))))

    return nodes


def _parse_inline(text: str) -> list[JsonDict]:
    if not text:
        return []

    nodes: list[JsonDict] = []
    pattern = re.compile(
        r"(\*\*(.+?)\*\*)"
        r"|(\*(.+?)\*)"
        r"|(`(.+?)`)"
        r"|(\[([^\]]+)\]\(([^)]+)\))"
    )
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            nodes.append({"type": "text", "text": text[pos : match.start()]})

        if match.group(2) is not None:
            nodes.append({"type": "text", "text": match.group(2), "marks": [{"type": "bold"}]})
        elif match.group(4) is not None:
            nodes.append({"type": "text", "text": match.group(4), "marks": [{"type": "italic"}]})
        elif match.group(6) is not None:
            nodes.append({"type": "text", "text": match.group(6), "marks": [{"type": "code"}]})
        elif match.group(8) is not None:
            nodes.append(
                {"type": "text", "text": match.group(8), "marks": [{"type": "link", "attrs": {"href": match.group(9)}}]}
            )
        pos = match.end()

    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})
    return [node for node in nodes if node.get("text") != ""]


def _node_to_markdown(node: JsonDict) -> str:
    node_type = node.get("type")
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}

    if node_type == "heading":
        level = attrs.get("level", 1) if isinstance(attrs, dict) else 1
        return f"{'#' * int(level)} {_inline_content_to_markdown(node)}"
    if node_type == "paragraph":
        return _inline_content_to_markdown(node)
    if node_type == "bulletList":
        return "\n".join(f"- {_node_to_text(item).strip()}" for item in _content_list(node))
    if node_type == "orderedList":
        return "\n".join(
            f"{index + 1}. {_node_to_text(item).strip()}" for index, item in enumerate(_content_list(node))
        )
    if node_type == "codeBlock":
        language = attrs.get("language", "") if isinstance(attrs, dict) else ""
        return f"```{language}\n{_node_to_text(node)}\n```"
    if node_type == "ph-query" and isinstance(attrs, dict):
        title = _format_title_attr(attrs.get("title"))
        return f"<Query{title}>\n{json.dumps(attrs.get('query') or {}, indent=2)}\n</Query>"
    if node_type in {"ph-python", "ph-hogql-sql", "ph-duck-sql"} and isinstance(attrs, dict):
        tag = {"ph-python": "Python", "ph-hogql-sql": "HogQL", "ph-duck-sql": "DuckSQL"}[str(node_type)]
        title = _format_title_attr(attrs.get("title"))
        return_variable = ""
        if node_type != "ph-python" and attrs.get("returnVariable"):
            return_variable = f' return_variable="{html.escape(str(attrs["returnVariable"]), quote=True)}"'
        return f"<{tag}{title}{return_variable}>\n{attrs.get('code') or ''}\n</{tag}>"
    if node_type in NODE_TYPE_TO_RESOURCE_TAG and isinstance(attrs, dict):
        tag = NODE_TYPE_TO_RESOURCE_TAG[str(node_type)]
        resource_id = attrs.get("id")
        id_attr = f' id="{html.escape(str(resource_id), quote=True)}"' if resource_id is not None else ""
        return f"<{tag}{id_attr} />"
    if str(node_type).startswith("ph-"):
        return f'<NotebookNode type="{html.escape(str(node_type), quote=True)}">\n{json.dumps(attrs, indent=2)}\n</NotebookNode>'

    return "\n".join(_node_to_markdown(child) for child in _content_list(node))


def _node_to_text(node: JsonDict) -> str:
    node_type = node.get("type")
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    if node_type == "text":
        return str(node.get("text") or "")
    if node_type == "ph-query" and isinstance(attrs, dict):
        title = attrs.get("title")
        return str(title or "Query")
    if node_type in NODE_TYPE_TO_RESOURCE_TAG and isinstance(attrs, dict):
        resource_id = attrs.get("id")
        return f"{NODE_TYPE_TO_RESOURCE_TAG[str(node_type)]} {resource_id}".strip()
    if node_type in {"ph-python", "ph-hogql-sql", "ph-duck-sql"} and isinstance(attrs, dict):
        return str(attrs.get("code") or "")
    return "\n".join(part for part in (_node_to_text(child) for child in _content_list(node)) if part)


def _inline_content_to_markdown(node: JsonDict) -> str:
    parts: list[str] = []
    for child in _content_list(node):
        text = str(child.get("text") or "") if child.get("type") == "text" else _node_to_markdown(child)
        for mark in child.get("marks") or []:
            if not isinstance(mark, dict):
                continue
            mark_type = mark.get("type")
            if mark_type == "bold":
                text = f"**{text}**"
            elif mark_type == "italic":
                text = f"*{text}*"
            elif mark_type == "code":
                text = f"`{text}`"
            elif mark_type == "link":
                mark_attrs = mark.get("attrs")
                attrs = mark_attrs if isinstance(mark_attrs, dict) else {}
                text = f"[{text}]({attrs.get('href') or ''})"
        parts.append(text)
    return "".join(parts)


def _content_list(node: JsonDict) -> list[JsonDict]:
    content = node.get("content")
    if not isinstance(content, list):
        return []
    return [child for child in content if isinstance(child, dict)]


def _heading(level: int, content: list[JsonDict]) -> JsonDict:
    return {"type": "heading", "attrs": {"level": level}, "content": content}


def _paragraph(content: list[JsonDict]) -> JsonDict:
    if not content:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": content}


def _parse_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in ATTRIBUTE_PATTERN.finditer(raw_attrs):
        raw_value = match.group(2)
        value = raw_value[1:-1] if raw_value[:1] in {'"', "'"} and raw_value[-1:] == raw_value[:1] else raw_value
        attrs[match.group(1).replace("-", "_").lower()] = html.unescape(value)
    return attrs


def _coerce_numeric_id(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def _format_title_attr(value: object) -> str:
    return f' title="{html.escape(str(value), quote=True)}"' if value else ""


def _starts_with_h1(nodes: list[JsonDict]) -> bool:
    if not nodes:
        return False
    first = nodes[0]
    attrs = first.get("attrs")
    return first.get("type") == "heading" and isinstance(attrs, dict) and attrs.get("level") == 1


def _strip_title_heading(markdown: str, title: str | None) -> str:
    if not title:
        return markdown
    match = re.match(r"^\s*#\s+(.+?)(?:\n|$)", markdown)
    if match and match.group(1).strip().lower() == title.lower():
        return markdown[match.end() :].lstrip("\n")
    return markdown


def _is_special_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("```")
        or bool(re.match(r"^#{1,6}\s+", stripped))
        or bool(re.match(r"^\s*[-*]\s+", line))
        or bool(re.match(r"^\s*\d+[.)]\s+", line))
    )
