"""Turns a SendGrid template into PostHog's Liquid, and says what did not carry over.

Dynamic templates use Handlebars with SendGrid's own helpers:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/using-handlebars. Legacy templates use `-name-` tags:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/substitution-tags.

Liquid reads values differently from Handlebars, so a plain rewrite of the tags would change what people receive. An
empty string, a 0 and an empty list are false in Handlebars and true in Liquid, and SendGrid's `equals` treats 3 and "3"
as equal where Liquid doesn't. Conditions here spell those rules out, so they are longer than a person would write.
"""

import re
import html as html_lib
from collections.abc import Callable, Iterator
from dataclasses import field, replace
from functools import partial

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.sendgrid_handlebars import (
    _Block,
    _Call,
    _Condition,
    _Liquid,
    _Literal,
    _Malformed,
    _Output,
    _parse_expression,
    _parse_nodes,
    _Path,
    _required_string,
    _Text,
    _tokenize,
    _Unconvertible,
    liquid_literal,
)

_MAX_NOTED_TAGS = 5
_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%LZ"
# Handlebars also encodes = and `, so a value in an unquoted attribute can't add an attribute of its own.
_HTML_ESCAPE = ' | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;"'
# Handlebars prints an array with commas between its items, and Liquid prints them run together.
_AS_TEXT = ' | join: ","'

_UNSUBSCRIBE_VARIABLES = {"unsubscribe", "unsubscribe_preferences"}
_SENDER_VARIABLES = {"Sender_Name", "Sender_Address", "Sender_City", "Sender_State", "Sender_Zip"}
_CONTACT_VARIABLES = {
    "first_name",
    "last_name",
    "email",
    "alternate_emails",
    "address_line_1",
    "address_line_2",
    "city",
    "state_province_region",
    "postal_code",
    "country",
    "phone_number",
    "whatsapp",
    "line",
    "facebook",
    "unique_name",
}
_COMPARISONS = {"equals", "notEquals", "greaterThan", "lessThan"}
_BLOCKS = {"if", "unless", "each", "with", "and", "or"} | _COMPARISONS

# https://www.twilio.com/docs/sendgrid/ui/sending-email/group-unsubscribes
_ASM_TAG = re.compile(r"(?:<|&lt;)%\s*([\w.]+)\s*%(?:>|&gt;)")
_ASM_URLS = {"asm_group_unsubscribe_raw_url", "asm_global_unsubscribe_raw_url", "asm_preferences_raw_url"}
_ASM_LINKS = {
    "asm_group_unsubscribe_url": "Unsubscribe From This List",
    "asm_global_unsubscribe_url": "Unsubscribe From All Emails",
    "asm_preferences_url": "Manage Email Preferences",
}

_DATE_TOKEN = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|dddd|ddd|DD|D|hh|h|HH|H|mm|m|ss|s|A|ZZ|Z")
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
    "hh": "%I",
    "h": "%-I",
    "HH": "%H",
    "H": "%-H",
    "mm": "%M",
    "m": "%-M",
    "ss": "%S",
    "s": "%-S",
    "A": "%p",
    "ZZ": "%z",
    "Z": "%:z",
}
_TIMEZONE_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
# Bracketed text, ordinals and the tokens below have no strftime equivalent, so a format with them stays as written.
_UNREPRESENTABLE_DATE = re.compile(r"[\[\]]|(?:M|DDD|D|d|Q|w|W)o|Q|X|x|SSS|ww|WW|gg|GG|E|e")

_SEGMENT = re.compile(r"\[([^\]]*)\]|([^./\[\]]+)")
_LIQUID_NAME = re.compile(r"^[A-Za-z_][\w-]*$")


@frozen
class ConvertedSendGridTemplate:
    subject: str
    html: str
    text: str
    notes: tuple[str, ...]
    # About values the app passes when it sends.
    send_notes: tuple[str, ...] = ()


@frozen
class _Frame:
    """A level of Handlebars context. Handlebars adds one for `each` and `with`, not for `if`."""

    prefix: str
    names: dict[str, str] = field(default_factory=dict)
    is_loop: bool = False


# Conversion -----------------------------------------------------------------------------------------------------------


class _Converter:
    def __init__(self, is_html: bool, contact_fields: bool) -> None:
        self.is_html = is_html
        self.contact_fields = contact_fields
        self.unsupported: list[str] = []
        self.compared_as_text: list[str] = []
        self.date_notes: list[str] = []
        self.uses_unsubscribe = False
        self.sender_variables: set[str] = set()
        self.contact_variables: set[str] = set()
        self.web_link = False
        self.uses_legacy_slots = False
        self._next_temp = 0

    def nodes(self, nodes: tuple[object, ...], frames: tuple[_Frame, ...]) -> str:
        return "".join(self.node(node, frames) for node in nodes)

    def node(self, node: object, frames: tuple[_Frame, ...]) -> str:
        if isinstance(node, _Text):
            # Handlebars prints `{%` as it stands. Liquid would read it as a tag.
            text = node.text.replace("{%", '{{ "{%" }}')
            # A dropped comment or trimmed space can put this `{` next to a `{` or `%` from the next node.
            return f'{text[:-1]}{{{{ "{{" }}}}' if text.endswith("{") else text
        if isinstance(node, _Liquid):
            return node.liquid
        if isinstance(node, _Output):
            return self.output(node, frames)
        if isinstance(node, _Block):
            return self.block(node, frames)
        raise TypeError(type(node).__name__)

    def literal(self, tag: str) -> str:
        self.unsupported.append(tag)
        return liquid_literal(tag)

    def temp(self) -> str:
        self._next_temp += 1
        return f"sg_{self._next_temp}"

    def output(self, node: _Output, frames: tuple[_Frame, ...]) -> str:
        body = node.body
        raw = node.raw
        if body.startswith("&"):
            body, raw = body[1:].strip(), True
        try:
            if body.startswith((">", "*")):
                raise _Unconvertible(body)
            expression = _parse_expression(body)
            name, params, hash_args = expression.name, expression.params, expression.hash_args
            if name == "insert":
                return self._insert(params, raw, frames)
            if name == "formatDate":
                return self._format_date(params, raw, frames)
            if name == "length":
                if len(params) != 1 or hash_args:
                    raise _Unconvertible(body)
                return f"{{{{ {self._size(params[0], frames)} | plus: 0 }}}}"
            if params or hash_args:
                raise _Unconvertible(body)
            if name in _UNSUBSCRIBE_VARIABLES:
                self.uses_unsubscribe = True
                return "{{ unsubscribe_url }}"
            if name == "Weblink":
                self.web_link = True
                return ""
            if name in _SENDER_VARIABLES:
                self.sender_variables.add(name)
            elif self.contact_fields and name in _CONTACT_VARIABLES:
                self.contact_variables.add(name)
            return self._print(self._path(name, frames), raw)
        except _Unconvertible:
            return self.literal(node.source)

    def _print(self, value: str, raw: bool, filters: str = "") -> str:
        if self.is_html and not raw:
            return f"{{{{ {value}{filters}{_AS_TEXT}{_HTML_ESCAPE} | raw }}}}"
        escape = " | raw" if raw and self.is_html else ""
        return f"{{{{ {value}{filters}{_AS_TEXT}{escape} }}}}"

    def _insert(self, params: tuple[object, ...], raw: bool, frames: tuple[_Frame, ...]) -> str:
        if not params or len(params) > 2:
            raise _Unconvertible("insert")
        filters = ""
        if len(params) == 2:
            default = params[1]
            if not isinstance(default, _Literal) or default.text is None:
                raise _Unconvertible("insert")
            text = default.text.removeprefix("default=")
            filters = f" | default: {_required_string(text)}"
        return self._print(self._value(params[0], frames), raw, filters)

    def _format_date(self, params: tuple[object, ...], raw: bool, frames: tuple[_Frame, ...]) -> str:
        if not params or len(params) > 3:
            raise _Unconvertible("formatDate")
        value = self._value(params[0], frames)
        strftime = _ISO_FORMAT
        if len(params) > 1:
            date_format = params[1]
            if isinstance(date_format, _Literal) and date_format.text is not None:
                if _UNREPRESENTABLE_DATE.search(date_format.text):
                    raise _Unconvertible("formatDate")
                strftime = _DATE_TOKEN.sub(lambda t: _DATE_TOKENS[t.group(0)], date_format.text.replace("%", "%%"))
            else:
                self.date_notes.append(_describe(date_format))
        minutes = 0
        if len(params) > 2:
            offset = params[2]
            match = _TIMEZONE_OFFSET.match(offset.text or "") if isinstance(offset, _Literal) else None
            if match is None:
                self.date_notes.append(_describe(offset))
            else:
                total = int(match.group(2)) * 60 + int(match.group(3))
                # LiquidJS counts the offset the way JavaScript does: positive is behind UTC.
                minutes = -total if match.group(1) == "+" else total
        return self._print(value, raw, f" | date: {_required_string(strftime)}, {minutes}")

    def _value(self, param: object, frames: tuple[_Frame, ...]) -> str:
        if isinstance(param, _Literal):
            return param.liquid
        if isinstance(param, _Path):
            return self._path(param.source, frames)
        if isinstance(param, _Call) and param.name == "length" and len(param.params) == 1:
            return self._size(param.params[0], frames)
        raise _Unconvertible(_describe(param))

    def _size(self, param: object, frames: tuple[_Frame, ...]) -> str:
        return f"{self._value(param, frames)}.size"

    def _path(self, source: str, frames: tuple[_Frame, ...]) -> str:
        path = source
        # Handlebars reads a block alias only from a bare name, never from a path that names its context.
        scoped = path in ("this", ".") or path.startswith(("this.", "this/", "./", "../"))
        if path.startswith("@root"):
            return _join("variables", _segments(path[len("@root") :].lstrip(".")))
        if path.startswith("@"):
            return self._loop_value(path[1:], frames)
        frame_index = len(frames) - 1
        while path.startswith("../"):
            path = path[3:]
            frame_index -= 1
            if frame_index < 0:
                raise _Unconvertible(source)
        path = path.removeprefix("./")
        frame = frames[frame_index]
        if path in ("this", "."):
            return frame.prefix
        path = path.removeprefix("this.").removeprefix("this/")
        segments = _segments(path)
        if not segments:
            raise _Unconvertible(source)
        for candidate in () if scoped else reversed(frames[: frame_index + 1]):
            if segments[0] in candidate.names:
                return _join(candidate.names[segments[0]], segments[1:])
        return _join(frame.prefix, segments)

    def _loop_value(self, name: str, frames: tuple[_Frame, ...]) -> str:
        loop = next((frame for frame in reversed(frames) if frame.is_loop), None)
        if loop is None:
            raise _Unconvertible(f"@{name}")
        values = {"index": "forloop.index0", "first": "forloop.first", "last": "forloop.last"}
        if name not in values:
            raise _Unconvertible(f"@{name}")
        return values[name]

    def block(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        written = block
        try:
            if block.name not in _BLOCKS and not (block.inverted and not block.params):
                raise _Unconvertible(block.name)
            if block.inverted and block.name in ("each", "with"):
                # `{{^each xs}}a{{else}}b{{/each}}` is the block with its two parts swapped.
                block = replace(block, body=block.inverse, inverse=block.body, inverted=False)
            if block.name == "each":
                return self._each(block, frames, written)
            if block.name == "with":
                return self._with(block, frames)
            test = self.condition(block, frames)
            prelude, condition = test.prelude, test.condition
        except _Unconvertible:
            # The whole block stays as text, so a value it guards can't print without the condition around it.
            self.unsupported.append(written.source_open)
            return self._block_as_text(written)
        tag = "unless" if (block.name == "unless") != block.inverted else "if"
        opening = f"{prelude}{{% {tag} {condition} %}}"
        return f"{opening}{self.nodes(block.body, frames)}{self._else(block, frames)}{{% end{tag} %}}"

    def _else(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        if not block.inverse:
            return ""
        first = block.inverse[0]
        if len(block.inverse) == 1 and isinstance(first, _Block) and first.chained and first.name == "if":
            try:
                test = self.condition(first, frames)
            except _Unconvertible:
                test = _Condition(prelude="", condition="")
            if test.condition and not test.prelude:
                body = self.nodes(first.body, frames)
                return f"{{% elsif {test.condition} %}}{body}{self._else(first, frames)}"
        return f"{{% else %}}{self.nodes(block.inverse, frames)}"

    def condition(self, block: _Block, frames: tuple[_Frame, ...]) -> _Condition:
        params = block.params
        if block.name not in _BLOCKS:
            return self._truthy(_Path(source=block.name), frames)
        if block.name in ("if", "unless"):
            if len(params) != 1:
                raise _Unconvertible(block.name)
            include_zero = block.hash_args.get("includeZero")
            keeps_zero = isinstance(include_zero, _Literal) and include_zero.liquid == "true"
            return self._truthy(params[0], frames, keeps_zero)
        if block.name in _COMPARISONS:
            return self._comparison(block, frames)
        if not params:
            raise _Unconvertible(block.name)
        parts = [self._truthy(param, frames) for param in params]
        if block.name == "and":
            return _Condition(
                prelude="".join(part.prelude for part in parts),
                condition=" and ".join(part.condition for part in parts),
            )
        # Liquid has no brackets and reads `a and b or c` from the right, so each side of an `or` goes in a flag first.
        prelude = ""
        flags = []
        for part in parts:
            flag = self.temp()
            flags.append(flag)
            prelude += (
                f"{part.prelude}{{% if {part.condition} %}}{{% assign {flag} = true %}}"
                f"{{% else %}}{{% assign {flag} = false %}}{{% endif %}}"
            )
        return _Condition(prelude=prelude, condition=" or ".join(flags))

    def _truthy(self, param: object, frames: tuple[_Frame, ...], keeps_zero: bool = False) -> _Condition:
        if isinstance(param, _Call) and param.name in _COMPARISONS:
            call = _Block(
                source_open="",
                source_close="",
                name=param.name,
                params=param.params,
                hash_args={},
                block_params=(),
                inverted=False,
                body=(),
            )
            return self._comparison(call, frames)
        if isinstance(param, _Call) and param.name == "length":
            value = self.temp()
            return _Condition(
                prelude=f"{{% assign {value} = {self._value(param, frames)} | plus: 0 %}}", condition=f"{value} != 0"
            )
        if isinstance(param, _Literal):
            return _Condition(prelude="", condition="true" if _literal_truthy(param, keeps_zero) else "false")
        value = self._value(param, frames)
        if value in ("forloop.first", "forloop.last"):
            return _Condition(prelude="", condition=value)
        zero = "" if keeps_zero else f" and {value} != 0"
        # `empty` checks a list's length without reading a field named size from an object.
        return _Condition(prelude="", condition=f"{value}{zero} and {value} != empty")

    def _comparison(self, block: _Block, frames: tuple[_Frame, ...]) -> _Condition:
        if len(block.params) != 2:
            raise _Unconvertible(block.name)
        left, right = block.params
        if block.name in ("equals", "notEquals"):
            operator = "==" if block.name == "equals" else "!="
            if _is_nil(left) or _is_nil(right):
                return _Condition(
                    prelude="", condition=f"{self._value(left, frames)} {operator} {self._value(right, frames)}"
                )
            self.compared_as_text.append(block.source_open or f"({block.name})")
            convert = ' | append: ""'
        else:
            operator = ">" if block.name == "greaterThan" else "<"
            convert = " | plus: 0"
        first, second = self.temp(), self.temp()
        prelude = (
            f"{{% assign {first} = {self._value(left, frames)}{convert} %}}"
            f"{{% assign {second} = {self._value(right, frames)}{convert} %}}"
        )
        return _Condition(prelude=prelude, condition=f"{first} {operator} {second}")

    def _each(self, block: _Block, frames: tuple[_Frame, ...], written: _Block) -> str:
        if len(block.params) != 1 or len(block.block_params) > 2:
            raise _Unconvertible("each")
        # Liquid loops over an object as [key, value] pairs, and Handlebars over its values. Every loop is converted
        # as a loop over a list, and one that reads an object's keys stays as text for a person to rewrite.
        if _uses_key(block.body):
            self.unsupported.append(block.source_open)
            return self._block_as_text(written)
        collection = self._value(block.params[0], frames)
        depth = sum(1 for frame in frames if frame.is_loop)
        name = f"item{depth + 1}" if depth else "item"
        names: dict[str, str] = {}
        if block.block_params:
            names[block.block_params[0]] = name
        # A nested loop has its own forloop, so the index is kept in a variable an inner loop can still read.
        index = f"{name}_index" if len(block.block_params) == 2 else None
        if index:
            names[block.block_params[1]] = index
        body = self.nodes(block.body, (*frames, _Frame(prefix=name, names=names, is_loop=True)))
        if index:
            body = f"{{% assign {index} = forloop.index0 %}}{body}"
        otherwise = f"{{% else %}}{self.nodes(block.inverse, frames)}" if block.inverse else ""
        return f"{{% for {name} in {collection} %}}{body}{otherwise}{{% endfor %}}"

    def _kept_as_text(self, nodes: tuple[object, ...]) -> str:
        """The nodes as they were written, so none of them prints a value meant for another context."""
        parts = []
        for node in nodes:
            if isinstance(node, _Output):
                parts.append(liquid_literal(node.source))
            elif isinstance(node, _Block):
                parts.append(self._block_as_text(node))
            else:
                parts.append(self.node(node, ()))
        return "".join(parts)

    def _block_as_text(self, block: _Block, closing: bool = True) -> str:
        first = block.inverse[0] if len(block.inverse) == 1 else None
        if isinstance(first, _Block) and first.chained:
            # `{{else if b}}` opens the chained block, and the block that opened the chain closes both.
            inverse = self._block_as_text(first, closing=False)
        elif block.inverse:
            inverse = liquid_literal("{{else}}") + self._kept_as_text(block.inverse)
        else:
            inverse = ""
        close = liquid_literal(block.source_close) if closing else ""
        return liquid_literal(block.source_open) + self._kept_as_text(block.body) + inverse + close

    def _with(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        if len(block.params) != 1:
            raise _Unconvertible("with")
        test = self._truthy(block.params[0], frames)
        prelude, condition = test.prelude, test.condition
        value = self._value(block.params[0], frames)
        names = {block.block_params[0]: value} if block.block_params else {}
        body = self.nodes(block.body, (*frames, _Frame(prefix=value, names=names)))
        otherwise = f"{{% else %}}{self.nodes(block.inverse, frames)}" if block.inverse else ""
        return f"{prelude}{{% if {condition} %}}{body}{otherwise}{{% endif %}}"


def _literal_truthy(literal: _Literal, keeps_zero: bool) -> bool:
    if literal.liquid in ("nil", "false"):
        return False
    if literal.liquid.startswith(("'", '"')):
        return literal.text != ""
    if literal.liquid == "true":
        return True
    return keeps_zero or float(literal.liquid) != 0


def _is_nil(param: object) -> bool:
    return isinstance(param, _Literal) and param.liquid == "nil"


def _describe(param: object) -> str:
    if isinstance(param, _Path):
        return param.source
    if isinstance(param, _Literal):
        return param.text or param.liquid
    return "this value"


def _uses_key(nodes: tuple[object, ...]) -> bool:
    for node in nodes:
        if isinstance(node, _Output) and _expression_uses_key(node.body.removeprefix("&").strip()):
            return True
        if isinstance(node, _Block):
            if _reads_key((_Path(source=node.name), *node.params, *node.hash_args.values())):
                return True
            # A nested each has its own @key.
            if node.name != "each" and (_uses_key(node.body) or _uses_key(node.inverse)):
                return True
    return False


def _expression_uses_key(body: str) -> bool:
    try:
        expression = _parse_expression(body)
    except (_Unconvertible, _Malformed):
        # A tag that doesn't parse is kept as text anyway, so only a plain mention of @key matters here.
        return "@key" in body
    return _reads_key((_Path(source=expression.name), *expression.params, *expression.hash_args.values()))


def _reads_key(params: tuple[object, ...]) -> bool:
    for param in params:
        if isinstance(param, _Path) and param.source == "@key":
            return True
        if isinstance(param, _Call) and _reads_key(param.params):
            return True
    return False


def _segments(path: str) -> list[str]:
    if not path:
        return []
    return [literal if literal else plain for literal, plain in _SEGMENT.findall(path)]


def _join(prefix: str, segments: list[str]) -> str:
    result = prefix
    for segment in segments:
        if segment.isdigit():
            result += f"[{segment}]"
        elif _LIQUID_NAME.match(segment):
            result += f".{segment}"
        else:
            result += f"[{_required_string(segment)}]"
    return result


# Whole templates ------------------------------------------------------------------------------------------------------


def _convert_asm_tags(text: str, is_html: bool, converter: _Converter) -> str:
    def convert(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _ASM_URLS:
            converter.uses_unsubscribe = True
            return "{{ unsubscribe_url }}"
        if name in _ASM_LINKS:
            converter.uses_unsubscribe = True
            return f'<a href="{{{{ unsubscribe_url }}}}">{_ASM_LINKS[name]}</a>' if is_html else "{{ unsubscribe_url }}"
        if name == "body":
            converter.uses_legacy_slots = True
            return "{{ variables.body | raw }}" if is_html else "{{ variables.body }}"
        if name == "subject":
            converter.uses_legacy_slots = True
            return "{{ variables.subject }}"
        converter.unsupported.append(match.group(0))
        return match.group(0)

    return _ASM_TAG.sub(convert, text)


def _convert_handlebars(source: str | None, is_html: bool, contact_fields: bool) -> tuple[str, _Converter]:
    converter = _Converter(is_html, contact_fields)
    # The placeholders below are marked with NUL, which an email can't hold, so a source with one can't fake them.
    source = (source or "").replace("\x00", "")
    if not source:
        return "", converter
    with_asm = _convert_asm_placeholders(source)
    try:
        tree = _parse_nodes(_tokenize(with_asm, is_html))
    except (_Malformed, _Unconvertible):
        return _literal_everything(source, converter, is_html), converter
    frames = (_Frame(prefix="variables"),)
    return _restore_asm(converter.nodes(tree, frames), is_html, converter), converter


# Set aside while the Handlebars is parsed, because `<%...%>` reads as text to the parser and its result is Liquid.
_ASM_PLACEHOLDER = "\x00asm:{}\x00"
_ASM_PLACEHOLDER_PATTERN = re.compile("\x00asm:(.*?)\x00", re.DOTALL)


def _convert_asm_placeholders(source: str) -> str:
    return _ASM_TAG.sub(lambda match: _ASM_PLACEHOLDER.format(match.group(0)), source)


def _restore_asm(text: str, is_html: bool, converter: _Converter) -> str:
    return _ASM_PLACEHOLDER_PATTERN.sub(lambda match: _convert_asm_tags(match.group(1), is_html, converter), text)


# Tag bodies are capped and stop at the next opening, so text full of unclosed braces scans in linear time.
_ANY_LIQUID_OPENING = re.compile(r"\{\{(?:(?!\{\{).){0,2000}?\}\}|\{%(?:(?!\{%).){0,2000}?%\}|\{\{|\{%", re.DOTALL)


def _literal_everything(source: str, converter: _Converter, is_html: bool) -> str:
    converter.unsupported.append("this template's tags, which don't form valid Handlebars")
    literal = _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), source)
    return _convert_asm_tags(literal, is_html, converter)


_SUBSTITUTION_TAG = re.compile(r"(?<![\w-])-([A-Za-z_]\w*)-(?![\w-])")
_OTHER_SUBSTITUTION_MARKS = re.compile(r"(?<![\w%#<;])([%#])[A-Za-z_]\w*\1(?![\w%#>&])")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_NOT_CONTENT_OPENING = re.compile(r"<(style|script|head|title)\b|<!--", re.IGNORECASE)


@frozen
class _Span:
    start: int
    end: int


def _not_content_spans(html: str) -> Iterator[_Span]:
    """Where the style, script and comment blocks are. Each closing tag is looked for once, so an unclosed opening
    repeated many times can't make this quadratic."""
    # str.lower() can change the length of a string (`İ` becomes two code points), and these offsets slice `html`.
    lowered = html.translate(_ASCII_LOWER)
    position = 0
    closed: set[str] = set()
    while match := _NOT_CONTENT_OPENING.search(html, position):
        closer = f"</{match.group(1).lower()}" if match.group(1) else "-->"
        end = lowered.find(closer, match.end()) if closer not in closed else -1
        if end == -1:
            closed.add(closer)
            position = match.end()
            continue
        end = lowered.find(">", end) + 1 if closer != "-->" else end + len(closer)
        if end <= 0:
            closed.add(closer)
            position = match.end()
            continue
        yield _Span(start=match.start(), end=end)
        position = end


def _map_content(html: str, convert: Callable[[str], str], keep: Callable[[str], str]) -> str:
    parts = []
    position = 0
    for span in _not_content_spans(html):
        parts += [convert(html[position : span.start]), keep(html[span.start : span.end])]
        position = span.end
    parts.append(convert(html[position:]))
    return "".join(parts)


def _convert_legacy(source: str | None, is_html: bool, tags: list[str]) -> tuple[str, _Converter]:
    converter = _Converter(is_html, False)
    if not source:
        return "", converter

    def convert(match: re.Match[str]) -> str:
        tags.append(match.group(0))
        # SendGrid leaves a tag as it stands when the send has no value for it. A word that only looks like a tag
        # stays readable for the same reason.
        raw = " | raw" if is_html else ""
        return f'{{{{ variables.{match.group(1)} | default: "{match.group(0)}"{raw} }}}}'

    def convert_content(content: str, substitute: bool = True) -> str:
        pieces = []
        position = 0
        # A legacy template isn't Handlebars, so braces in it are plain text.
        for match in _ANY_LIQUID_OPENING.finditer(content):
            between = content[position : match.start()]
            pieces += [
                _SUBSTITUTION_TAG.sub(convert, between) if substitute else between,
                liquid_literal(match.group(0)),
            ]
            position = match.end()
        rest = content[position:]
        pieces.append(_SUBSTITUTION_TAG.sub(convert, rest) if substitute else rest)
        return "".join(pieces)

    converted = (
        _map_content(source, convert_content, partial(convert_content, substitute=False))
        if is_html
        else convert_content(source)
    )
    return _convert_asm_tags(converted, is_html, converter), converter


_HTML_LINK = re.compile(
    r"<a\b[^<>]{0,2000}?\bhref\s*=\s*[\"']([^\"'<>]{1,2000})[\"'][^<>]{0,2000}>((?:(?!<a\b).){0,5000}?)</a\s*>",
    re.DOTALL | re.IGNORECASE,
)
_HTML_LINE_BREAK = re.compile(r"<br\s*/?>|</(?:p|div|tr|li|h[1-6]|table|ul|ol)\s*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^<>]*>")
# A quoted string is one piece, so the `{{` inside `{{ "{{" }}` doesn't start a tag of its own. Atomic groups keep
# a quote from being retried as a plain character, which would make long runs of quotes slow.
_LIQUID_TAG = re.compile(
    r"\{\{(?>\"[^\"]{0,2000}\"|'[^']{0,2000}'|(?!\{\{).){0,2000}?\}\}"
    r"|\{%(?>\"[^\"]{0,2000}\"|'[^']{0,2000}'|(?!\{%).){0,2000}?%\}",
    re.DOTALL,
)
_LIQUID_SLOT = re.compile("\x01(\\d+)\x01")
_RAW_OPEN = re.compile(r"\{%-?\s*raw\s*-?%\}")
_RAW_CLOSE = re.compile(r"\{%-?\s*endraw\s*-?%\}")


def _hold_raw_blocks(text: str, tags: list[str]) -> str:
    """Holds each `{% raw %}...{% endraw %}` block whole. Held in parts, removing an HTML tag around one part could
    drop the opening and leave what the block kept literal free to run."""
    parts: list[str] = []
    position = 0
    while (opening := _RAW_OPEN.search(text, position)) and (closing := _RAW_CLOSE.search(text, opening.end())):
        tags.append(text[opening.start() : closing.end()])
        parts.append(f"{text[position : opening.start()]}\x01{len(tags) - 1}\x01")
        position = closing.end()
    return "".join(parts) + text[position:]


def _without_raw_filter(tag: str) -> str:
    if not tag.startswith("{{") or not tag.endswith("}}"):
        return tag
    body = tag[2:-2].rstrip()
    if not body.endswith("raw") or not (head := body[:-3].rstrip()).endswith("|"):
        return tag
    head = head[:-1].rstrip()
    # The HTML part escapes what it prints, and plain text shows characters as they are.
    return f"{{{{{head.removesuffix(_HTML_ESCAPE)} }}}}"


def plain_text_from_html(html: str) -> str:
    """The plain text part SendGrid would have built from the HTML when it sent the email. PostHog only sends a plain
    text part it's given, so this happens at import."""
    tags: list[str] = []

    def hold(match: re.Match[str]) -> str:
        tags.append(match.group(0))
        return f"\x01{len(tags) - 1}\x01"

    # Source text can't hold the slot marker, or it could stand in for a tag held here.
    text = _hold_raw_blocks(html.replace("\x01", ""), tags)
    text = _LIQUID_TAG.sub(hold, text)
    spans = list(_not_content_spans(text))
    text = "".join(
        text[start:end]
        for start, end in zip([0, *(span.end for span in spans)], [*(span.start for span in spans), len(text)])
    )
    text = _HTML_LINK.sub(
        lambda match: (
            match.group(1)
            if _HTML_TAG.sub("", match.group(2)).strip() == match.group(1)
            else f"{_HTML_TAG.sub('', match.group(2)).strip()} ({match.group(1)})"
        ),
        text,
    )
    text = _HTML_LINE_BREAK.sub("\n", text)
    text = html_lib.unescape(_HTML_TAG.sub("", text))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    # Decoded entities and removed HTML tags can leave braces that read as Liquid, like `&#123;&#123; x &#125;&#125;`.
    text = _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), text)
    # Plain text has no escaping, so `| raw` and the HTML escaping before it have nothing to do in it. Only an output's
    # last filters go, so a tag kept literally can't turn into another one.
    return _LIQUID_SLOT.sub(lambda match: _without_raw_filter(tags[int(match.group(1))]), text)


def convert_version(
    version: dict[str, object], *, generation: str = "dynamic", contact_fields: bool = False
) -> ConvertedSendGridTemplate:
    """A template version's subject and bodies in Liquid, with notes on anything to review. `contact_fields` says
    SendGrid fills its reserved contact fields, as it does for a Single Send."""
    html_source = _as_text(version.get("html_content"))
    text_source = _as_text(version.get("plain_content"))
    subject_source = _as_text(version.get("subject"))
    generates_text = version.get("generate_plain_content", True) is not False or not text_source

    legacy_tags: list[str] = []
    if generation == "legacy":
        subject, subject_state = _convert_legacy(subject_source, False, legacy_tags)
        html, html_state = _convert_legacy(html_source, True, legacy_tags)
        text, text_state = _convert_legacy(text_source, False, legacy_tags)
    else:
        subject, subject_state = _convert_handlebars(subject_source, False, contact_fields)
        html, html_state = _convert_handlebars(html_source, True, contact_fields)
        text, text_state = _convert_handlebars(text_source, False, contact_fields)
    if generates_text and html:
        text = plain_text_from_html(html)

    states = (subject_state, html_state, text_state)
    notes: list[str] = []
    send_notes: list[str] = []

    if tags := list(dict.fromkeys(tag for state in states for tag in state.unsupported)):
        shown = ", ".join(tags[:_MAX_NOTED_TAGS])
        more = f" and {len(tags) - _MAX_NOTED_TAGS} more" if len(tags) > _MAX_NOTED_TAGS else ""
        notes.append(f"PostHog can't convert {shown}{more}, so it appears as plain text. Rewrite it in Liquid.")
    if compared := list(dict.fromkeys(tag for state in states for tag in state.compared_as_text)):
        shown = ", ".join(compared[:_MAX_NOTED_TAGS])
        notes.append(
            f'{shown} compares values as text, so 3 equals "3" as in SendGrid, but 3.0 doesn\'t equal 3 and a missing '
            "value equals an empty one. Check these if your data has such values."
        )
    if formats := list(dict.fromkeys(item for state in states for item in state.date_notes)):
        notes.append(
            f"formatDate takes {', '.join(formats)} from your data, and PostHog needs the format written in the "
            "template. The date prints in full until you write it in."
        )
    if any(state.web_link for state in states):
        notes.append("PostHog has no view in browser link, so the {{{Weblink}}} tag was removed.")
    if any(state.uses_unsubscribe for state in states):
        notes.append(
            "Unsubscribe links now open PostHog's preferences page, where people choose what to leave, rather than "
            "leaving a SendGrid group in one click."
        )
    if any(state.uses_legacy_slots for state in states):
        send_notes.append("SendGrid fills <%subject%> and <%body%> from the send. Pass subject and body as variables.")
    if legacy_tags:
        shown = ", ".join(list(dict.fromkeys(legacy_tags))[:_MAX_NOTED_TAGS])
        send_notes.append(f"Pass {shown} as variables when you send, without the hyphens.")
    if generation == "legacy" and any(
        _OTHER_SUBSTITUTION_MARKS.search(source) for source in (html_source, text_source, subject_source)
    ):
        notes.append(
            "This template may use tags like %name% or #name#. PostHog only converted -name- tags, so rewrite any "
            "others in Liquid."
        )
    if version.get("editor") == "design":
        notes.append(
            "This was built in SendGrid's design editor. Its HTML came across, and its drag and drop blocks can't."
        )
    if generates_text and html:
        notes.append(
            "SendGrid builds the plain text version when it sends. PostHog built it from the HTML now, so check it, "
            "and update it when you edit the HTML."
        )
    if senders := sorted({name for state in states for name in state.sender_variables}):
        send_notes.append(
            f"SendGrid fills {', '.join(senders)} from the sender. PostHog doesn't, so your app has to pass the value."
        )
    if contacts := sorted({name for state in states for name in state.contact_variables}):
        send_notes.append(
            f"SendGrid fills {', '.join(contacts)} from the contact. PostHog doesn't, so this needs a value when you "
            "send it."
        )
    return ConvertedSendGridTemplate(
        subject=subject, html=html, text=text, notes=tuple(notes), send_notes=tuple(send_notes)
    )


def _as_text(value: object) -> str:
    # NUL and \x01 mark the converter's own placeholders, and an email holds neither, so a source can't fake one.
    return value.replace("\x00", "").replace("\x01", "") if isinstance(value, str) else ""
