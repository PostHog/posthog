"""Turns a Mailgun template version into PostHog's Liquid, and says what did not carry over.

Mailgun renders versions with Handlebars or Go templates, then replaces `%recipient.x%` style variables. Handlebars
converts one tag at a time (see handlebars_liquid.py). Go converts only plain values, `{{.Name}}` in page text, and a
Go template with anything else stays as plain text with a note, so a person rewrites it. See
https://documentation.mailgun.com/docs/mailgun/user-manual/sending-messages/send-templates.
"""

import re
import html
from collections.abc import Iterator, Mapping
from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.handlebars_liquid import HandlebarsToLiquid, OutputTooLarge, TextValue
from products.messaging.backend.provider_imports.html_context import HtmlContext
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
        return ConvertedText(text=_as_text(text, is_html), has_tags=True, too_large=True)
    if engine == "go":
        return _GoConverter(text, is_html).convert()
    return _convert_handlebars(text, is_html)


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

    if unsupported := list(dict.fromkeys(tag for part in parts for tag in part.unsupported)):
        shown = ", ".join(unsupported[:_MAX_NOTED_TAGS])
        more = f" and {len(unsupported) - _MAX_NOTED_TAGS} more" if len(unsupported) > _MAX_NOTED_TAGS else ""
        if engine == "go":
            notes.append(
                f"PostHog only converts plain values, such as {{{{.Name}}}}, and this template uses {shown}{more}. It "
                "appears as plain text, so rewrite it in Liquid."
            )
        else:
            them = "it" if len(unsupported) == 1 else "them"
            notes.append(
                f"PostHog can't convert {shown}{more}, so the email shows {them} as written. Rewrite {them} in Liquid."
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


def _header(headers: Mapping[str, Any], name: str) -> Any:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


@frozen
class _Value:
    start: int
    end: int
    source: str
    liquid: str


class _Unsupported(Exception):
    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source = source


class _GoConverter:
    """Converts a Go template, which only converts as a whole."""

    def __init__(self, text: str, is_html: bool) -> None:
        self.text = text
        self.is_html = is_html
        self.recipient_variables: list[str] = []
        self.tag_unsubscribe = False
        self.list_unsubscribe = False
        self.unsubscribe_email = False
        self.go_kinds: dict[str, str] = {}

    def convert(self) -> ConvertedText:
        try:
            values = self._values()
            if self.is_html:
                self._check_contexts(values)
        except _Unsupported as e:
            return ConvertedText(text=_as_text(self.text, self.is_html), unsupported=(e.source,), has_tags=True)
        out: list[str] = []
        cursor = 0
        for value in values:
            _append(out, _literal(self.text[cursor : value.start]))
            _append(out, value.liquid)
            cursor = value.end
        _append(out, _literal(self.text[cursor:]))
        setup = "".join(f"{{% assign {kind} = {path} | json | slice: 0 %}}" for path, kind in self.go_kinds.items())
        converted = setup + "".join(out)
        # Liquid counts length in UTF-16 units, so a character outside the basic plane counts twice.
        if len(converted.encode("utf-16-le")) // 2 > _MAX_OUTPUT_CHARS:
            return ConvertedText(text=_as_text(self.text, self.is_html), has_tags=True, too_large=True)
        return ConvertedText(
            text=converted,
            recipient_variables=tuple(dict.fromkeys(self.recipient_variables)),
            has_tags=any(value.source.startswith("{{") for value in values),
            tag_unsubscribe=self.tag_unsubscribe,
            list_unsubscribe=self.list_unsubscribe,
            unsubscribe_email=self.unsubscribe_email,
        )

    def _values(self) -> list[_Value]:
        """Every value in the text, in order. Raises _Unsupported for anything in braces that isn't a plain value."""
        values: list[_Value] = []
        position = 0
        while (opening := self.text.find("{{", position)) >= 0:
            tag = _TAG.match(self.text, opening)
            go = _GO_VALUE.fullmatch(tag.group(0)) if tag else None
            if tag is None or go is None or _LIQUID_PROPERTIES.intersection(go[1].split(".")):
                shown = tag.group(0) if tag else self.text[opening : opening + 60].split("\n", 1)[0]
                raise _Unsupported(shown)
            values.append(
                _Value(start=opening, end=tag.end(), source=tag.group(0), liquid=self._value(f"variables.{go[1]}"))
            )
            position = tag.end()
        for match in _FIXED_VARIABLE.finditer(self.text):
            values.append(
                _Value(start=match.start(), end=match.end(), source=match.group(0), liquid=self._fixed_variable(match))
            )
        for match in _RECIPIENT_VARIABLE.finditer(self.text):
            if match[1] in _LIQUID_PROPERTIES:
                raise _Unsupported(match.group(0))
            self.recipient_variables.append(match.group(0))
            values.append(
                _Value(
                    start=match.start(),
                    end=match.end(),
                    source=match.group(0),
                    liquid=self._value(f"variables.{match[1]}"),
                )
            )
        values.sort(key=lambda value: value.start)
        if any(previous.end > value.start for previous, value in zip(values, values[1:])):
            raise _Unsupported("a Mailgun variable inside braces")
        return values

    def _fixed_variable(self, match: re.Match[str]) -> str:
        name = match[1]
        if name == "tag_unsubscribe_url":
            self.tag_unsubscribe = True
        elif name == "mailing_list_unsubscribe_url":
            self.list_unsubscribe = True
        elif name == "unsubscribe_email":
            self.unsubscribe_email = True
            return _literal(match.group(0))
        if name in _UNSUBSCRIBE_URLS:
            return "{{ unsubscribe_url }}"
        self.recipient_variables.append(match.group(0))
        return self._value(f"variables.{name}")

    def _value(self, path: str) -> str:
        show = _escaped if self.is_html else (lambda shown: f"{{{{ {shown} }}}}")
        # Go prints a list as [a b] and a map as map[key:value], so the value's JSON says which it is. Each value's
        # answer is worked out once, at the top of the template, so every use can read it.
        kind = self.go_kinds.setdefault(path, f"go_value{len(self.go_kinds) + 1}")
        return (
            f'{{% if {kind} == "[" %}}[{show(f"{path} | join: ' '")}]'
            f'{{% elsif {kind} == "{{" %}}map[{{% for pair in {path} %}}{{% unless forloop.first %}} {{% endunless %}}'
            f"{show('pair[0]')}:{show('pair[1]')}{{% endfor %}}]"
            f"{{% else %}}{show(path)}{{% endif %}}"
        )

    def _check_contexts(self, values: list[_Value]) -> None:
        """Raises _Unsupported for a value anywhere but page text. Go escapes an attribute value by what the attribute
        holds, such as a link, and Liquid can't."""
        context = HtmlContext()
        cursor = 0
        for value in values:
            context.feed(self.text[cursor : value.start])
            if context.untrusted:
                raise _Unsupported(f"{value.source} after a script")
            if (where := context.where()) != "text":
                raise _Unsupported(f"{value.source} {_PLACES.get(where, 'inside an HTML tag')}")
            context.feed("x")
            cursor = value.end


def _as_text(text: str, is_html: bool) -> str:
    """The source as text, so its markup can't render, as nothing would where Mailgun's blocks were false."""
    # Escaping makes a character at most five long, so this much of the source always fits what Liquid parses, and a
    # huge template is cut before it's copied.
    source = text[: _MAX_OUTPUT_CHARS // 5]
    return _literal(html.escape(source, quote=False) if is_html else source)


_PLACES = {
    "value": "in an attribute PostHog can't escape the way Mailgun does",
    "raw": "inside a script, style or similar element",
    "comment": "inside an HTML comment",
}


def _escaped(path: str) -> str:
    # Handlebars also escapes = and `, so a value can't end an unquoted attribute and start another one.
    return f'{{{{ {path} | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}}}'


def _append(out: list[str], chunk: str) -> None:
    """Adds a chunk, so a `{` that ends one chunk and a `{` or `%` that starts the next never join into a Liquid tag."""
    if not chunk:
        return
    if out and out[-1].endswith("{") and chunk[0] in "{%":
        out[-1] = out[-1][:-1] + '{{ "{" }}'
    out.append(chunk)


def _literal(text: str) -> str:
    # Only the openings are Liquid. The renderer decodes entities inside every tag before parsing, so text kept
    # outside tags is the only text that stays exactly as written.
    return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', text)
