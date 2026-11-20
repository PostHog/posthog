"""Turns a SendGrid template into PostHog's Liquid, and says what did not carry over.

Dynamic templates use Handlebars with SendGrid's own helpers:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/using-handlebars. Legacy templates stay as text.

Only plain values written with two braces convert, in body text. Any other Handlebars, conditions and loops
included, keeps the whole template as text with a note, because each other form needs rules of its own to print what
SendGrid prints.
"""

import re
import html as html_lib
from collections.abc import Iterator

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.sendgrid_handlebars import (
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

    def nodes(self, nodes: tuple[object, ...]) -> str:
        return "".join(self.node(node) for node in nodes)

    def node(self, node: object) -> str:
        converted = self._leaf(node)
        self._budget -= len(converted)
        if self._budget < 0:
            raise _OutputTooLarge
        return converted

    def _leaf(self, node: object) -> str:
        if isinstance(node, _Text):
            # Handlebars prints `{%` as it stands. Liquid would read it as a tag.
            text = node.text.replace("{%", '{{ "{%" }}')
            # A trimmed space can put this `{` next to a `{` or `%` from the next node.
            return f'{text[:-1]}{{{{ "{{" }}}}' if text.endswith("{") else text
        if isinstance(node, _Liquid):
            return node.liquid
        if isinstance(node, _Output):
            return self.output(node)
        raise TypeError(type(node).__name__)

    def output(self, node: _Output) -> str:
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
        # Handlebars escapes a two-brace value in every part, the subject and plain text included.
        return f"{{{{ variables.{name}{_AS_TEXT}{_HTML_ESCAPE}{' | raw' if self.is_html else ''} }}}}"


# Whole templates ------------------------------------------------------------------------------------------------------


def _convert_asm_tags(text: str, is_html: bool, converter: _Converter) -> str:
    def convert(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _ASM_URLS:
            converter.uses_unsubscribe = True
            return "{{ unsubscribe_url }}"
        converter.uses_unsubscribe = True
        return f'<a href="{{{{ unsubscribe_url }}}}">{_ASM_LINKS[name]}</a>' if is_html else "{{ unsubscribe_url }}"

    return _ASM_TAG.sub(convert, text)


# Only a plain value converts. Anything else keeps the whole template as text, because each other form needs rules of
# its own to print what SendGrid prints: a condition reads an empty object differently, and a loop reads an object's
# values where Liquid reads its pairs.
# Liquid reads `size`, `first` and `last` as properties of any object or array, where Handlebars finds nothing.
_SEGMENT = r"(?!(?:this|size|first|last)\b)[A-Za-z_][A-Za-z0-9_]*"
_ALLOWED_TAG = re.compile(rf"\{{\{{ *{_SEGMENT}(?:\.{_SEGMENT})* *\}}\}}(?!\}})")
_HELD = re.compile("[\x02\x03]")
_BRACE_BEFORE_ASM = re.compile(r"\{(?:<|&lt;)%")
_ANGLE_IN_QUOTED_VALUE = re.compile(r"""=\s*(?:"[^"<>]*[<>][^"]*"|'[^'<>]*[<>][^']*')""")


def _unsupported_reason(source: str, is_html: bool) -> str | None:
    """Why the template can't convert, or None when every tag is a supported form in a supported place."""
    if _BRACE_BEFORE_ASM.search(source):
        return "put a brace right before an unsubscribe tag"
    held: list[str] = []
    position = 0
    if any(match.group(1) not in _ASM_URLS and match.group(1) not in _ASM_LINKS for match in _ASM_TAG.finditer(source)):
        return "use <%...%> tags other than unsubscribe links"
    # `<%...%>` tags hold `<` and `>`, which would read as HTML below. An unsubscribe URL is PostHog's own, so it may
    # also sit in a tag, and an unsubscribe link may only sit in body text.
    text = _ASM_TAG.sub(lambda match: "\x04" if match.group(1) in _ASM_URLS else "\x03", source)
    while (start := text.find("{{", position)) != -1:
        match = _ALLOWED_TAG.match(text, start)
        if match is None:
            return "use Handlebars beyond plain values"
        held.append(text[position:start] + "\x02")
        position = match.end()
    text = "".join(held) + text[position:]
    if not is_html:
        return None
    # A `<` or `>` in a quoted value hides where the tag ends from the checks below.
    if _ANGLE_IN_QUOTED_VALUE.search(text):
        return "have a < or > inside a quoted attribute value"
    if _has_unclosed_block(text):
        return "have a comment, style, script or head block that never closes"
    if any(_HELD.search(text[span.start : span.end]) for span in _not_content_spans(text)):
        return "sit inside a comment, style, script or head block"
    if any(_HELD.search(tag.group(0)) for tag in _HTML_TAG.finditer(text)):
        return "sit inside an HTML tag"
    return None


def _convert_handlebars(source: str | None, is_html: bool, contact_fields: bool) -> tuple[str, _Converter]:
    # The placeholders below are marked with NUL, which an email can't hold, so a source with one can't fake them.
    source = (source or "").replace("\x00", "")
    # Each value prints with its escaping filters, so output can grow faster than input.
    converter = _Converter(is_html, contact_fields, budget=max(_MIN_OUTPUT_BUDGET, _OUTPUT_GROWTH_LIMIT * len(source)))
    if not source:
        return "", converter
    reason = _unsupported_reason(source, is_html)
    if reason:
        return _kept_as_text(source, is_html, contact_fields, reason)
    try:
        tree = _parse_nodes(_tokenize(_convert_asm_placeholders(source), is_html))
        converted = _restore_asm(converter.nodes(tree), is_html, converter)
    except (_Malformed, _Unconvertible):
        return _kept_as_text(source, is_html, contact_fields, "don't form valid Handlebars")
    except _OutputTooLarge:
        return _kept_as_text(source, is_html, contact_fields, "nest too deeply")
    return converted, converter


_LEGACY_REASON = "come from a legacy template"


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


def _has_unclosed_block(html: str) -> bool:
    """Whether a comment, style, script or head block opens and never closes. Every span starts at an opening, so an
    opening outside all spans is one that never closed."""
    position = 0
    for span in _not_content_spans(html):
        if _NOT_CONTENT_OPENING.search(html, position, span.start):
            return True
        position = span.end
    return _NOT_CONTENT_OPENING.search(html, position) is not None


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
_LIQUID_SLOT_SPLIT = re.compile("(\x01\\d+\x01)")
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
    # Only between held tags: a span across one would put that tag's raw block inside a new one, which ends early.
    text = "".join(
        part
        if _LIQUID_SLOT.fullmatch(part)
        else _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), part)
        for part in _LIQUID_SLOT_SPLIT.split(text)
    )
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

    if generation == "legacy":
        subject, subject_state = _kept_as_text(subject_source, False, False, _LEGACY_REASON)
        html, html_state = _kept_as_text(html_source, True, False, _LEGACY_REASON)
        text, text_state = _kept_as_text(text_source, False, False, _LEGACY_REASON)
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
