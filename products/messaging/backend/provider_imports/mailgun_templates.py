"""Turns a Mailgun template version into PostHog's Liquid, and says what did not carry over.

Mailgun renders versions with Handlebars or Go templates, then replaces `%recipient.x%` style variables. Both convert
one tag at a time (see handlebars_liquid.py and mailgun_go.py). A Go template with a part that doesn't convert stays as
plain text with a note, so a person rewrites it. See
https://documentation.mailgun.com/docs/mailgun/user-manual/sending-messages/send-templates.
"""

import re
import html
import dataclasses
from collections.abc import Iterator, Mapping
from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.handlebars_liquid import HandlebarsToLiquid, OutputTooLarge, TextValue
from products.messaging.backend.provider_imports.mailgun_go import GoToLiquid, GoUnsupported
from products.messaging.backend.provider_imports.sendgrid_handlebars import _Malformed, _parse_nodes, _tokenize

_MAX_NOTED_TAGS = 5
# Liquid can't parse a longer template.
_MAX_OUTPUT_CHARS = 5_000_000
_OPENING = re.compile(r"\{[{%]")
# Each converted value is about a hundred characters, so more than this can't fit what Liquid parses anyway.
_MAX_VALUES = 40_000
_TAG = re.compile(r"\{\{(?:(?!\{\{).){0,200}?\}\}\}?", re.DOTALL)
_GO_VALUE = re.compile(r"\{\{\s*\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\}\}")
_RECIPIENT_VARIABLE = re.compile(r"%recipient\.([A-Za-z_][\w-]{0,127})%")
_FIXED_VARIABLE = re.compile(
    r"%(recipient|recipient_email|recipient_name|recipient_fname|recipient_lname"
    r"|unsubscribe_url|tag_unsubscribe_url|mailing_list_unsubscribe_url|unsubscribe_email)%"
)
# Liquid reads these as properties of any list or object, such as how many variables the send has, where Mailgun
# finds nothing.
_LIQUID_PROPERTIES = frozenset({"size", "first", "last"})
_UNSUBSCRIBE_URLS = frozenset({"unsubscribe_url", "tag_unsubscribe_url", "mailing_list_unsubscribe_url"})
_MAILGUN_VARIABLE = re.compile(f"{_FIXED_VARIABLE.pattern}|{_RECIPIENT_VARIABLE.pattern}")
_FIXED_UNSUBSCRIBE = re.compile(r"%(?:unsubscribe_url|tag_unsubscribe_url|mailing_list_unsubscribe_url)%")
# Looks like a Mailgun variable, but Mailgun fills nothing for it. Two hex digits are an encoded character in a link,
# and a percent right after a number, as in 50%off%, is text.
_PERCENT_TAG = re.compile(r"(?<![\w%])%(?![0-9A-Fa-f]{2}%)[A-Za-z_][\w.-]{0,127}%")
_LINK = re.compile(
    r"<a\b[^>]{0,2000}?\bhref\s*=\s*(?:\"([^\"]{0,2000})\"|'([^']{0,2000})'|([^\s>]{1,2000}))[^>]{0,2000}>(.{0,500}?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_BROWSER_LINK_TEXT = re.compile(
    r"\b(?:view|read|see|open)\b[^<>]{0,40}\b(?:browser|online|web)|\bweb\s?(?:version|page)\b", re.IGNORECASE
)
_BROWSER_LINK_NAME = re.compile(r"view.?in.?browser|view.?online|web.?version|browser.?(?:link|url)", re.IGNORECASE)
_MARKUP = re.compile(r"<[^>]{0,2000}>")
# Syntax Handlebars can't parse, for a version whose engine field is blank.
_GO_ONLY = re.compile(r"\{\{-?\s*(?:\.[A-Za-z_]|end\b|range\b|\$)")

Engine = Literal["handlebars", "go"]


@frozen
class ConvertedText:
    text: str
    # Variables Mailgun fills from recipient-variables or the list member, so the app must pass them.
    recipient_variables: tuple[str, ...] = ()
    # What kept the text from converting, as written in the source.
    unsupported: tuple[str, ...] = ()
    unknown_variables: tuple[str, ...] = ()
    has_tags: bool = False
    tag_unsubscribe: bool = False
    list_unsubscribe: bool = False
    unsubscribe_email: bool = False
    too_large: bool = False
    malformed: bool = False


@frozen
class ConvertedVersion:
    subject: str
    html: str
    notes: tuple[str, ...] = ()
    # About values the app passes when it sends.
    send_notes: tuple[str, ...] = field(default_factory=tuple)
    has_content: bool = True


def detect_engine(version: Mapping[str, Any]) -> Engine:
    engine = str(version.get("engine") or "").strip().lower()
    if engine == "go":
        return "go"
    if engine:
        return "handlebars"
    return "go" if _GO_ONLY.search(str(version.get("template") or "")) else "handlebars"


def convert_text(text: str | None, *, engine: Engine = "handlebars", is_html: bool = True) -> ConvertedText:
    if not text:
        return ConvertedText(text="")
    text = text.replace("\x00", "")
    if _too_many_values(text):
        converted = ConvertedText(text=_as_text(text, is_html), has_tags=True, too_large=True)
    elif engine == "go":
        converted = _convert_go(text, is_html)
    else:
        converted = _convert_handlebars(text, is_html)
    return dataclasses.replace(converted, unknown_variables=_unknown_variables(text))


def _unknown_variables(text: str) -> tuple[str, ...]:
    found = (match.group(0) for match in _PERCENT_TAG.finditer(text))
    return tuple(dict.fromkeys(tag for tag in found if not _MAILGUN_VARIABLE.fullmatch(tag)))


def browser_links(html_body: str) -> tuple[str, ...]:
    """The addresses of "view in browser" links, as written in the source."""
    found: list[str] = []
    for match in _LINK.finditer(html_body):
        address = next((group for group in match.groups()[:3] if group is not None), "")
        if _BROWSER_LINK_NAME.search(address) or _BROWSER_LINK_TEXT.search(_MARKUP.sub(" ", match[4])):
            found.append(address.strip() or match.group(0)[:100])
    return tuple(dict.fromkeys(found))


def _too_many_values(text: str) -> bool:
    return text.count("{{") + text.count("%") // 2 > _MAX_VALUES


def _split_mailgun_variables(text: str) -> Iterator[str | TextValue]:
    """The `%recipient.x%` style variables Mailgun replaces after Handlebars runs."""
    position = 0
    for match in _MAILGUN_VARIABLE.finditer(text):
        name = match[1]
        yield text[position : match.start()]
        position = match.end()
        if name == "unsubscribe_email":
            yield match.group(0)
        elif name in _UNSUBSCRIBE_URLS:
            yield TextValue(source=match.group(0), in_attribute=True, liquid="{{ unsubscribe_url }}")
        elif match[2] in _LIQUID_PROPERTIES:
            yield TextValue(source=match.group(0), in_attribute=True)
        else:
            yield TextValue(source=match.group(0), in_attribute=True, value_path=f"variables.{name or match[2]}")
    yield text[position:]


def _convert_handlebars(text: str, is_html: bool) -> ConvertedText:
    converter = HandlebarsToLiquid(is_html=is_html, dialect="mailgun", split_text=_split_mailgun_variables)
    try:
        converted = converter.convert(_parse_nodes(_tokenize(text, is_html)))
    except _Malformed:
        return ConvertedText(text=_as_text(text, is_html), has_tags=True, malformed=True)
    except OutputTooLarge:
        return ConvertedText(text=_as_text(text, is_html), has_tags=True, too_large=True)
    return _converted(converter, converted, text)


def _converted(converter: HandlebarsToLiquid, converted: str, text: str) -> ConvertedText:
    # Only the variables that converted need a value from the app or point at PostHog's preferences page.
    done = converter.converted
    return ConvertedText(
        text=converted,
        recipient_variables=tuple(dict.fromkeys(tag for tag in done if not _FIXED_UNSUBSCRIBE.fullmatch(tag))),
        unsupported=tuple(converter.unsupported),
        has_tags="{{" in text,
        tag_unsubscribe="%tag_unsubscribe_url%" in done,
        list_unsubscribe="%mailing_list_unsubscribe_url%" in done,
        unsubscribe_email="%unsubscribe_email%" in text,
    )


def _convert_go(text: str, is_html: bool) -> ConvertedText:
    converter = GoToLiquid(is_html=is_html, split_text=_split_mailgun_variables)
    try:
        converted = converter.convert_go(text)
    except GoUnsupported as e:
        return ConvertedText(text=_as_text(text, is_html), unsupported=(e.source,), has_tags=True)
    except OutputTooLarge:
        return ConvertedText(text=_as_text(text, is_html), has_tags=True, too_large=True)
    if converter.unsupported:
        # A Go template only converts as a whole, because Mailgun refuses all of one it can't read.
        return ConvertedText(text=_as_text(text, is_html), unsupported=tuple(converter.unsupported), has_tags=True)
    return _converted(converter, converted, text)


def convert_version(version: Mapping[str, Any]) -> ConvertedVersion:
    """A version's subject and body in Liquid, with notes on anything to review."""
    engine = detect_engine(version)
    raw_headers = version.get("headers")
    headers: Mapping[str, Any] = raw_headers if isinstance(raw_headers, dict) else {}
    subject_source = str(_header(headers, "Subject") or "")
    subject = convert_text(subject_source, engine=engine, is_html=False)
    body_source = version.get("template")
    body = convert_text(body_source if isinstance(body_source, str) else "", engine=engine)
    parts = (subject, body)
    notes: list[str] = []
    send_notes: list[str] = []
    named_engine = str(version.get("engine") or "").strip().lower()

    unsupported = list(dict.fromkeys(tag for part in parts for tag in part.unsupported))
    unknown = [
        tag for tag in dict.fromkeys(tag for part in parts for tag in part.unknown_variables) if tag not in unsupported
    ]
    if engine != "go":
        unsupported, unknown = unsupported + unknown, []
    if unsupported and engine == "go":
        notes.append(
            f"PostHog can't convert {_shown(unsupported)}, so the email shows this whole template as plain text. "
            "Rewrite it in Liquid."
        )
    elif unsupported:
        notes.append(_as_written_note(unsupported))
    if unknown:
        notes.append(_as_written_note(unknown))
    if links := browser_links(body_source if isinstance(body_source, str) else ""):
        notes.append(
            f"PostHog has no view in browser link, so {_shown(links)} still points where it did in Mailgun. Remove it "
            "or point it at a page you host."
        )
    if any(part.malformed for part in parts):
        notes.append("This template isn't valid Handlebars, so it appears as plain text. Rewrite it in Liquid.")
    if any(part.too_large for part in parts):
        notes.append("This template is too large to convert, so it appears as plain text. Rewrite it in Liquid.")
    if engine == "go":
        notes.append(
            "Mailgun renders this version with Go templates. Send a test and check any value that holds HTML. Values "
            "that are maps may print their keys in a different order."
        )
    elif named_engine not in ("", "handlebars"):
        notes.append(f"Mailgun lists the engine {named_engine}. PostHog read it as Handlebars, so send a test.")
    if not subject_source:
        notes.append("This template has no subject in Mailgun, so your app set it on each send. Add one here.")
    elif subject.has_tags:
        notes.append("The subject uses variables, so send a test to check how it reads.")
    if version.get("mjml") and isinstance(body_source, str) and body_source:
        notes.append("PostHog imported the HTML of this template. Its MJML source stays in Mailgun.")
    if any(part.tag_unsubscribe for part in parts):
        notes.append(
            "%tag_unsubscribe_url% now opens the PostHog preferences page. To let people leave one type of email, "
            "put this template in a message category."
        )
    if any(part.list_unsubscribe for part in parts):
        notes.append(
            "%mailing_list_unsubscribe_url% now opens the PostHog preferences page. Put this template in the message "
            "category imported from the list."
        )
    if any(part.unsubscribe_email for part in parts):
        notes.append("PostHog has no %unsubscribe_email% address, so it stays as text. Remove it.")
    if recipient := list(dict.fromkeys(name for part in parts for name in part.recipient_variables)):
        send_notes.append(
            f"Mailgun fills {', '.join(recipient[:_MAX_NOTED_TAGS])} for each recipient. PostHog doesn't, so your app "
            "has to pass them as variables."
        )
    return ConvertedVersion(
        subject=subject.text,
        html=body.text,
        notes=tuple(notes),
        send_notes=tuple(send_notes),
        has_content=bool(body.text),
    )


def _shown(items: list[str] | tuple[str, ...]) -> str:
    shown = ", ".join(items[:_MAX_NOTED_TAGS])
    return f"{shown} and {len(items) - _MAX_NOTED_TAGS} more" if len(items) > _MAX_NOTED_TAGS else shown


def _as_written_note(tags: list[str]) -> str:
    them = "it" if len(tags) == 1 else "them"
    return f"PostHog can't convert {_shown(tags)}, so the email shows {them} as written. Rewrite {them} in Liquid."


def _header(headers: Mapping[str, Any], name: str) -> Any:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _as_text(text: str, is_html: bool) -> str:
    """The source as text, so its markup can't render, as nothing would where Mailgun's blocks were false."""
    # Escaping makes a character at most five long, so this much of the source always fits what Liquid parses, and a
    # huge template is cut before it's copied.
    source = text[: _MAX_OUTPUT_CHARS // 5]
    return _literal(html.escape(source, quote=False) if is_html else source)


def _literal(text: str) -> str:
    # Only the openings are Liquid. The renderer decodes entities inside every tag before parsing, so text kept
    # outside tags is the only text that stays exactly as written.
    return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', text)
