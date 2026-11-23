"""Turns a SendGrid template into PostHog's Liquid, and says what did not carry over.

Dynamic templates use Handlebars with SendGrid's own helpers:
https://www.twilio.com/docs/sendgrid/for-developers/sending-email/using-handlebars. Legacy templates stay as text.

Each tag converts on its own (see handlebars_liquid.py), and a tag with no Liquid form stays as written with a note.
"""

import re
import html as html_lib
from collections.abc import Iterator

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.handlebars_liquid import (
    HTML_ESCAPE,
    HandlebarsToLiquid,
    OutputTooLarge,
    TextValue,
)
from products.messaging.backend.provider_imports.sendgrid_handlebars import (
    _Malformed,
    _parse_nodes,
    _tokenize,
    liquid_literal,
)

_MAX_NOTED_TAGS = 5

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


class _Found:
    """What a part of the template uses, for the notes."""

    def __init__(self, contact_fields: bool) -> None:
        self.contact_fields = contact_fields
        self.unsupported: list[str] = []
        self.uses_unsubscribe = False
        self.sender_variables: set[str] = set()
        self.contact_variables: set[str] = set()
        self.web_link = False

    def root_value(self, name: str) -> str | None:
        if name in _UNSUBSCRIBE_VARIABLES:
            return "{{ unsubscribe_url }}"
        if name == "Weblink":
            return ""
        if name in _SENDER_VARIABLES:
            self.sender_variables.add(name)
        elif self.contact_fields and name in _CONTACT_VARIABLES:
            self.contact_variables.add(name)
        return None


def _split_asm_tags(text: str, is_html: bool) -> Iterator[str | TextValue]:
    position = 0
    for match in _ASM_TAG.finditer(text):
        yield text[position : match.start()]
        name = match.group(1)
        if name in _ASM_URLS:
            yield TextValue(source=match.group(0), in_attribute=True, liquid="{{ unsubscribe_url }}")
        elif name in _ASM_LINKS:
            link = f'<a href="{{{{ unsubscribe_url }}}}">{_ASM_LINKS[name]}</a>' if is_html else "{{ unsubscribe_url }}"
            yield TextValue(source=match.group(0), in_attribute=False, liquid=link)
        else:
            yield TextValue(source=match.group(0), in_attribute=False)
        position = match.end()
    yield text[position:]


def _convert_handlebars(source: str | None, is_html: bool, contact_fields: bool) -> tuple[str, _Found]:
    source = source or ""
    found = _Found(contact_fields)
    if not source:
        return "", found
    converter = HandlebarsToLiquid(
        is_html=is_html,
        dialect="sendgrid",
        root_value=found.root_value,
        split_text=lambda text: _split_asm_tags(text, is_html),
    )
    try:
        converted = converter.convert(_parse_nodes(_tokenize(source, is_html)))
    except _Malformed:
        return _kept_as_text(source, contact_fields, "don't form valid Handlebars")
    except OutputTooLarge:
        return _kept_as_text(source, contact_fields, "make a template too large to convert")
    found.unsupported = converter.unsupported
    # Only the links that converted open PostHog's preferences page.
    found.uses_unsubscribe = any(
        tag in _UNSUBSCRIBE_VARIABLES or _ASM_TAG.fullmatch(tag) for tag in converter.converted
    )
    found.web_link = "Weblink" in converter.converted
    return converted, found


_LEGACY_REASON = "come from a legacy template"


def _kept_as_text(source: str, contact_fields: bool, reason: str) -> tuple[str, _Found]:
    """The whole template as text. Its `<%...%>` tags stay text too, so a guarded body can't print unguarded."""
    found = _Found(contact_fields)
    found.unsupported.append(f"this template's tags, which {reason}")
    return _ANY_LIQUID_OPENING.sub(lambda match: liquid_literal(match.group(0)), source), found


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
    if head.endswith(HTML_ESCAPE):
        return f"{{{{{head.removesuffix(HTML_ESCAPE)} }}}}"
    # A value the HTML part prints as HTML reads as text once its markup is gone, as SendGrid builds plain text.
    return f"{{{{{head} | strip_html }}}}"


def _control_tags(text: str, span: _Span, tags: list[str]) -> Iterator[str]:
    for slot in _LIQUID_SLOT.finditer(text, span.start, span.end):
        tag = tags[int(slot.group(1))]
        if tag.startswith("{%") and not _RAW_OPEN.match(tag):
            yield slot.group(0)


def _without_html_tags(text: str, tags: list[str]) -> str:
    """Removes HTML tags but keeps the control tags inside them, in order, so a condition that opens inside an
    attribute still has its opening when it closes in the text."""
    return _HTML_TAG.sub(
        lambda match: "".join(_control_tags(text, _Span(start=match.start(), end=match.end()), tags)), text
    )


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
    # A `<%...%>` tag in a template kept as text holds `<` and `>`, which would read as HTML below.
    text = _ASM_TAG.sub(hold, text)
    spans = list(_not_content_spans(text))
    # A condition can open inside a title or head and close after it, so its control tags stay when the block goes.
    # Values and text in the block go with it.
    text = "".join(
        text[start:end] + ("".join(_control_tags(text, span, tags)) if span else "")
        for start, end, span in zip(
            [0, *(span.end for span in spans)], [*(span.start for span in spans), len(text)], [*spans, None]
        )
    )

    def link(match: re.Match[str]) -> str:
        # A condition inside the link can guard its URL. Expanding the link would print the URL outside that condition.
        if any(_control_tags(match.string, _Span(start=match.start(), end=match.end()), tags)):
            return match.group(0)
        label = _without_html_tags(match.group(2), tags).strip()
        return match.group(1) if label == match.group(1) else f"{label} ({match.group(1)})"

    text = _HTML_LINK.sub(link, text)
    text = _HTML_LINE_BREAK.sub("\n", text)
    text = html_lib.unescape(_without_html_tags(text, tags))
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
    # Plain text has no escaping, so `| raw` has nothing to do in it. Only an output's last filter goes, so a tag kept
    # literally can't turn into another one.
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
        subject, subject_state = _kept_as_text(subject_source, False, _LEGACY_REASON)
        html, html_state = _kept_as_text(html_source, False, _LEGACY_REASON)
        text, text_state = _kept_as_text(text_source, False, _LEGACY_REASON)
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
        them = "it" if len(tags) == 1 else "them"
        notes.append(
            f"PostHog can't convert {shown}{more}, so the email shows {them} as written. Rewrite {them} in Liquid."
        )
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
