"""Turns Mailchimp merge tags into PostHog's Liquid, and says what did not carry over.

Mailchimp writes a merge tag as `*|NAME|*` and fills it from the audience member, escaped for HTML unless it's written
`*|HTML:NAME|*`. Conditions use `*|IF:NAME|*`, `*|IFNOT:NAME|*`, `*|ELSEIF:NAME|*`, `*|ELSE:|*` and `*|END:IF|*`, with
an optional `=` or `!=` comparison. See https://mailchimp.com/help/all-the-merge-tags-cheat-sheet/.

Each tag converts on its own. A tag PostHog can't convert stays exactly as written and is named in a note, so a person
decides what it becomes. Conditions convert only when every condition in the text converts and they nest correctly,
because a half-converted condition would change which parts a recipient sees.
"""

import re
import html
from collections.abc import Mapping
from dataclasses import field

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.html_context import HtmlContext, Place

_MAX_NOTED_TAGS = 5
# Liquid can't parse a longer template.
_MAX_OUTPUT_CHARS = 5_000_000
_MERGE_TAG = re.compile(r"\*\|([^|\n]{1,200}?)\|\*")
_OPENING = re.compile(r"\{[{%]")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,49}")
# An HTML entity inside a tag means the editor encoded what the sender typed, so the value PostHog would compare
# against isn't the one Mailchimp compares against.
_ENTITY = re.compile(r"&(?:[A-Za-z]+|#\d+|#[xX][0-9a-fA-F]+);")
_NUMBER = re.compile(r"\s*-?\d+(?:\.\d+)?\s*")
_CONDITION = re.compile(r"([A-Za-z][A-Za-z0-9_]{0,49})(?:\s*(!=|=)\s*([^\"'{}%\\&<>]*))?")
_CONDITION_KEYWORDS = ("IF", "IFNOT", "ELSEIF", "ELSE", "END")
# Tags Mailchimp fills itself, which look like merge fields but aren't values from the audience member.
_MAILCHIMP_ONLY = frozenset(
    {
        "ARCHIVE",
        "ARCHIVE_PAGE",
        "FORWARD",
        "REWARDS",
        "REWARDS_TEXT",
        "EMAIL_TYPE",
        "MC_LANGUAGE",
        "MC_LANGUAGE_LABEL",
        "CAMPAIGN_UID",
        "ABOUT_LIST",
        "LIST_ADDRESS",
        "LIST_ADDRESS_HTML",
        "UNSUB_LINK",
        "MC_PREVIEW_TEXT",
    }
)
_UNSUBSCRIBE = frozenset({"UNSUB"})
_PREFERENCES = frozenset({"UPDATE_PROFILE"})
# PHP date letters Mailchimp's DATE tag takes, and the strftime code Liquid's date filter reads for each.
_DATE_CODES = {
    "d": "%d",
    "m": "%m",
    "Y": "%Y",
    "y": "%y",
    "M": "%b",
    "F": "%B",
    "D": "%a",
    "l": "%A",
    "H": "%H",
    "i": "%M",
    "s": "%S",
}
_DATE_SEPARATORS = frozenset(" /-.,:")


@frozen
class ConvertedText:
    text: str
    # Audience fields the text reads, as Mailchimp names them.
    merge_fields: tuple[str, ...] = ()
    # Tags left as written, as they appear in the source.
    unsupported: tuple[str, ...] = ()
    has_values: bool = False
    has_conditions: bool = False
    preferences_link: bool = False
    too_large: bool = False


@frozen
class ConvertedEmail:
    subject: str
    html: str
    text: str
    notes: tuple[str, ...] = ()
    send_notes: tuple[str, ...] = field(default_factory=tuple)


@frozen
class _Replacement:
    start: int
    end: int
    source: str
    liquid: str
    # Output that holds a value from the person, so the HTML around it decides whether it's safe.
    value: bool = False
    raw: bool = False
    # The Liquid tag of a condition: if, elsif, else or endif.
    branch: str = ""


def convert_text(text: str | None, *, is_html: bool, fixed: Mapping[str, str | None] | None = None) -> ConvertedText:
    """Rewrites the merge tags in `text` as Liquid. `fixed` holds tags with one value for every recipient, such as
    `LIST:COMPANY`, by tag name, which go in as plain text. None marks a value that isn't empty but can't go in as
    text, so a condition on it is true and the tag itself stays as written."""
    if not text:
        return ConvertedText(text="")
    return _Converter(text.replace("\x00", ""), is_html, fixed or {}).convert()


def convert_email(
    subject: str | None,
    html_body: str | None,
    text_body: str | None,
    fixed: Mapping[str, str | None] | None = None,
    *,
    expects_subject: bool = True,
) -> ConvertedEmail:
    parts = (
        convert_text(subject, is_html=False, fixed=fixed),
        convert_text(html_body, is_html=True, fixed=fixed),
        convert_text(text_body, is_html=False, fixed=fixed),
    )
    notes: list[str] = []
    send_notes: list[str] = []
    if unsupported := list(dict.fromkeys(tag for part in parts for tag in part.unsupported)):
        notes.append(
            f"PostHog can't convert {_shown(unsupported)}, so it stays as written. Replace it with Liquid or remove it."
            if len(unsupported) == 1
            else f"PostHog can't convert {_shown(unsupported)}, so they stay as written. Replace them with Liquid or "
            "remove them."
        )
    if any(part.too_large for part in parts):
        notes.append("This email is too large to convert, so its merge tags stay as written.")
    if any(part.has_conditions for part in parts):
        notes.append("PostHog converted the IF conditions to Liquid. Send yourself a test to check each one.")
    if any(part.preferences_link for part in parts):
        notes.append("*|UPDATE_PROFILE|* now opens the PostHog preferences page.")
    if expects_subject and not subject:
        notes.append("This email has no subject in Mailchimp. Add one here.")
    fields = [name for name in dict.fromkeys(name for part in parts for name in part.merge_fields) if name != "EMAIL"]
    if fields:
        properties = [
            name if name not in _PERSON_PROPERTIES else f"{_PERSON_PROPERTIES[name]} ({name} in Mailchimp)"
            for name in fields
        ]
        send_notes.append(f"Set these person properties on your people or change the template: {_shown(properties)}.")
    return ConvertedEmail(
        subject=parts[0].text,
        html=parts[1].text,
        text=parts[2].text,
        notes=tuple(notes),
        send_notes=tuple(send_notes),
    )


def _shown(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_NOTED_TAGS])
    return f"{shown} and {len(items) - _MAX_NOTED_TAGS} more" if len(items) > _MAX_NOTED_TAGS else shown


# Mailchimp's default audience fields, read from the person properties the other importers fill.
_PERSON_PROPERTIES = {"EMAIL": "email", "FNAME": "first_name", "LNAME": "last_name"}


def _field_name(name: str) -> str:
    return name.upper() if name.upper() in _PERSON_PROPERTIES else name


def property_name(name: str) -> str:
    return _PERSON_PROPERTIES.get(name.upper(), name)


def person_path(name: str) -> str:
    return f"person.properties.{property_name(name)}"


class _Converter:
    def __init__(self, text: str, is_html: bool, fixed: Mapping[str, str | None]) -> None:
        self.text = text
        self.is_html = is_html
        self.fixed = {name.upper(): value for name, value in fixed.items()}
        self.merge_fields: list[str] = []
        self.unsupported: list[str] = []
        self.preferences_link = False
        # Only a condition on a person property needs a test send. One on a fixed tag was decided at import.
        self.person_conditions = False

    def convert(self) -> ConvertedText:
        if _length(self.text) > _MAX_OUTPUT_CHARS // 2:
            return self._too_large()
        matches = list(_MERGE_TAG.finditer(self.text))
        conditions = self._conditions(matches)
        replacements: list[_Replacement] = []
        for match in matches:
            if match.start() in conditions:
                liquid = conditions[match.start()]
                replacements.append(_swap(match, liquid, branch=liquid.split()[1]))
                continue
            replacement = self._tag(match)
            if replacement is None:
                self.unsupported.append(match.group(0))
            else:
                replacements.append(replacement)
        if self.is_html:
            replacements = self._in_safe_places(replacements)
        out: list[str] = []
        cursor = 0
        for replacement in replacements:
            _append(out, _literal(self.text[cursor : replacement.start]))
            _append(out, replacement.liquid)
            cursor = replacement.end
        _append(out, _literal(self.text[cursor:]))
        converted = "".join(out)
        if _length(converted) > _MAX_OUTPUT_CHARS:
            return self._too_large()
        return ConvertedText(
            text=converted,
            merge_fields=tuple(dict.fromkeys(self.merge_fields)),
            unsupported=tuple(dict.fromkeys(self.unsupported)),
            has_values=any(replacement.value for replacement in replacements),
            has_conditions=bool(conditions) and self.person_conditions,
            preferences_link=self.preferences_link,
        )

    def _too_large(self) -> ConvertedText:
        tags = list(dict.fromkeys(match.group(0) for match in _MERGE_TAG.finditer(self.text)))
        # Quoting a Liquid opening makes it at most five times longer, so this much of the source fits what sends render.
        text = _literal(self.text[: _MAX_OUTPUT_CHARS // 5])
        return ConvertedText(text=text, unsupported=tuple(tags[:_MAX_NOTED_TAGS]), too_large=True)

    def _tag(self, match: re.Match[str]) -> _Replacement | None:
        body = match.group(1).strip()
        upper = body.upper()
        if _ENTITY.search(body):
            return None
        keyword = upper.split(":", 1)[0]
        if ":" in upper and keyword in _CONDITION_KEYWORDS:
            return None
        if (value := self.fixed.get(upper)) is not None:
            return _swap(match, _literal(html.escape(value) if self.is_html else value))
        if upper in _UNSUBSCRIBE:
            return _swap(match, "{{ unsubscribe_url }}")
        if upper in _PREFERENCES:
            self.preferences_link = True
            return _swap(match, "{{ unsubscribe_url }}")
        if upper == "CURRENT_YEAR":
            return _swap(match, '{{ "now" | date: "%Y" }}')
        if upper.startswith("DATE:"):
            date_format = _strftime(body[5:])
            if date_format is None:
                return None
            return _swap(match, f'{{{{ "now" | date: "{date_format}" }}}}')
        raw = upper.startswith("HTML:")
        name = body[5:] if raw else body
        if not _NAME.fullmatch(name) or name.upper() in _MAILCHIMP_ONLY or name.upper() in _UNSUBSCRIBE | _PREFERENCES:
            return None
        self.merge_fields.append(_field_name(name))
        path = person_path(name)
        if not self.is_html:
            liquid = f"{{{{ {path} }}}}"
        elif raw:
            liquid = f"{{{{ {path} | raw }}}}"
        else:
            liquid = f"{{{{ {path} | escape | raw }}}}"
        return _swap(match, liquid, value=True, raw=raw)

    def _conditions(self, matches: list[re.Match[str]]) -> dict[int, str]:
        """The Liquid for each condition tag by its position, or nothing when any condition can't convert."""
        converted: dict[int, str] = {}
        depth = 0
        open_has_else: list[bool] = []
        for match in matches:
            body = match.group(1).strip()
            keyword, _, argument = body.partition(":")
            keyword = keyword.upper()
            if keyword not in _CONDITION_KEYWORDS or (keyword == "END" and argument.strip().upper() != "IF"):
                continue
            if keyword in ("ELSE", "END") and ":" not in body:
                continue
            if _ENTITY.search(body):
                return {}
            if keyword in ("IF", "IFNOT"):
                test = self._test(argument, negate=keyword == "IFNOT")
                if test is None:
                    return {}
                converted[match.start()] = f"{{% if {test} %}}"
                depth += 1
                open_has_else.append(False)
            elif keyword == "ELSEIF":
                test = self._test(argument, negate=False)
                if test is None or not depth or open_has_else[-1]:
                    return {}
                converted[match.start()] = f"{{% elsif {test} %}}"
            elif keyword == "ELSE":
                if argument.strip() or not depth or open_has_else[-1]:
                    return {}
                open_has_else[-1] = True
                converted[match.start()] = "{% else %}"
            else:
                if not depth:
                    return {}
                depth -= 1
                open_has_else.pop()
                converted[match.start()] = "{% endif %}"
        if depth:
            return {}
        return converted

    def _test(self, argument: str, *, negate: bool) -> str | None:
        condition = _CONDITION.fullmatch(argument.strip())
        if condition is None:
            return None
        name, operator, value = condition.group(1), condition.group(2), condition.group(3)
        if name.upper() in self.fixed:
            # A tag with one value for every recipient, such as the preview text, decides the condition now.
            known = self.fixed[name.upper()]
            if known is None and operator is not None:
                return None
            holds = known is None or bool(known) if operator is None else (known == value.strip()) == (operator == "=")
            return "true" if holds != negate else "false"
        if name.upper() in _MAILCHIMP_ONLY:
            return None
        self.person_conditions = True
        self.merge_fields.append(_field_name(name))
        path = person_path(name)
        if operator is None:
            # Liquid treats an empty string as true, while Mailchimp treats a blank field as false.
            return f'{path} == nil or {path} == ""' if negate else f'{path} and {path} != ""'
        if _NUMBER.fullmatch(value):
            # A number property never equals the quoted value in Liquid, so the condition stays as written.
            return None
        comparison = "!=" if (operator == "!=") != negate else "=="
        return f'{path} {comparison} "{value.strip()}"'

    def _in_safe_places(self, replacements: list[_Replacement]) -> list[_Replacement]:
        """Drops value replacements anywhere but page text or a quoted attribute value Liquid escapes the way Mailchimp
        does. Those tags stay as written."""
        context = HtmlContext()
        cursor = 0
        kept: list[_Replacement] = []
        # For each open condition: where it started, where each branch ended, and whether it has an ELSE.
        open_conditions: list[tuple[Place, list[Place], list[bool]]] = []
        for replacement in replacements:
            context.feed(self.text[cursor : replacement.start])
            cursor = replacement.start
            if replacement.branch:
                cursor = replacement.end
                self._follow_branch(context, replacement.branch, open_conditions)
                kept.append(replacement)
                continue
            if replacement.value:
                where = context.where()
                in_plain_attribute = where == "title" or (where == "value" and context.plain_attribute())
                if context.untrusted or (where != "text" and (replacement.raw or not in_plain_attribute)):
                    self.unsupported.append(replacement.source)
                    continue
                context.feed("x")
                cursor = replacement.end
            kept.append(replacement)
        return kept

    @staticmethod
    def _follow_branch(
        context: HtmlContext, branch: str, open_conditions: list[tuple[Place, list[Place], list[bool]]]
    ) -> None:
        """Reads each branch of a condition from where the condition started. Branches that leave the HTML in
        different places hide where later values sit, so none of them convert."""
        if branch == "if":
            open_conditions.append((context.snapshot(), [], [False]))
            return
        start, ends, has_else = open_conditions[-1]
        ends.append(context.snapshot())
        if branch != "endif":
            has_else[0] = has_else[0] or branch == "else"
            context.restore(start)
            return
        open_conditions.pop()
        if not has_else[0]:
            ends.append(start)
        context.restore(ends[0])
        if any(end != ends[0] for end in ends):
            context.untrusted = True


def _length(text: str) -> int:
    """The length a send's renderer counts, in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def _swap(
    match: re.Match[str], liquid: str, *, value: bool = False, raw: bool = False, branch: str = ""
) -> _Replacement:
    return _Replacement(
        start=match.start(), end=match.end(), source=match.group(0), liquid=liquid, value=value, raw=raw, branch=branch
    )


def _strftime(php_format: str) -> str | None:
    if not php_format:
        return None
    out: list[str] = []
    for character in php_format:
        if character in _DATE_CODES:
            out.append(_DATE_CODES[character])
        elif character in _DATE_SEPARATORS:
            out.append(character)
        else:
            return None
    return "".join(out)


def _append(out: list[str], chunk: str) -> None:
    """Adds a chunk, so a `{` that ends one chunk and a `{` or `%` that starts the next never join into a Liquid tag."""
    if not chunk:
        return
    if out and out[-1].endswith("{") and chunk[0] in "{%":
        out[-1] = out[-1][:-1] + '{{ "{" }}'
    out.append(chunk)


def _literal(text: str) -> str:
    # Only the openings are Liquid, so text outside them prints exactly as written.
    return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', text)
