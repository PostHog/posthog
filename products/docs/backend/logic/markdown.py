"""A doc as markdown, and markdown as a doc.

The space's context notes are a doc, edited like any page, and the wiki page every
agent reads is compiled from it. Blocks and marks map one to one; a live data point
compiles to the ``<hogql>`` tag agents already cite, so the notes an agent reads
carry the query, not a stale figure.
"""

from __future__ import annotations

import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

Node = dict[str, Any]

_TASK_PREFIX = re.compile(r"^\[( |x|X)\]\s+")


# --- doc -> markdown ---


def to_markdown(content: Node | None) -> str:
    if not content:
        return ""
    blocks = [_block(node, depth=0) for node in content.get("content") or []]
    return "\n\n".join(block for block in blocks if block.strip()).strip() + "\n"


def _block(node: Node, *, depth: int) -> str:
    kind = node.get("type")
    children = node.get("content") or []
    if kind == "heading":
        level = int((node.get("attrs") or {}).get("level") or 1)
        return f"{'#' * min(level, 6)} {_inline(children)}"
    if kind == "paragraph":
        return _inline(children)
    if kind == "blockquote":
        inner = "\n\n".join(_block(child, depth=depth) for child in children)
        return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
    if kind == "codeBlock":
        language = (node.get("attrs") or {}).get("language") or ""
        return f"```{language}\n{_inline(children, raw=True)}\n```"
    if kind == "horizontalRule":
        return "---"
    if kind in ("bulletList", "taskList"):
        return "\n".join(_list_item(child, marker="-", depth=depth, task=kind == "taskList") for child in children)
    if kind == "orderedList":
        start = int((node.get("attrs") or {}).get("start") or 1)
        return "\n".join(
            _list_item(child, marker=f"{start + index}.", depth=depth) for index, child in enumerate(children)
        )
    if kind in ("metricRow", "objectBlock"):
        label = (node.get("attrs") or {}).get("label") or (node.get("attrs") or {}).get("query") or ""
        return str(label).strip()
    return _inline(children)


def _list_item(node: Node, *, marker: str, depth: int, task: bool = False) -> str:
    indent = "  " * depth
    prefix = f"{indent}{marker} "
    if task:
        checked = bool((node.get("attrs") or {}).get("checked"))
        prefix += "[x] " if checked else "[ ] "
    parts: list[str] = []
    for index, child in enumerate(node.get("content") or []):
        if child.get("type") in ("bulletList", "orderedList", "taskList"):
            parts.append(_block(child, depth=depth + 1))
        elif index == 0:
            parts.append(prefix + _block(child, depth=depth))
        else:
            parts.append(indent + "  " + _block(child, depth=depth))
    return "\n".join(parts) if parts else prefix.rstrip()


def _inline(nodes: list[Node], *, raw: bool = False) -> str:
    return "".join(_inline_node(node, raw=raw) for node in nodes)


def _inline_node(node: Node, *, raw: bool) -> str:
    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "text":
        text = str(node.get("text") or "")
        return text if raw else _marked(text, node.get("marks") or [])
    if kind == "hardBreak":
        return "\n" if raw else "  \n"
    if kind == "dataValue":
        label = str(attrs.get("label") or "").strip()
        if attrs.get("query"):
            return f'<hogql label="{label}">{str(attrs["query"]).strip()}</hogql>'
        if attrs.get("shortId"):
            return f'<insight id="{attrs["shortId"]}">{label or attrs["shortId"]}</insight>'
        return label
    if kind == "dataRequest":
        return f"[{str(attrs.get('question') or '').strip()}]"
    if kind == "mention":
        return f"@{str(attrs.get('label') or '').strip()}"
    if kind == "taskChip":
        return f"[task: {str(attrs.get('label') or '').strip()}]"
    label = attrs.get("label") or attrs.get("title") or ""
    return str(label).strip()


def _marked(text: str, marks: list[Node]) -> str:
    out = text
    kinds = {mark.get("type"): mark for mark in marks}
    if "code" in kinds:
        return f"`{out}`"
    if "bold" in kinds:
        out = f"**{out}**"
    if "italic" in kinds:
        out = f"*{out}*"
    if "strike" in kinds:
        out = f"~~{out}~~"
    if "link" in kinds:
        href = (kinds["link"].get("attrs") or {}).get("href") or ""
        out = f"[{out}]({href})"
    return out


# --- markdown -> doc ---


def from_markdown(text: str) -> Node:
    """A doc for the markdown a page held before it was a doc. Unknown constructs become text."""
    tokens = MarkdownIt("commonmark").enable("strikethrough").parse(text or "")
    content, _ = _blocks(tokens, 0, closer=None)
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def _blocks(tokens: list[Token], index: int, *, closer: str | None) -> tuple[list[Node], int]:
    nodes: list[Node] = []
    while index < len(tokens):
        token = tokens[index]
        if closer is not None and token.type == closer:
            return nodes, index + 1
        if token.type == "heading_open":
            inline, index = _find_inline(tokens, index + 1, "heading_close")
            nodes.append({"type": "heading", "attrs": {"level": int(token.tag[1])}, "content": inline})
        elif token.type == "paragraph_open":
            inline, index = _find_inline(tokens, index + 1, "paragraph_close")
            nodes.append({"type": "paragraph", **({"content": inline} if inline else {})})
        elif token.type in ("bullet_list_open", "ordered_list_open"):
            items, index = _list_items(tokens, index + 1, closer=token.type.replace("_open", "_close"))
            task = bool(items) and all(item.get("type") == "taskItem" for item in items)
            if task:
                nodes.append({"type": "taskList", "content": items})
            elif token.type == "bullet_list_open":
                nodes.append({"type": "bulletList", "content": items})
            else:
                start = int(token.attrGet("start") or 1)
                nodes.append({"type": "orderedList", "attrs": {"start": start}, "content": items})
        elif token.type == "blockquote_open":
            inner, index = _blocks(tokens, index + 1, closer="blockquote_close")
            nodes.append({"type": "blockquote", "content": inner or [{"type": "paragraph"}]})
        elif token.type in ("fence", "code_block"):
            node: Node = {"type": "codeBlock", "attrs": {"language": (token.info or "").strip() or None}}
            body = token.content.rstrip("\n")
            if body:
                node["content"] = [{"type": "text", "text": body}]
            nodes.append(node)
            index += 1
        elif token.type == "hr":
            nodes.append({"type": "horizontalRule"})
            index += 1
        elif token.type == "html_block":
            nodes.append({"type": "paragraph", "content": [{"type": "text", "text": token.content.strip()}]})
            index += 1
        else:
            index += 1
    return nodes, index


def _list_items(tokens: list[Token], index: int, *, closer: str) -> tuple[list[Node], int]:
    items: list[Node] = []
    while index < len(tokens) and tokens[index].type != closer:
        if tokens[index].type != "list_item_open":
            index += 1
            continue
        inner, index = _blocks(tokens, index + 1, closer="list_item_close")
        checked = _task_state(inner)
        if checked is None:
            items.append({"type": "listItem", "content": inner or [{"type": "paragraph"}]})
        else:
            items.append({"type": "taskItem", "attrs": {"checked": checked}, "content": inner})
    return items, index + 1


def _task_state(blocks: list[Node]) -> bool | None:
    """Strips a leading ``[ ]``/``[x]`` off the item's first paragraph and says which it was."""
    if not blocks or blocks[0].get("type") != "paragraph":
        return None
    content = blocks[0].get("content") or []
    if not content or content[0].get("type") != "text":
        return None
    match = _TASK_PREFIX.match(content[0]["text"])
    if not match:
        return None
    content[0]["text"] = content[0]["text"][match.end() :]
    if not content[0]["text"]:
        content.pop(0)
    if content:
        blocks[0]["content"] = content
    else:
        blocks[0].pop("content", None)
    return match.group(1).lower() == "x"


def _find_inline(tokens: list[Token], index: int, closer: str) -> tuple[list[Node], int]:
    inline: list[Node] = []
    while index < len(tokens) and tokens[index].type != closer:
        if tokens[index].type == "inline":
            inline = _inline_nodes(tokens[index].children or [])
        index += 1
    return inline, index + 1


def _inline_nodes(children: list[Token]) -> list[Node]:
    nodes: list[Node] = []
    marks: list[Node] = []

    def push(text: str) -> None:
        if not text:
            return
        node: Node = {"type": "text", "text": text}
        if marks:
            node["marks"] = [dict(mark) for mark in marks]
        nodes.append(node)

    for child in children:
        kind = child.type
        if kind == "text":
            push(child.content)
        elif kind == "code_inline":
            nodes.append({"type": "text", "text": child.content, "marks": [*marks, {"type": "code"}]})
        elif kind == "softbreak":
            push(" ")
        elif kind == "hardbreak":
            nodes.append({"type": "hardBreak"})
        elif kind == "strong_open":
            marks.append({"type": "bold"})
        elif kind == "em_open":
            marks.append({"type": "italic"})
        elif kind == "s_open":
            marks.append({"type": "strike"})
        elif kind == "link_open":
            marks.append({"type": "link", "attrs": {"href": child.attrGet("href") or ""}})
        elif kind in ("strong_close", "em_close", "s_close", "link_close"):
            if marks:
                marks.pop()
        elif kind == "html_inline":
            push(child.content)
        elif kind == "image":
            push(child.content or "")
    return nodes
