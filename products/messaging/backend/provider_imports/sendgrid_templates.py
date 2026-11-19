"""Turns a SendGrid template into PostHog's Liquid, and says what did not carry over.

Dynamic templates use Handlebars with SendGrid's own helpers:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/using-handlebars. Legacy templates use `-name-` tags:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/substitution-tags.

Only plain values and `if` or `each` on a plain value convert, in body text and in quoted attribute values. Any other
Handlebars keeps the whole template as text with a note, because each other form needs rules of its own to print what
SendGrid prints. Liquid treats an empty string, 0 and an empty list as true where Handlebars doesn't, so conditions spell
that out.
"""

import re
import html as html_lib
from collections.abc import Callable, Iterator
from functools import partial

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.sendgrid_handlebars import (
    _Block,
    _Liquid,
    _Malformed,
    _Output,
    _parse_nodes,
    _Text,
    _tokenize,
    _Unconvertible,
    liquid_literal,
)

_MAX_NOTED_TAGS = 5
_MIN_OUTPUT_BUDGET = 1_000_000
_OUTPUT_GROWTH_LIMIT = 20
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

# https://www.twilio.com/docs/sendgrid/ui/sending-email/group-unsubscribes
_ASM_TAG = re.compile(r"(?:<|&lt;)%\s*([\w.]+)\s*%(?:>|&gt;)")
_ASM_URLS = {"asm_group_unsubscribe_raw_url", "asm_global_unsubscribe_raw_url", "asm_preferences_raw_url"}
_ASM_LINKS = {
    "asm_group_unsubscribe_url": "Unsubscribe From This List",
    "asm_global_unsubscribe_url": "Unsubscribe From All Emails",
    "asm_preferences_url": "Manage Email Preferences",
}


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
    is_loop: bool = False


# Conversion -----------------------------------------------------------------------------------------------------------


class _OutputTooLarge(Exception):
    pass


class _Converter:
    def __init__(self, is_html: bool, contact_fields: bool, budget: int = 0) -> None:
        self._budget = budget
        self.is_html = is_html
        self.contact_fields = contact_fields
        self.unsupported: list[str] = []
        self.uses_unsubscribe = False
        self.sender_variables: set[str] = set()
        self.contact_variables: set[str] = set()
        self.web_link = False
        self.uses_legacy_slots = False

    def nodes(self, nodes: tuple[object, ...], frames: tuple[_Frame, ...]) -> str:
        return "".join(self.node(node, frames) for node in nodes)

    def node(self, node: object, frames: tuple[_Frame, ...]) -> str:
        if isinstance(node, _Block):
            return self.block(node, frames)
        converted = self._leaf(node, frames)
        self._budget -= len(converted)
        if self._budget < 0:
            raise _OutputTooLarge
        return converted

    def _leaf(self, node: object, frames: tuple[_Frame, ...]) -> str:
        if isinstance(node, _Text):
            # Handlebars prints `{%` as it stands. Liquid would read it as a tag.
            text = node.text.replace("{%", '{{ "{%" }}')
            # A trimmed space can put this `{` next to a `{` or `%` from the next node.
            return f'{text[:-1]}{{{{ "{{" }}}}' if text.endswith("{") else text
        if isinstance(node, _Liquid):
            return node.liquid
        if isinstance(node, _Output):
            return self.output(node, frames)
        raise TypeError(type(node).__name__)

    def output(self, node: _Output, frames: tuple[_Frame, ...]) -> str:
        name = node.body
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
        value = self._path(name, frames)
        if self.is_html and not node.raw:
            return f"{{{{ {value}{_AS_TEXT}{_HTML_ESCAPE} | raw }}}}"
        return f"{{{{ {value}{_AS_TEXT}{' | raw' if self.is_html else ''} }}}}"

    def _path(self, name: str, frames: tuple[_Frame, ...]) -> str:
        prefix = frames[-1].prefix
        if name == "this":
            return prefix
        return ".".join([prefix, *name.removeprefix("this.").split(".")])

    def block(self, block: _Block, frames: tuple[_Frame, ...]) -> str:
        value = self._path(block.params[0].source, frames)  # type: ignore[attr-defined]
        otherwise = f"{{% else %}}{self.nodes(block.inverse, frames)}" if block.inverse else ""
        if block.name == "if":
            # Handlebars treats an empty string, 0 and an empty list as false, and Liquid doesn't.
            return f"{{% if {value} and {value} != 0 and {value} != empty %}}{self.nodes(block.body, frames)}{otherwise}{{% endif %}}"
        depth = sum(1 for frame in frames if frame.is_loop)
        item = f"item{depth + 1}" if depth else "item"
        body = self.nodes(block.body, (*frames, _Frame(prefix=item, is_loop=True)))
        return f"{{% for {item} in {value} %}}{body}{otherwise}{{% endfor %}}"


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


# Only these forms convert: a plain value, and `if` or `each` on a plain value. Anything else keeps the whole template
# as text, because each other form needs rules of its own to print what SendGrid prints.
_NAME = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
_ALLOWED_TAG = re.compile(
    rf"\{{\{{\{{ *{_NAME} *\}}\}}\}}|\{{\{{ *(?:{_NAME}|#(?:if|each) +{_NAME}|else|/(?:if|each)) *\}}\}}"
)
_BLOCK_TAG = re.compile(r"\{\{ *[#/]|\{\{ *else")
# An attribute value in quotes, other than an event handler or a style, can hold a value.
_PLAIN_ATTRIBUTE = re.compile(r"""\s(?!on|style\b)[\w:-]+\s*=\s*(?:"[^"<>]*"|'[^'<>]*')""", re.IGNORECASE)
_BRACE_BEFORE_ASM = re.compile(r"\{(?:<|&lt;)%")
_BRACE_BEFORE_SUBSTITUTION = re.compile(r"\{-[A-Za-z_]\w*-")
_ANGLE_IN_QUOTED_VALUE = re.compile(r"""=\s*(?:"[^"]*[<>][^"]*"|'[^']*[<>][^']*')""")
_LINK_LABEL = re.compile(r"<a\b[^<>]{0,2000}>((?:(?!<a\b).){0,5000}?)</a\s*>", re.DOTALL | re.IGNORECASE)


def _unsupported_reason(source: str, is_html: bool) -> str | None:
    """Why the template can't convert, or None when every tag is a supported form in a supported place."""
    if _BRACE_BEFORE_ASM.search(source):
        return "put a brace right before an unsubscribe or body tag"
    held: list[str] = []
    position = 0
    # `<%...%>` tags hold `<` and `>`, which would read as HTML below.
    text = _ASM_TAG.sub("\x03", source)
    while (start := text.find("{{", position)) != -1:
        match = _ALLOWED_TAG.match(text, start)
        if match is None:
            return "use Handlebars beyond plain values, if and each"
        held.append(text[position:start] + ("\x02b\x02" if _BLOCK_TAG.match(match.group(0)) else "\x02o\x02"))
        position = match.end()
    text = "".join(held) + text[position:]
    if not is_html:
        return None
    # A `<` or `>` in a quoted value hides where the tag ends from the checks below.
    if _ANGLE_IN_QUOTED_VALUE.search(text):
        return "have a < or > inside a quoted attribute value"
    if any("\x02" in text[span.start : span.end] for span in _not_content_spans(text)):
        return "sit inside a comment, style, script or head block"
    for tag in _HTML_TAG.finditer(text):
        if "\x02" in _PLAIN_ATTRIBUTE.sub("", tag.group(0)) or "\x02b" in tag.group(0):
            return "sit inside an HTML tag other than a plain attribute value"
    if any("\x02b\x02" in label.group(1) for label in _LINK_LABEL.finditer(text)):
        return "put a condition or loop inside a link"
    return None


def _convert_handlebars(source: str | None, is_html: bool, contact_fields: bool) -> tuple[str, _Converter]:
    # The placeholders below are marked with NUL, which an email can't hold, so a source with one can't fake them.
    source = (source or "").replace("\x00", "")
    # Nested loops repeat their output for every item, so output can grow much faster than input.
    converter = _Converter(is_html, contact_fields, budget=max(_MIN_OUTPUT_BUDGET, _OUTPUT_GROWTH_LIMIT * len(source)))
    if not source:
        return "", converter
    reason = _unsupported_reason(source, is_html)
    if reason:
        return _kept_as_text(source, is_html, contact_fields, reason)
    try:
        tree = _parse_nodes(_tokenize(_convert_asm_placeholders(source), is_html))
        converted = _restore_asm(converter.nodes(tree, (_Frame(prefix="variables"),)), is_html, converter)
    except (_Malformed, _Unconvertible):
        return _kept_as_text(source, is_html, contact_fields, "don't form valid Handlebars")
    except _OutputTooLarge:
        return _kept_as_text(source, is_html, contact_fields, "nest too deeply")
    return converted, converter


def _kept_as_text(source: str, is_html: bool, contact_fields: bool, reason: str) -> tuple[str, _Converter]:
    """The whole template as text. Its `<%...%>` tags stay text too, so a guarded body can't print unguarded."""
    converter = _Converter(is_html, contact_fields)
    converter.unsupported.append(f"this template's tags, which {reason}")
    return _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), source), converter


# Set aside while the Handlebars is parsed, because `<%...%>` reads as text to the parser and its result is Liquid.
_ASM_PLACEHOLDER = "\x00asm:{}\x00"
_ASM_PLACEHOLDER_PATTERN = re.compile("\x00asm:(.*?)\x00", re.DOTALL)


def _convert_asm_placeholders(source: str) -> str:
    return _ASM_TAG.sub(lambda match: _ASM_PLACEHOLDER.format(match.group(0)), source)


def _restore_asm(text: str, is_html: bool, converter: _Converter) -> str:
    return _ASM_PLACEHOLDER_PATTERN.sub(lambda match: _convert_asm_tags(match.group(1), is_html, converter), text)


# Tag bodies are capped and stop at the next opening, so text full of unclosed braces scans in linear time.
_ANY_LIQUID_OPENING = re.compile(r"\{\{(?:(?!\{\{).){0,2000}?\}\}|\{%(?:(?!\{%).){0,2000}?%\}|\{\{|\{%", re.DOTALL)


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
    if _BRACE_BEFORE_ASM.search(source) or _BRACE_BEFORE_SUBSTITUTION.search(source):
        # The `{` would join the converted tag into `{{{`, so nothing converts.
        return _kept_as_text(source, is_html, False, "put a brace right before a tag")

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


def _is_control_flow(tag: str) -> bool:
    return tag.startswith("{%") and not _RAW_OPEN.match(tag)


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

    def kept_control_flow(fragment: str) -> str:
        # Removed HTML can hold the `if` around visible content, and dropping only the tag would print what it guards.
        held = (match.group(0) for match in _LIQUID_SLOT.finditer(fragment))
        return "".join(slot for slot in held if _is_control_flow(tags[int(slot.strip("\x01"))]))

    text = "".join(
        text[start:end] + (kept_control_flow(text[spans[index].start : spans[index].end]) if index < len(spans) else "")
        for index, (start, end) in enumerate(
            zip([0, *(span.end for span in spans)], [*(span.start for span in spans), len(text)])
        )
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
    text = html_lib.unescape(_HTML_TAG.sub(lambda match: kept_control_flow(match.group(0)), text))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    # Decoded entities and removed HTML tags can leave braces that read as Liquid, like `&#123;&#123; x &#125;&#125;`.
    text = _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), text)
    # A `{` left beside a held tag would join it into `{{{` or `{{%`.
    text = text.replace("{\x01", '{{ "{" }}\x01')
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
