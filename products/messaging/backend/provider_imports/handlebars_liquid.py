"""Turns a parsed Handlebars template into PostHog's Liquid one tag at a time.

A tag with a Liquid form that prints what Handlebars prints converts. Any other tag stays as written, and its source
lands in `unsupported` so the import can name it. A block that stays as written keeps everything inside it as written
too. The rest of the template converts around it.

Conditions follow Handlebars, where missing, null, false, "", 0 and an empty list are false, and everything else,
such as a string of spaces or an empty object, is true. Liquid's `blank` also matches those two, so conditions test
each false value instead. `x.length == 0 and x == empty` matches only "" and an empty list: `empty` alone also
matches an empty object, and `length` alone an object with a `length` key. Liquid reads `and` and `or` from the right,
so the last test groups as intended.

`{{#each}}` becomes a `for` loop over the values Handlebars would loop over: a list's items or an object's values,
and none for anything else. Liquid alone would loop over an object's key and value pairs, and over a string once.
"""

import re
import math
from collections.abc import Callable, Collection, Iterator
from typing import Literal

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.html_context import HtmlContext, Place
from products.messaging.backend.provider_imports.sendgrid_handlebars import (
    _Block,
    _Call,
    _Liquid,
    _Literal,
    _Output,
    _parse_expression,
    _Path,
    _Text,
    _Unconvertible,
    liquid_literal,
    liquid_string,
)

# Liquid reads `size`, `first` and `last` as properties of any list or object, where Handlebars finds nothing.
_SEGMENT = re.compile(r"(?!(?:size|first|last)$)[^\W\d][\w-]*")
# Names the send already defines, so a loop variable can't hide them.
_TAKEN_NAMES = frozenset(
    {"variables", "person", "event", "groups", "project", "source", "inputs", "now", "record", "forloop"}
    | {"unsubscribe_url", "unsubscribe_url_one_click", "empty", "blank", "nil", "true", "false"}
    # Liquid reads these as operators inside a condition.
    | {"and", "or", "contains", "in"}
)
# Names the converter assigns for a loop's values. A loop variable of the same name would hide them.
_LIST_NAME = re.compile(r"(?:values|shape|string|raw)\d+")
# Names the converter assigns before a comparison. A loop variable of the same name would hide them.
_ASSIGNED_NAME = re.compile(r"(?:text|length|truthy|probe)\d+")
# An HTML editor can save a tag's quotes and other characters as entities. Which text a provider then compares or
# prints is unclear, so a tag holding one stays as written.
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]*);", re.IGNORECASE)
_LOOP_DATA = {"@index": "forloop.index0", "@first": "forloop.first", "@last": "forloop.last"}
# Each provider adds its own helpers to Handlebars:
# https://www.twilio.com/docs/sendgrid/for-developers/sending-email/using-handlebars and
# https://documentation.mailgun.com/docs/mailgun/user-manual/sending-messages/send-templates.
Dialect = Literal["sendgrid", "mailgun"]
_COMPARISONS: dict[Dialect, dict[str, str]] = {
    "sendgrid": {"equals": "==", "notEquals": "!=", "greaterThan": ">", "lessThan": "<"},
    "mailgun": {"equal": "=="},
}
# SendGrid's formatDate takes Moment-style tokens. Each maps to the strftime code Liquid's `date` filter takes.
_DATE_TOKENS = {
    "YYYY": "%Y",
    "YY": "%y",
    "MMMM": "%B",
    "MMM": "%b",
    "MM": "%m",
    "M": "%-m",
    "DD": "%d",
    "D": "%-d",
    "dddd": "%A",
    "ddd": "%a",
    "HH": "%H",
    "H": "%-H",
    "hh": "%I",
    "h": "%-I",
    "mm": "%M",
    "m": "%-M",
    "ss": "%S",
    "s": "%-S",
    "A": "%p",
    "a": "%P",
}
# A run of one letter is one token, so a run with no strftime code, such as DDD (day of the year), stays as written.
_DATE_TOKEN = re.compile(r"([A-Za-z])\1*|[^A-Za-z]+")
_MAX_OUTPUT_CHARS = 5_000_000
# The entities are written escaped, because an editor that parses the HTML decodes it once, and so does a send.
HTML_ESCAPE = ' | escape | replace: "=", "&amp;#x3D;" | replace: "`", "&amp;#x60;"'


@frozen
class TextValue:
    """A provider tag found in plain text, such as SendGrid's `<%asm_group_unsubscribe_raw_url%>`."""

    source: str
    # A link URL may sit in a quoted attribute, and a whole link may only sit in page text.
    in_attribute: bool
    liquid: str | None = None
    # A variable the app passes, printed like a Handlebars value.
    value_path: str | None = None
    # Prints HTML unescaped, so it's only valid in page text.
    raw: bool = False
    # Prints the tag itself when the app passes no value.
    stays_when_missing: bool = False


TextSplitter = Callable[[str], Iterator["str | TextValue"]]


class OutputTooLarge(Exception):
    pass


class _Unsupported(Exception):
    pass


@frozen
class _Frame:
    """A Handlebars context: the Liquid path `this` reads, and the names a loop's `as |item index|` gives."""

    this: str
    loop: bool = False
    item_name: str | None = None
    index_name: str | None = None


class HandlebarsToLiquid:
    def __init__(
        self,
        *,
        is_html: bool,
        dialect: Dialect,
        root_value: Callable[[str], str | None] = lambda _name: None,
        split_text: TextSplitter | None = None,
        root_path: str = "variables",
        variable_names: Collection[str] = (),
        allows_raw: bool = True,
    ) -> None:
        self.is_html = is_html
        self._dialect = dialect
        self.unsupported: list[str] = []
        self.converted: list[str] = []
        self._root_value = root_value
        self._split_text = split_text
        self._root_path = root_path
        # Stay under `variables` when `root_path` is something else.
        self._variable_names = variable_names
        self._allows_raw = allows_raw
        self.read_root = False
        self._html = HtmlContext() if is_html else None
        self._loop_names: list[str] = []
        self._after_raw_html = False
        self._written = 0
        self._lists = 0
        self._assigned = 0
        self._converted_root = ""

    def convert(self, nodes: tuple[object, ...]) -> str:
        converted = self._nodes(nodes, (_Frame(this=self._root_path),))
        return self._within_limit(converted)

    @staticmethod
    def _within_limit(liquid: str) -> str:
        # Liquid counts length in UTF-16 units, so a character outside the basic plane counts twice.
        if len(liquid.encode("utf-16-le")) // 2 > _MAX_OUTPUT_CHARS:
            raise OutputTooLarge
        return liquid

    # Nodes ------------------------------------------------------------------------------------------------------------

    def _nodes(self, nodes: tuple[object, ...], frames: tuple[_Frame, ...]) -> str:
        out: list[str] = []
        for index, node in enumerate(nodes):
            following = nodes[index + 1] if index + 1 < len(nodes) else None
            if isinstance(node, _Text):
                for piece in self._text(node.text):
                    _append(out, self._spend(piece, literal=True))
            elif isinstance(node, _Liquid):
                _append(out, self._spend(self._kept(node.liquid, node.printed), literal=True))
            elif isinstance(node, _Output):
                after = following.text if isinstance(following, _Text) else ""
                _append(out, self._spend(self._output(node, frames, after), literal=True))
            elif isinstance(node, _Block):
                _append(out, self._block(node, frames))
        return "".join(out)

    def _attribute_safe(self, liquid: str) -> str:
        """Liquid for a double-quoted attribute. A double quote in it would end the attribute for an editor that parses
        the HTML, and a send decodes the entity before it renders the tag."""
        return liquid.replace('"', "&quot;") if self._html is not None and self._html.state == "dq" else liquid

    def _spend(self, chunk: str, *, literal: bool = False) -> str:
        """Counts what the conversion writes as it goes, so a template whose paths grow with nesting stops early."""
        if not literal:
            chunk = self._attribute_safe(chunk)
        self._written += len(chunk)
        if self._written > _MAX_OUTPUT_CHARS:
            raise OutputTooLarge
        return chunk

    def _text(self, text: str) -> Iterator[str]:
        pieces = list(self._split_text(text)) if self._split_text else [text]
        for index, piece in enumerate(pieces):
            following = pieces[index + 1] if index + 1 < len(pieces) else ""
            if isinstance(piece, str):
                self._feed(piece)
                yield _literal_text(piece)
                continue
            whole = (
                piece.in_attribute
                and not piece.raw
                and self._is_whole_unquoted_value(following if isinstance(following, str) else "")
            )
            if (piece.liquid or piece.value_path) and (whole or self._piece_fits(piece)):
                liquid = self._text_value(piece)
                yield _in_quotes(liquid) if whole else self._attribute_safe(liquid)
                self._feed('"x"' if whole else "x")
                self._after_raw_html = self._after_raw_html or (piece.raw and self.is_html)
                self.converted.append(piece.source)
            else:
                self.unsupported.append(piece.source)
                self._feed(piece.source)
                yield _literal_text(piece.source)

    def _text_value(self, piece: TextValue) -> str:
        if piece.value_path is None:
            return piece.liquid or ""
        value = self._print_piece(piece.value_path, raw=piece.raw)
        if not piece.stays_when_missing:
            return value
        return f"{{% if {piece.value_path} == nil %}}{_literal_text(piece.source)}{{% else %}}{value}{{% endif %}}"

    def _output(self, node: _Output, frames: tuple[_Frame, ...], following: str = "") -> str:
        if self.is_html and _ENTITY.search(node.source):
            return self._literal(node.source)
        body, raw = node.body, node.raw
        self._converted_root = ""
        if body.startswith("&"):
            body, raw = body[1:].strip(), True
        raw = raw and self._allows_raw
        try:
            liquid, raw = self._output_liquid(body, raw, frames)
        except (_Unsupported, _Unconvertible):
            return self._literal(node.source)
        whole = not raw and self._is_whole_unquoted_value(following)
        if not whole and not self._value_fits(raw=raw, in_attribute=True):
            return self._literal(node.source)
        self._feed('"x"' if whole else "x")
        self._after_raw_html = self._after_raw_html or (raw and self.is_html)
        if self._converted_root:
            self.converted.append(self._converted_root)
        return _in_quotes(liquid) if whole else self._attribute_safe(liquid)

    def _output_liquid(self, body: str, raw: bool, frames: tuple[_Frame, ...]) -> tuple[str, bool]:
        expression = _parse_expression(body)
        name, params = expression.name, expression.params
        if expression.hash_args or expression.block_params:
            raise _Unsupported
        if not params:
            if len(frames) == 1 and (special := self._root_value(name)) is not None:
                self._converted_root = name
                return special, False
            if (special := self._special(name, frames)) is not None:
                return special, False
            return self._print(self._path(name, frames), raw), raw
        if self._dialect != "sendgrid":
            raise _Unsupported
        if name == "formatDate" and len(params) == 2:
            date_format = _date_format(params[1])
            date = f'{self._value_path(params[0], frames)} | date: {date_format}, "UTC"'
            return self._print(date, False, may_be_a_list=False), False
        if name == "insert" and len(params) <= 2:
            if isinstance(params[0], _Path) and (special := self._special(params[0].source, frames)) is not None:
                return special, False
            value = self._value_path(params[0], frames)
            if len(params) == 1:
                return self._print(value, raw), raw
            default = params[1].text if isinstance(params[1], _Literal) else None
            if default is None or not default.startswith("default="):
                raise _Unsupported
            fallback = liquid_string(default.removeprefix("default="))
            if fallback is None:
                raise _Unsupported
            return self._print(f"{value} | default: {fallback}", raw), raw
        if name == "length" and len(params) == 1:
            setup: list[str] = []
            length = self._counted(self._value_path(params[0], frames), setup)
            return "".join(setup) + self._print(length, False, may_be_a_list=False), False
        raise _Unsupported

    def _print(self, value: str, raw: bool, *, may_be_a_list: bool = True) -> str:
        if may_be_a_list:
            # Handlebars prints a list with commas between its items, and Liquid runs them together.
            value = f'{value} | join: ","'
        if not self.is_html:
            return f"{{{{ {value} }}}}"
        if raw:
            return f"{{{{ {value} | raw }}}}"
        if self._after_raw_html:
            # Raw HTML can leave a tag open, so this value could land in an unquoted attribute. Handlebars also encodes
            # = and ` there, so the value can't add an attribute of its own.
            return f"{{{{ {value}{HTML_ESCAPE} | raw }}}}"
        return f"{{{{ {value} }}}}"

    def _literal(self, source: str, *, noted: bool = True) -> str:
        if noted:
            self.unsupported.append(source)
        return self._kept(liquid_literal(source), source)

    def _kept(self, liquid: str, printed: str) -> str:
        """Liquid that prints a tag as it was written. A quote in the tag ends the attribute when the provider sends it
        too, so then nothing is encoded."""
        kept = liquid if '"' in printed else self._attribute_safe(liquid)
        self._feed(printed)
        return kept

    # Blocks -----------------------------------------------------------------------------------------------------------

    def _block(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        try:
            if self.is_html and _ENTITY.search(block.source_open):
                raise _Unsupported
            if block.name == "each" and not block.inverted:
                return self._each(block, frames)
            if block.name == "with" and not block.inverted:
                return self._with(block, frames)
            self._dry_condition(block, frames)
        except (_Unsupported, _Unconvertible):
            return self._literal_block(block)
        return self._if_chain(block, frames)

    def _if_chain(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        start = self._snapshot()
        parts: list[str] = []
        ends: list[Place | None] = []
        current: _Block | None = block
        keyword = "if"
        # A comparison may first assign a value as text, and Liquid only allows that before the whole chain.
        setup: list[str] = []
        in_double_quotes = self._html is not None and self._html.state == "dq"
        while current is not None:
            condition = self._condition(current, frames, setup)
            body = current.body
            parts.append(self._spend(f"{{% {keyword} {condition} %}}"))
            parts.append(self._branch(start, ends, body, frames))
            keyword = "elsif"
            inverse = current.inverse
            current = None
            if len(inverse) == 1 and isinstance(inverse[0], _Block) and inverse[0].chained:
                chained = inverse[0]
                try:
                    self._dry_condition(chained, frames)
                    current = chained
                    continue
                except (_Unsupported, _Unconvertible):
                    pass
            if inverse:
                parts.append(self._spend("{% else %}"))
                parts.append(self._branch(start, ends, inverse, frames))
            else:
                ends.append(start)
        self._merge(ends)
        assigns = "".join(setup)
        if in_double_quotes:
            assigns = assigns.replace('"', "&quot;")
        return _joined([self._spend(assigns, literal=True), *parts, self._spend("{% endif %}")])

    def _dry_condition(self, block: _Block, frames: tuple[_Frame, ...]) -> None:
        """Raises when the block has no condition, without using up assignment names."""
        assigned = self._assigned
        try:
            self._condition(block, frames, [])
        finally:
            self._assigned = assigned

    def _condition(self, block: _Block, frames: tuple[_Frame, ...], setup: list[str]) -> str:
        if self.is_html and _ENTITY.search(block.source_open):
            raise _Unsupported
        params, hash_args = block.params, block.hash_args
        if not block.parsed or block.block_params:
            raise _Unsupported
        # `{{^x}}` skips "" and 0, unlike `{{#unless x}}`, and Liquid has no test that tells "" from an empty list.
        if block.inverted:
            raise _Unsupported
        include_zero = _include_zero(hash_args)
        if block.name in ("if", "unless") and len(params) == 1:
            test = self._truthy if block.name == "if" else self._falsy
            return test(params[0], frames, setup, include_zero=include_zero)
        if hash_args:
            raise _Unsupported
        comparisons = _COMPARISONS[self._dialect]
        if block.name in comparisons and len(params) == 2:
            operator = comparisons[block.name]
            if operator in ("==", "!="):
                # A missing value prints as "undefined" and null as "null" when compared as text, and Liquid can't
                # tell them apart or from "". Against a literal that is neither, all three compare unequal anyway.
                if all(isinstance(param, _Path) for param in params):
                    raise _Unsupported
                left, right = self._as_text(params[0], frames, setup), self._as_text(params[1], frames, setup)
            else:
                left, right = self._operand(params[0], frames, setup), self._operand(params[1], frames, setup)
            return f"{left} {operator} {right}"
        # Liquid reads `and` and `or` right to left with no brackets, so only `and` keeps each test whole.
        if self._dialect == "sendgrid" and block.name == "and" and len(params) >= 2:
            return " and ".join(
                self._whole(self._truthy(param, frames, setup, include_zero=False), setup) for param in params
            )
        raise _Unsupported

    def _each(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        if not block.parsed or len(block.params) != 1 or block.hash_args or len(block.block_params) > 2:
            raise _Unsupported
        (collection,) = block.params
        if not isinstance(collection, _Path):
            raise _Unsupported
        source = self._value_path(collection, frames)
        names = block.block_params
        loop_name = names[0] if names and self._free_name(names[0]) else self._next_loop_name()
        frame = _Frame(
            this=loop_name,
            loop=True,
            item_name=names[0] if names else None,
            index_name=names[1] if len(names) == 2 else None,
        )
        untrusted = self._html is not None and self._html.untrusted
        before = (len(self.unsupported), len(self.converted), self._written, self._assigned, self._after_raw_html)
        # The second pass of the body follows whatever raw HTML the first pass printed.
        self._after_raw_html = self._after_raw_html or (self.is_html and _has_raw_output(block.body))
        start = self._snapshot()
        # A loop body that runs zero times or many times has to leave the HTML where it found it.
        ends: list[Place | None] = [start]
        self._lists += 1
        n = self._lists
        values, shape, string, raw = f"values{n}", f"shape{n}", f"string{n}", f"raw{n}"
        # Handlebars loops over a list's items and an object's values, and over nothing else. Liquid loops over an
        # object's key and value pairs and over a string once. `slice: 0, 0` gives an empty list for a list or
        # nothing, and "" for anything else. `slice` reads anything else as text, and an object reads as
        # "[object Object]" whatever its keys, though an object never equals that text. Neither reads past the start
        # of the value, so a large list costs the renderer nothing.
        guard = self._spend(
            f"{{% assign {values} = {source} | slice: 0, 0 %}}{{% assign {string} = {source} | slice: 0, 16 %}}"
            f'{{% assign {shape} = "" %}}{{% if {values} != "" %}}{{% assign {shape} = "list" %}}'
            f'{{% elsif {string} == "[object Object]" and {source} != {string} %}}'
            f'{{% elsif {string} != "" %}}{{% assign {shape} = "text" %}}{{% endif %}}'
            f'{{% if {shape} == "text" %}}'
        )
        opening = self._spend(
            f"{{% else %}}{{% for {raw} in {source} %}}"
            f'{{% if {shape} == "list" %}}{{% assign {loop_name} = {raw} %}}'
            f"{{% else %}}{{% assign {loop_name} = {raw}[1] %}}{{% endif %}}"
        )
        self._loop_names.append(loop_name)
        try:
            body = self._branch(start, ends, block.body, (*frames, frame))
        finally:
            self._loop_names.pop()
        if ends[-1] != start or (self._html is not None and self._html.untrusted and not untrusted):
            # Each pass after the first starts where the last one ended, so values converted for the first pass
            # could land somewhere else, such as an unquoted attribute. A condition in the body whose branches end
            # in different places hides where that is.
            unsupported, converted, self._written, self._assigned, self._after_raw_html = before
            del self.unsupported[unsupported:], self.converted[converted:]
            if self._html is not None and start is not None:
                self._html.restore(start)
                self._html.untrusted = untrusted
            return self._literal_block(block)
        inverse = self._branch(start, ends, block.inverse, frames) if block.inverse else ""
        self._merge(ends)
        parts = [guard, inverse, opening, body]
        if inverse:
            parts.append(self._spend("{% else %}"))
            parts.append(self._spend(inverse, literal=True))
        return _joined([*parts, self._spend("{% endfor %}{% endif %}")])

    def _with(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        if not block.parsed or len(block.params) != 1 or block.hash_args or len(block.block_params) > 1:
            raise _Unsupported
        (target,) = block.params
        if not isinstance(target, _Path):
            raise _Unsupported
        this = self._value_path(target, frames)
        # Handlebars adds no level for a context that is already the current one, so `../` inside would point
        # one level further up than the frames say.
        if this == frames[-1].this:
            raise _Unsupported
        frame = _Frame(this=this, item_name=block.block_params[0] if block.block_params else None)
        start = self._snapshot()
        ends: list[Place | None] = []
        # Handlebars `with` skips its body only for an empty value, and 0 isn't one.
        opening = self._spend(f"{{% if {self._truthy(target, frames, [], include_zero=True)} %}}")
        body = self._branch(start, ends, block.body, (*frames, frame))
        parts = [opening, body]
        if block.inverse:
            parts.append(self._spend("{% else %}"))
            parts.append(self._branch(start, ends, block.inverse, frames))
        else:
            ends.append(start)
        self._merge(ends)
        return _joined([*parts, self._spend("{% endif %}")])

    def _literal_block(self, block: _Block) -> str:
        """Keeps the whole block as written. A value or tag inside it converted on its own would print whatever the
        block's condition was there to hide."""
        parts = [self._literal(block.source_open), self._literal_nodes(block.body)]
        if block.inverse:
            chained = block.inverse[0] if len(block.inverse) == 1 and isinstance(block.inverse[0], _Block) else None
            if chained is not None and chained.chained:
                # The rest of the chain stays as written, so each `{{else if}}` prints where it was.
                parts.append(self._literal_block(chained))
            else:
                parts.append(self._literal(block.source_else, noted=False))
                parts.append(self._literal_nodes(block.inverse))
        if not block.chained:
            parts.append(self._literal(block.source_close, noted=False))
        return _joined(parts)

    def _literal_nodes(self, nodes: tuple[object, ...]) -> str:
        out: list[str] = []
        for node in nodes:
            if isinstance(node, _Text):
                for piece in self._split_text(node.text) if self._split_text else (node.text,):
                    if not isinstance(piece, str):
                        self.unsupported.append(piece.source)
                        piece = piece.source
                    self._feed(piece)
                    _append(out, self._spend(_literal_text(piece), literal=True))
            elif isinstance(node, _Liquid):
                _append(out, self._spend(self._kept(node.liquid, node.printed), literal=True))
            elif isinstance(node, _Output):
                _append(out, self._spend(self._literal(node.source), literal=True))
            elif isinstance(node, _Block):
                _append(out, self._literal_block(node))
        return "".join(out)

    # Expressions ------------------------------------------------------------------------------------------------------

    def _path(self, source: str, frames: tuple[_Frame, ...]) -> str:
        if source in _LOOP_DATA:
            if not any(frame.loop for frame in frames):
                raise _Unsupported
            return _LOOP_DATA[source]
        if source.startswith("@root."):
            frames, source = frames[:1], source.removeprefix("@root.")
        elif source.startswith("@") or source in ("true", "false", "null", "undefined"):
            raise _Unsupported
        depth = len(frames) - 1
        while source.startswith("../"):
            depth -= 1
            source = source[3:]
        if depth < 0:
            raise _Unsupported
        frames = frames[: depth + 1]
        base = frames[-1].this
        if source in ("this", "."):
            parts: list[str] = []
        elif source.startswith(("this.", "./")):
            parts = source.split("/", 1)[1].split(".") if source.startswith("./") else source.split(".")[1:]
        else:
            parts = source.split(".")
            named = self._block_param(parts[0], frames)
            if named is not None:
                base, parts = named, parts[1:]
        if not all(_SEGMENT.fullmatch(part) for part in parts) or (not parts and base == self._root_path):
            raise _Unsupported
        if base == self._root_path and parts[0] in self._variable_names:
            base = "variables"
        self.read_root = self.read_root or base == self._root_path
        return ".".join([base, *parts])

    def _block_param(self, name: str, frames: tuple[_Frame, ...]) -> str | None:
        innermost_loop = next((frame for frame in reversed(frames) if frame.loop), None)
        for frame in reversed(frames):
            if frame.item_name == name:
                return frame.this
            if frame.index_name == name:
                if frame is not innermost_loop:
                    raise _Unsupported
                return "forloop.index0"
        return None

    def _special(self, source: str, frames: tuple[_Frame, ...]) -> str | None:
        """What a name with a meaning of its own converts to, written in a way that still reads the top level."""
        read_root = self.read_root
        base, _, name = self._path(source, frames).rpartition(".")
        special = self._root_value(name) if base == self._root_path else None
        if special is not None:
            self.read_root = read_root
            self._converted_root = name
        return special

    def _value_path(self, param: object, frames: tuple[_Frame, ...]) -> str:
        if not isinstance(param, _Path):
            raise _Unsupported
        # It isn't a value of the recipient's, so nothing can test, count or format it.
        if self._special(param.source, frames) is not None:
            self._converted_root = ""
            raise _Unsupported
        return self._path(param.source, frames)

    def _operand(self, param: object, frames: tuple[_Frame, ...], setup: list[str]) -> str:
        if isinstance(param, _Literal):
            # JavaScript reads null as 0 in a comparison, and Liquid's nil compares false with everything.
            if param.liquid == "nil":
                raise _Unsupported
            return param.liquid
        if isinstance(param, _Call):
            return self._counted(self._length(param, frames), setup)
        return self._value_path(param, frames)

    def _length(self, call: _Call, frames: tuple[_Frame, ...]) -> str:
        if self._dialect != "sendgrid" or call.name != "length" or len(call.params) != 1:
            raise _Unsupported
        return self._value_path(call.params[0], frames)

    def _counted(self, path: str, setup: list[str]) -> str:
        """SendGrid's `length` counts a list's items or a string's characters, and gives 0 for anything else. Liquid's
        `size` reads an object's `length` key, so an object, which `slice` reads as "[object Object]" but never equals
        that text, counts 0."""
        self._assigned += 1
        length, probe = f"length{self._assigned}", f"probe{self._assigned}"
        setup.append(
            f"{{% assign {probe} = {path} | slice: 0, 16 %}}{{% assign {length} = 0 %}}"
            f'{{% if {probe} != "[object Object]" or {path} == {probe} %}}{{% assign {length} = {path} | size %}}'
            "{% endif %}"
        )
        return length

    def _as_text(self, param: object, frames: tuple[_Frame, ...], setup: list[str]) -> str:
        """Both providers compare `equals` as text, so 5 equals "5". Liquid compares by type."""
        if isinstance(param, _Literal):
            if param.text is None or param.text in ("", "null", "undefined"):
                raise _Unsupported
            literal = liquid_string(_number_text(param.text) if _is_number(param) else param.text)
            if literal is None:
                raise _Unsupported
            return literal
        # A list compares as its items joined by commas, as JavaScript turns it into text.
        return self._assign(f'{self._operand(param, frames, setup)} | join: "," | append: ""', "text", setup)

    def _whole(self, condition: str, setup: list[str]) -> str:
        """A test that stays whole when joined to others with `and`. Liquid reads `and` and `or` from the right, so a
        test holding `or` is worked out first."""
        if " or " not in condition:
            return condition
        self._assigned += 1
        name = f"truthy{self._assigned}"
        # An assign, unlike a capture, holds no text, so the plain text part keeps it when it drops text from tags.
        setup.append(f"{{% assign {name} = false %}}{{% if {condition} %}}{{% assign {name} = true %}}{{% endif %}}")
        return f"{name} == true"

    def _assign(self, expression: str, prefix: str, setup: list[str]) -> str:
        self._assigned += 1
        name = f"{prefix}{self._assigned}"
        setup.append(f"{{% assign {name} = {expression} %}}")
        return name

    def _truthy(self, param: object, frames: tuple[_Frame, ...], setup: list[str], *, include_zero: bool) -> str:
        if isinstance(param, _Literal):
            return "true" if _literal_truthy(param, include_zero) else "false"
        if isinstance(param, _Call):
            if include_zero:
                # A length is always a number, so with includeZero only the check that it is one is left.
                self._length(param, frames)
                return "true"
            return f"{self._operand(param, frames, setup)} > 0"
        path = self._value_path(param, frames)
        if path == "forloop.index0":
            return "true" if include_zero else f"{path} != 0"
        if path.startswith("forloop."):
            return path
        zero = "" if include_zero else f" and {path} != 0"
        return f"{path} != nil and {path} != false{zero} and {path}.length != 0 or {path} != empty"

    def _falsy(self, param: object, frames: tuple[_Frame, ...], setup: list[str], *, include_zero: bool) -> str:
        if isinstance(param, _Literal):
            return "false" if _literal_truthy(param, include_zero) else "true"
        path = self._value_path(param, frames)
        if path == "forloop.index0":
            return "false" if include_zero else f"{path} == 0"
        if path.startswith("forloop."):
            return f"{path} == false"
        zero = "" if include_zero else f" or {path} == 0"
        return f"{path} == nil or {path} == false{zero} or {path}.length == 0 and {path} == empty"

    def _free_name(self, name: str) -> bool:
        return (
            bool(_SEGMENT.fullmatch(name))
            and name not in _TAKEN_NAMES
            and name not in self._loop_names
            and not _ASSIGNED_NAME.fullmatch(name)
            and not _LIST_NAME.fullmatch(name)
        )

    def _next_loop_name(self) -> str:
        count = 1
        while not self._free_name(name := "item" if count == 1 else f"item{count}"):
            count += 1
        return name

    # HTML context -----------------------------------------------------------------------------------------------------

    def _value_fits(self, *, raw: bool, in_attribute: bool) -> bool:
        """Whether a value sits where Liquid escapes it the way Handlebars does: page text, the page title, or a quoted
        attribute that holds no script or style."""
        if self._html is None:
            return True
        where = self._html.where()
        if self._html.untrusted:
            return False
        if where == "text":
            return True
        if where == "title":
            return not raw and in_attribute
        return where == "value" and in_attribute and not raw and self._html.plain_attribute()

    def _print_piece(self, value: str, *, raw: bool) -> str:
        return self._print(value, raw, may_be_a_list=not raw)

    def _piece_fits(self, piece: TextValue) -> bool:
        return self._value_fits(raw=piece.raw, in_attribute=piece.in_attribute)

    def _is_whole_unquoted_value(self, following: str) -> bool:
        """Whether the next value is all of an attribute written without quotes, as in `<a href={{x}}>`. Converting it
        adds the quotes, so a space in the value can't start another attribute."""
        return (
            self._html is not None
            and not self._html.untrusted
            and self._html.state == "before_value"
            and self._html.plain_attribute()
            and following[:1] in ("\t", "\n", "\f", "\r", " ", ">")
        )

    def _feed(self, text: str) -> None:
        if self._html is not None:
            self._html.feed(text)

    def _snapshot(self) -> Place | None:
        return self._html.snapshot() if self._html is not None else None

    def _branch(
        self, start: Place | None, ends: list[Place | None], nodes: tuple[object, ...], frames: tuple[_Frame, ...]
    ) -> str:
        if self._html is not None and start is not None:
            self._html.restore(start)
        converted = self._nodes(nodes, frames)
        ends.append(self._snapshot())
        return converted

    def _merge(self, ends: list[Place | None]) -> None:
        """Branches that leave the HTML in different places hide where later values sit, so none of them convert."""
        if self._html is None or ends[0] is None:
            return
        self._html.restore(ends[0])
        if any(end != ends[0] for end in ends):
            self._html.untrusted = True


def _has_raw_output(nodes: tuple[object, ...]) -> bool:
    for node in nodes:
        if isinstance(node, _Output) and (node.raw or node.body.startswith("&")):
            return True
        if isinstance(node, _Block) and (_has_raw_output(node.body) or _has_raw_output(node.inverse)):
            return True
    return False


def _include_zero(hash_args: dict[str, object]) -> bool:
    if not hash_args:
        return False
    value = hash_args.get("includeZero")
    if set(hash_args) != {"includeZero"} or not isinstance(value, _Literal) or value.text not in ("true", "false"):
        raise _Unsupported
    return value.text == "true"


def _is_number(literal: _Literal) -> bool:
    return literal.liquid == literal.text and literal.text not in ("true", "false")


def _number_text(text: str) -> str:
    """How JavaScript prints a number, which is the text Handlebars compares: `5.0` is the number 5 and prints as 5."""
    number = float(text)
    if number.is_integer() and abs(number) < 2**53:
        return str(int(number))
    shown = repr(number)
    # Past 2**53, in exponent form, or too large to hold (Python prints "inf", JavaScript "Infinity"), the two
    # print a number differently.
    if not math.isfinite(number) or number.is_integer() or "e" in shown:
        raise _Unsupported
    return shown


def _literal_truthy(literal: _Literal, include_zero: bool) -> bool:
    if literal.text is None or literal.liquid == "false":
        return False
    if literal.liquid == literal.text and literal.text != "true":
        return include_zero or float(literal.text) != 0
    return literal.text != ""


def _date_format(param: object) -> str:
    if not isinstance(param, _Literal) or not param.text or param.liquid == param.text:
        raise _Unsupported
    converted: list[str] = []
    for token in (match.group(0) for match in _DATE_TOKEN.finditer(param.text)):
        if token in _DATE_TOKENS:
            converted.append(_DATE_TOKENS[token])
        elif re.search(r"[A-Za-z\[\]]", token):
            raise _Unsupported
        else:
            converted.append(token.replace("%", "%%"))
    literal = liquid_string("".join(converted))
    if literal is None:
        raise _Unsupported
    return literal


def _literal_text(text: str) -> str:
    # Handlebars prints `{%` as it stands. Liquid would read it as a tag.
    return text.replace("{%", '{{ "{%" }}')


def _in_quotes(liquid: str) -> str:
    return f'"{liquid.replace('"', "&quot;")}"'


def _joined(chunks: list[str]) -> str:
    out: list[str] = []
    for chunk in chunks:
        _append(out, chunk)
    return "".join(out)


def _append(out: list[str], chunk: str) -> None:
    """Adds a chunk, so a `{` that ends one chunk and a `{` or `%` that starts the next never join into a Liquid tag."""
    if not chunk:
        return
    if out and out[-1].endswith("{") and chunk[0] in "{%":
        out[-1] = out[-1][:-1] + '{{ "{" }}'
    out.append(chunk)
