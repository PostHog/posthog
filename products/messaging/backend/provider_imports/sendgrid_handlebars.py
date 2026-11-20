"""Reads SendGrid's Handlebars into a tree of text, output tags and blocks, for sendgrid_templates.py to turn into Liquid.

Follows the Handlebars grammar where SendGrid templates use it: https://handlebarsjs.com/guide/expressions.html.
Anything outside it raises _Malformed or _Unconvertible, and the converter keeps that part as text.
"""

import re
import html as html_lib
from collections.abc import Iterator
from dataclasses import replace
from typing import Literal

from posthog.dataclasses import frozen

_OPENING = re.compile(r"\{[{%]")
# The email renderer treats a backslash or an HTML entity inside a filter argument differently from SendGrid.
_UNSAFE_IN_LIQUID_STRING = re.compile(r"\\|&(?:\w+|#\d+|#[xX][0-9a-fA-F]+);")
_MAX_TAG_LENGTH = 2000
_LONG_COMMENT_CLOSE = re.compile(r"--~?\}\}")
# Handlebars identifiers never hold these, and the converter writes identifiers into Liquid.
# The renderer decodes HTML entities inside a tag, so `&` is refused too.
_UNSAFE_IN_IDENTIFIER = re.compile(r"[{}%|\"'\\<>&]")
_MAX_DEPTH = 50
_EXPRESSION_TOKEN = re.compile(
    r"""\s*(?:
        (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<number>-?\d+(?:\.\d+)?)(?=[\s)=]|$)
      | (?P<open>\()
      | (?P<close>\))
      | (?P<equals>=)
      | (?P<path>(?:\[[^\]]*\]|[^\s()=\[\]])+)
    )""",
    re.VERBOSE,
)


def liquid_literal(tag: str) -> str:
    # A raw block ends at the first `endraw` and needs a close of its own, so these print their openings another way.
    if "endraw" in tag or tag in ("{{", "{%"):
        return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', tag)
    return f"{{% raw %}}{tag}{{% endraw %}}"


def liquid_string(value: str) -> str | None:
    if any(braces in value for braces in ("{{", "}}", "{%", "%}")) or _UNSAFE_IN_LIQUID_STRING.search(value):
        return None
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return None


class _Unconvertible(Exception):
    """This tag has no faithful Liquid form. Its text stays visible and a note names it."""


class _Malformed(Exception):
    """The template doesn't parse as Handlebars, so none of its tags can be trusted."""


# Parse tree -----------------------------------------------------------------------------------------------------------


@frozen
class _Text:
    text: str


@frozen
class _Liquid:
    liquid: str


@frozen
class _Output:
    source: str
    body: str
    raw: bool


@frozen
class _Block:
    source_open: str
    source_close: str
    name: str
    params: tuple[object, ...]
    hash_args: dict[str, object]
    block_params: tuple[str, ...]
    inverted: bool
    body: tuple[object, ...]
    inverse: tuple[object, ...] = ()
    # Written as `{{else if x}}`, so it sits in the block before it.
    chained: bool = False


@frozen
class _Tag:
    kind: Literal["text", "liquid", "output", "open", "close", "else", "comment"]
    source: str
    body: str = ""
    raw: bool = False
    strip_before: bool = False
    strip_after: bool = False
    inverted: bool = False


def _tokenize(source: str, is_html: bool) -> list[_Tag]:
    tags: list[_Tag] = []
    position = 0
    while position < len(source):
        start = source.find("{{", position)
        if start == -1:
            tags.append(_Tag(kind="text", source=source[position:]))
            break
        if start - 2 >= position and source[start - 2 : start] == "\\\\":
            # Two backslashes print as one, and the tag after them still runs.
            tags.append(_Tag(kind="text", source=source[position : start - 1]))
            tag, position = _read_tag(source, start, is_html)
            tags.append(tag)
            continue
        if start > position and source[start - 1] == "\\":
            # Handlebars prints an escaped tag as it's written, without the backslash.
            end = source.find("}}", start)
            end = len(source) if end == -1 else end + 2
            tags.append(_Tag(kind="text", source=source[position : start - 1]))
            tags.append(_Tag(kind="liquid", source=liquid_literal(source[start:end])))
            position = end
            continue
        if start > position:
            tags.append(_Tag(kind="text", source=source[position:start]))
        tag, position = _read_tag(source, start, is_html)
        tags.append(tag)
    return _strip_whitespace(tags)


def _read_tag(source: str, start: int, is_html: bool) -> tuple[_Tag, int]:
    if source.startswith("{{{{", start):
        raise _Malformed("raw blocks")
    if source.startswith(("{{!--", "{{~!--"), start):
        comment_close = _LONG_COMMENT_CLOSE.search(source, start)
        if comment_close is None:
            raise _Malformed("an unclosed comment")
        raw = source[start : comment_close.end()]
        return _Tag(
            kind="comment", source=raw, strip_before=raw.startswith("{{~"), strip_after=raw.endswith("~}}")
        ), comment_close.end()
    triple = source.startswith("{{{", start)
    closer = "}}}" if triple else "}}"
    close = source.find(closer, start)
    if close == -1 or close - start > _MAX_TAG_LENGTH:
        raise _Malformed("an unclosed tag")
    end = close + len(closer)
    raw_tag = source[start:end]
    body = source[start + len(closer) : close].strip()
    if is_html:
        # An HTML editor can save the quotes inside a tag as entities.
        body = html_lib.unescape(body)
    strip_before = body.startswith("~")
    strip_after = body.endswith("~")
    body = body.strip("~").strip()
    comment = _Tag(kind="comment", source=raw_tag, strip_before=strip_before, strip_after=strip_after)
    if body.startswith("!"):
        return comment, end
    if body.startswith("#") and not body.startswith("#>") and not body.startswith("#*"):
        return replace(comment, kind="open", body=body[1:].strip()), end
    if body.startswith("^") and body[1:].strip():
        return replace(comment, kind="open", body=body[1:].strip(), inverted=True), end
    if body.startswith("/"):
        return replace(comment, kind="close", body=body[1:].strip()), end
    if body == "^" or body == "else" or re.match(r"else\s", body):
        return replace(comment, kind="else", body=body[4:].strip() if body != "^" else ""), end
    return replace(comment, kind="output", body=body, raw=triple), end


def _strip_whitespace(tags: list[_Tag]) -> list[_Tag]:
    """`~` removes the whitespace beside a tag. So does Handlebars for a block tag alone on its line, and leaving that
    in would add blank lines to every plain text email."""
    texts = {i: tag.source for i, tag in enumerate(tags) if tag.kind == "text"}
    # Handlebars decides whether a tag stands alone from the template as written, before any `~` trims it.
    alone = {
        i
        for i, tag in enumerate(tags)
        if tag.kind in ("open", "close", "else", "comment")
        and _alone_on_line(i, texts.get(i - 1), texts.get(i + 1), len(tags))
    }
    # The closing tag of an `{{else if}}` chain stands alone only when the first branch also ends its line.
    chains: list[int | None] = []
    for i, tag in enumerate(tags):
        if tag.kind == "open":
            chains.append(None)
        elif tag.kind == "else" and tag.body and chains and chains[-1] is None:
            chains[-1] = i
        elif tag.kind == "close" and chains:
            first_else = chains.pop()
            if first_else is not None and not _starts_line(first_else, texts.get(first_else - 1)):
                alone.discard(i)
    for i, tag in enumerate(tags):
        if tag.kind in ("text", "liquid"):
            continue
        before = texts.get(i - 1)
        after = texts.get(i + 1)
        if i in alone:
            if before is not None:
                texts[i - 1] = before = before[: before.rfind("\n") + 1]
            if after is not None:
                newline = after.find("\n")
                texts[i + 1] = after = after[newline + 1 :] if newline != -1 else ""
        if tag.strip_before and before is not None:
            texts[i - 1] = before.rstrip()
        if tag.strip_after and after is not None:
            texts[i + 1] = after.lstrip()
    return [_Tag(kind="text", source=texts[i]) if tag.kind == "text" else tag for i, tag in enumerate(tags)]


def _starts_line(index: int, before: str | None) -> bool:
    if before is None:
        return index == 0
    return not before[before.rfind("\n") + 1 :].strip(" \t") and ("\n" in before or index == 1)


def _alone_on_line(index: int, before: str | None, after: str | None, count: int) -> bool:
    starts_line = _starts_line(index, before)
    if after is None:
        ends_line = index == count - 1
    else:
        newline = after.find("\n")
        ends_line = not (after[:newline] if newline != -1 else after).strip(" \t\r") and (
            newline != -1 or index == count - 2
        )
    return starts_line and ends_line


@frozen
class _ParsedNodes:
    nodes: tuple[object, ...]
    position: int
    stop: _Tag | None


def _parse_nodes(tags: list[_Tag]) -> tuple[object, ...]:
    parsed = _parse_until(tags, 0, 0)
    if parsed.stop is not None or parsed.position != len(tags):
        raise _Malformed("a closing tag without its opening tag")
    return parsed.nodes


def _parse_until(tags: list[_Tag], position: int, depth: int) -> _ParsedNodes:
    if depth > _MAX_DEPTH:
        raise _Malformed("blocks nested too deeply")
    nodes: list[object] = []
    while position < len(tags):
        tag = tags[position]
        if tag.kind == "close" or tag.kind == "else":
            return _ParsedNodes(nodes=tuple(nodes), position=position, stop=tag)
        position += 1
        if tag.kind == "text":
            nodes.append(_Text(text=tag.source))
        elif tag.kind == "liquid":
            nodes.append(_Liquid(liquid=tag.source))
        elif tag.kind == "output":
            # An output follows the same grammar as a block, so a name that can't be written into Liquid is refused.
            _parse_expression(tag.body.removeprefix("&").strip())
            nodes.append(_Output(source=tag.source, body=tag.body, raw=tag.raw))
        elif tag.kind == "open":
            block, position = _parse_block(tags, position, tag, depth)
            nodes.append(block)
    return _ParsedNodes(nodes=tuple(nodes), position=position, stop=None)


def _parse_block(
    tags: list[_Tag], position: int, opening: _Tag, depth: int, close_name: str | None = None
) -> tuple[_Block, int]:
    expression = _parse_expression(opening.body)
    name, params, hash_args, block_params = (
        expression.name,
        expression.params,
        expression.hash_args,
        expression.block_params,
    )
    # `{{#if a}}{{else equals b c}}{{/if}}` closes with the name of the block that opened the chain.
    closes_with = close_name or name
    parsed = _parse_until(tags, position, depth + 1)
    body, position, stop = parsed.nodes, parsed.position, parsed.stop
    inverse: tuple[object, ...] = ()
    if stop is not None and stop.kind == "else":
        position += 1
        if stop.body:
            chained, position = _parse_block(
                tags, position, _Tag(kind="open", source=stop.source, body=stop.body), depth + 1, closes_with
            )
            inverse = (replace(chained, chained=True),)
            return _block(opening, name, params, hash_args, block_params, body, inverse, chained.source_close), position
        parsed = _parse_until(tags, position, depth + 1)
        inverse, position, stop = parsed.nodes, parsed.position, parsed.stop
        if stop is not None and stop.kind == "else":
            raise _Malformed("a block with two else tags")
    if stop is None or stop.kind != "close" or stop.body != closes_with:
        raise _Malformed(f"a block {name} without its closing tag")
    return _block(opening, name, params, hash_args, block_params, body, inverse, stop.source), position + 1


def _block(
    opening: _Tag,
    name: str,
    params: tuple[object, ...],
    hash_args: dict[str, object],
    block_params: tuple[str, ...],
    body: tuple[object, ...],
    inverse: tuple[object, ...],
    source_close: str,
) -> _Block:
    return _Block(
        source_open=opening.source,
        source_close=source_close,
        name=name,
        params=params,
        hash_args=hash_args,
        block_params=block_params,
        inverted=opening.inverted,
        body=body,
        inverse=inverse,
    )


# Expressions ----------------------------------------------------------------------------------------------------------


@frozen
class _Literal:
    liquid: str
    # The text the value compares as, for a format or a default.
    text: str | None = None


@frozen
class _Path:
    source: str


@frozen
class _Call:
    name: str
    params: tuple[object, ...]


@frozen
class _Expression:
    """A helper's name, its parameters, its `key=value` arguments, and the names after `as |...|`."""

    name: str
    params: tuple[object, ...]
    hash_args: dict[str, object]
    block_params: tuple[str, ...]


@frozen
class _Token:
    kind: str
    value: str


def _parse_expression(body: str) -> _Expression:
    block_params: tuple[str, ...] = ()
    match = re.search(r"\bas\s*\|([^|]*)\|\s*$", body)
    if match:
        block_params = tuple(match.group(1).split())
        if any(not re.fullmatch(r"[A-Za-z_][\w-]*", name) for name in block_params):
            raise _Unconvertible(body)
        body = body[: match.start()]
    tokens = list(_expression_tokens(body))
    if not tokens or tokens[0].kind != "path":
        raise _Unconvertible(body)
    params: list[object] = []
    hash_args: dict[str, object] = {}
    position = 1
    while position < len(tokens):
        if position + 1 < len(tokens) and tokens[position + 1].kind == "equals":
            # Handlebars only takes a name before `=`.
            if tokens[position].kind != "path":
                raise _Unconvertible(body)
            key = tokens[position].value
            value, position = _parse_param(tokens, position + 2)
            hash_args[key] = value
            continue
        value, position = _parse_param(tokens, position)
        params.append(value)
    return _Expression(name=tokens[0].value, params=tuple(params), hash_args=hash_args, block_params=block_params)


def _expression_tokens(body: str) -> Iterator[_Token]:
    position = 0
    body = body.rstrip()
    while position < len(body):
        match = _EXPRESSION_TOKEN.match(body, position)
        if not match or match.end() == position:
            raise _Unconvertible(body)
        kind = match.lastgroup or ""
        if kind == "path" and _UNSAFE_IN_IDENTIFIER.search(match.group(kind)):
            raise _Unconvertible(body)
        yield _Token(kind=kind, value=match.group(kind))
        position = match.end()


def _parse_param(tokens: list[_Token], position: int, depth: int = 0) -> tuple[object, int]:
    if position >= len(tokens):
        raise _Unconvertible("missing value")
    if depth > _MAX_DEPTH:
        raise _Unconvertible("nested groups")
    kind, value = tokens[position].kind, tokens[position].value
    if kind == "string":
        # Handlebars only turns an escaped quote into a quote and keeps every other backslash.
        quote = value[0]
        text = value[1:-1].replace("\\" + quote, quote)
        return _Literal(liquid=_required_string(text), text=text), position + 1
    if kind == "number":
        return _Literal(liquid=value, text=value), position + 1
    if kind == "open":
        if position + 1 >= len(tokens) or tokens[position + 1].kind != "path":
            raise _Unconvertible("empty group")
        name = tokens[position + 1].value
        position += 2
        params: list[object] = []
        while position < len(tokens) and tokens[position].kind != "close":
            param, position = _parse_param(tokens, position, depth + 1)
            params.append(param)
        if position >= len(tokens):
            raise _Unconvertible("unclosed group")
        return _Call(name=name, params=tuple(params)), position + 1
    if kind == "path":
        if value in ("true", "false"):
            return _Literal(liquid=value, text=value), position + 1
        if value in ("null", "undefined"):
            return _Literal(liquid="nil"), position + 1
        return _Path(source=value), position + 1
    raise _Unconvertible(value)


def _required_string(text: str) -> str:
    literal = liquid_string(text)
    if literal is None:
        raise _Unconvertible(text)
    return literal
