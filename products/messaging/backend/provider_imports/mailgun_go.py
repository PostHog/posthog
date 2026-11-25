"""Reads Mailgun's Go templates into the tree the Handlebars converter turns into Liquid.

Values, `if`, `range`, `with`, `else` and comments have the same meaning in both, so only how Go prints a value, what it
counts as true, and how it escapes a link differ. See https://pkg.go.dev/html/template.
"""

import re
from collections.abc import Iterator

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.handlebars_liquid import (
    HandlebarsToLiquid,
    TextSplitter,
    TextValue,
    _Frame,
)
from products.messaging.backend.provider_imports.html_context import Place
from products.messaging.backend.provider_imports.sendgrid_handlebars import _Block, _Literal, _Output, _Path, _Text

_MAX_DEPTH = 50
_TAG = re.compile(r"\{\{(?P<before>-(?=\s))?(?P<body>(?:(?!\{\{|\}\}).){0,2000})\}\}", re.DOTALL)
_COMMENT = re.compile(r"/\*.*\*/", re.DOTALL)
_NAME = r"[A-Za-z_]\w*"
_PATH = re.compile(rf"(?P<root>\$(?:{_NAME})?)?(?P<fields>(?:\.{_NAME})+)?|\.")
_LOOP_NAMES = re.compile(rf"\$(?P<first>{_NAME})(?:\s*,\s*\$(?P<second>{_NAME}))?\s*:=\s*(?P<list>\S+)")
_EQUAL = re.compile(r'eq\s+(?P<path>\S+)\s+"(?P<text>[^"\\]*)"')
# Names the converted Liquid uses itself.
_RESERVED_NAME = re.compile(r"this|variables|forloop|pair|and|or|not|nil|null|true|false|contains|empty|blank|\w*\d")
# Liquid reads these as properties of any list or object, where Go finds a field of that name.
_LIQUID_PROPERTIES = frozenset({"size", "first", "last"})
# The attributes html/template treats as plain text and as a link. It refuses or rewrites values in some others, such
# as `content` and anything that holds script or style.
_PLAIN_ATTRIBUTES = frozenset({"align", "alt", "class", "height", "id", "lang", "name", "title", "valign", "width"})
_LINK_ATTRIBUTES = frozenset({"href", "src"})
# Go rejects an unsafe scheme and rewrites a path, and Liquid can do neither, so a value only fits after a written-out
# address. An entity could hide where the query starts.
_LINK_QUERY = re.compile(r"https?://[^&?#\s<>\"']{0,2000}[?#]", re.IGNORECASE)


class GoUnsupported(Exception):
    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source = source


@frozen
class _GoTag:
    source: str
    # None for text.
    body: str | None


def _tags(text: str) -> Iterator[_GoTag]:
    position = 0
    trim_next = False
    while True:
        opening = text.find("{{", position)
        chunk = text[position:] if opening < 0 else text[position:opening]
        tag = _TAG.match(text, opening) if opening >= 0 else None
        if opening >= 0 and tag is None:
            raise GoUnsupported(text[opening : opening + 60].split("\n", 1)[0])
        if trim_next:
            chunk = chunk.lstrip(" \t\r\n")
        if tag is not None and tag["before"]:
            chunk = chunk.rstrip(" \t\r\n")
        if chunk:
            yield _GoTag(source=chunk, body=None)
        if tag is None:
            return
        body = tag["body"]
        trim_next = body[-1:] == "-" and body[-2:-1].isspace()
        body = (body[:-1] if trim_next else body).strip()
        if not _COMMENT.fullmatch(body):
            yield _GoTag(source=tag.group(0), body=body)
        position = tag.end()


class _Parser:
    def __init__(self, text: str) -> None:
        self._tags = list(_tags(text))
        self._position = 0

    def parse(self) -> tuple[object, ...]:
        nodes = self._nodes((), 0)
        if self._position < len(self._tags):
            raise GoUnsupported(self._tags[self._position].source)
        return nodes

    def _nodes(self, names: tuple[str, ...], depth: int) -> tuple[object, ...]:
        """Reads up to the tag that ends this branch, and leaves it for the caller."""
        nodes: list[object] = []
        while self._position < len(self._tags):
            tag = self._tags[self._position]
            if tag.body is None:
                nodes.append(_Text(text=tag.source))
                self._position += 1
            elif tag.body == "end" or re.match(r"else\b", tag.body):
                return tuple(nodes)
            elif re.match(r"(?:if|range|with)\s", tag.body):
                self._position += 1
                nodes.append(self._block(tag, tag.body, names, depth + 1, chained=False))
            else:
                path = self._path(tag.body, names, tag.source)
                nodes.append(_Output(source=tag.source, body=path, raw=False))
                self._position += 1
        return tuple(nodes)

    def _block(self, tag: _GoTag, body: str, names: tuple[str, ...], depth: int, *, chained: bool) -> _Block:
        if depth > _MAX_DEPTH:
            raise GoUnsupported(tag.source)
        keyword, rest = body.split(maxsplit=1)
        block_params: tuple[str, ...] = ()
        params: tuple[object, ...]
        inner = names
        if keyword == "range":
            name = "each"
            if declared := _LOOP_NAMES.fullmatch(rest):
                item = declared["second"] or declared["first"]
                if _RESERVED_NAME.fullmatch(item):
                    raise GoUnsupported(tag.source)
                # The other name is a list's index or a map's key, which Liquid can't tell apart.
                block_params = (item,)
                inner = (*(name for name in names if name != declared["first"]), item)
                rest = declared["list"]
            params = (_Path(source=self._path(rest, names, tag.source)),)
        elif keyword == "with":
            name = "with"
            params = (_Path(source=self._path(rest, names, tag.source)),)
        elif equal := _EQUAL.fullmatch(rest):
            name = "equal"
            text = equal["text"]
            params = (
                _Path(source=self._path(equal["path"], names, tag.source)),
                _Literal(liquid=f'"{text}"', text=text),
            )
        else:
            negated = re.match(r"not\s+", rest)
            name = "unless" if negated else "if"
            params = (_Path(source=self._path(rest[negated.end() :] if negated else rest, names, tag.source)),)
        content = self._nodes(inner, depth)
        inverse: tuple[object, ...] = ()
        ending = self._next(tag)
        if ending.body is not None and (chain := re.fullmatch(r"else\s+(if\s.*)", ending.body, re.DOTALL)):
            if keyword != "if":
                raise GoUnsupported(ending.source)
            inverse = (self._block(ending, chain[1], names, depth + 1, chained=True),)
        elif ending.body == "else":
            inverse = self._nodes(names, depth)
            ending = self._next(tag)
            if ending.body != "end":
                raise GoUnsupported(ending.source)
        elif ending.body != "end":
            raise GoUnsupported(ending.source)
        return _Block(
            source_open=tag.source,
            source_close="",
            name=name,
            params=params,
            hash_args={},
            block_params=block_params,
            inverted=False,
            body=content,
            inverse=inverse,
            chained=chained,
        )

    def _next(self, opened: _GoTag) -> _GoTag:
        if self._position >= len(self._tags):
            raise GoUnsupported(opened.source)
        tag = self._tags[self._position]
        self._position += 1
        return tag

    @staticmethod
    def _path(source: str, names: tuple[str, ...], tag: str) -> str:
        if source == ".":
            return "this"
        match = _PATH.fullmatch(source)
        if not source or match is None:
            raise GoUnsupported(tag)
        root, fields = match["root"], (match["fields"] or "").removeprefix(".")
        # The converter reads `this` as the value it is in, where Go finds a field of that name.
        if {"this", *_LIQUID_PROPERTIES}.intersection(fields.split(".")):
            raise GoUnsupported(tag)
        if root is None:
            return f"./{fields}"
        if root == "$":
            if not fields:
                raise GoUnsupported(tag)
            return f"@root.{fields}"
        if root[1:] not in names:
            raise GoUnsupported(tag)
        return f"{root[1:]}.{fields}" if fields else root[1:]


class GoToLiquid(HandlebarsToLiquid):
    """Converts a Go template. The caller keeps the whole template as text when any part of it didn't convert."""

    def __init__(self, *, is_html: bool, split_text: TextSplitter) -> None:
        super().__init__(is_html=is_html, dialect="mailgun", split_text=split_text)
        self._kinds: dict[str, str] = {}
        self._inline_kinds = 0
        # What the source wrote in the attribute so far, or None when a block makes that unclear.
        self._attribute_start: str | None = ""

    def convert_go(self, text: str) -> str:
        converted = self.convert(_Parser(text).parse())
        setup = "".join(f"{{% assign {kind} = {path} | json | slice: 0 %}}" for path, kind in self._kinds.items())
        return self._within_limit(setup + converted)

    def _print(self, value: str, raw: bool, *, may_be_a_list: bool = True) -> str:
        if value.startswith("forloop."):
            return f"{{{{ {value} }}}}"
        setup = ""
        if value.startswith("variables."):
            # Each value's kind is worked out once, at the top of the template, so every use can read it.
            kind = self._kinds.setdefault(value, f"go_value{len(self._kinds) + 1}")
        else:
            self._inline_kinds += 1
            kind = f"go_item{self._inline_kinds}"
            setup = f"{{% assign {kind} = {value} | json | slice: 0 %}}"
        # Go prints a list as [a b] and a map as map[key:value], so the value's JSON says which it is.
        return (
            f'{setup}{{% if {kind} == "[" %}}[{self._shown(f"{value} | join: ' '")}]'
            f'{{% elsif {kind} == "{{" %}}map[{{% for pair in {value} %}}{{% unless forloop.first %}} {{% endunless %}}'
            f"{self._shown('pair[0]')}:{self._shown('pair[1]')}{{% endfor %}}]"
            f"{{% else %}}{self._shown(value)}{{% endif %}}"
        )

    def _shown(self, value: str) -> str:
        if not self.is_html:
            return f"{{{{ {value} }}}}"
        if self._in_link_query():
            # Go encodes everything but letters, digits and `-._~` in a link's query, with a space as %20.
            return f'{{{{ {value} | cgi_escape | replace: "+", "%20" }}}}'
        if self._in_attribute():
            # Only quoted attributes take a value, so `escape` is enough, as in Go.
            return f"{{{{ {value} | escape | raw }}}}"
        # Handlebars also escapes = and `, so a value can't end an unquoted attribute and start another one.
        return f'{{{{ {value} | escape | replace: "=", "&amp;#x3D;" | replace: "`", "&amp;#x60;" | raw }}}}'

    def _truthy(self, param: object, frames: tuple[_Frame, ...], setup: list[str], *, include_zero: bool) -> str:
        path = self._value_path(param, frames)
        return (
            path
            if path.startswith("forloop.")
            else f"{path} != nil and {path} != false and {path} != 0 and {path} != empty"
        )

    def _falsy(self, param: object, frames: tuple[_Frame, ...], setup: list[str], *, include_zero: bool) -> str:
        path = self._value_path(param, frames)
        return f"{path} == nil or {path} == false or {path} == 0 or {path} == empty"

    # HTML context -----------------------------------------------------------------------------------------------------

    def _in_attribute(self) -> bool:
        return self._html is not None and self._html.where() == "value"

    def _in_link_query(self) -> bool:
        return (
            self._html is not None
            and self._in_attribute()
            and self._html.attribute in _LINK_ATTRIBUTES
            and self._attribute_start is not None
            and bool(_LINK_QUERY.match(self._attribute_start))
        )

    def _value_fits(self, *, raw: bool, in_attribute: bool) -> bool:
        if self._html is None:
            return True
        if not super()._value_fits(raw=raw, in_attribute=in_attribute):
            return False
        if not self._in_attribute():
            return True
        return self._html.state == "dq" and (self._html.attribute in _PLAIN_ATTRIBUTES or self._in_link_query())

    def _print_piece(self, value: str, *, raw: bool) -> str:
        # Mailgun fills these after Go has run, so Go never encodes them for a link.
        return super()._print(value, raw)

    def _piece_fits(self, piece: TextValue) -> bool:
        # Only the import writes a piece's own Liquid, such as the unsubscribe link, so any address fits.
        return (
            super()._value_fits(raw=False, in_attribute=piece.in_attribute)
            if piece.liquid
            else super()._piece_fits(piece)
        )

    def _is_whole_unquoted_value(self, following: str) -> bool:
        return False

    def _feed(self, text: str) -> None:
        was_in_value = self._in_attribute()
        super()._feed(text)
        if not self._in_attribute():
            self._attribute_start = ""
            return
        assert self._html is not None
        quote = '"' if self._html.state == "dq" else "'"
        head, found, tail = text.rpartition(quote)
        if found or not was_in_value:
            self._attribute_start = tail if found else None
        elif self._attribute_start is not None:
            self._attribute_start += text

    def _branch(
        self, start: Place | None, ends: list[Place | None], nodes: tuple[object, ...], frames: tuple[_Frame, ...]
    ) -> str:
        self._attribute_start = None if start is not None and start.state in ("dq", "sq") else ""
        converted = super()._branch(start, ends, nodes, frames)
        if self._in_attribute():
            self._attribute_start = None
        return converted
