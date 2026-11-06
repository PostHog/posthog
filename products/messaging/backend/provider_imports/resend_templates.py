"""Turns a Resend template into PostHog's Liquid, and says what did not carry over.

Resend writes a variable as `{{{NAME}}}` or `{{NAME}}`, optionally with a fallback: `{{{NAME|there}}}`. Conditions and
loops aren't part of Resend's documented syntax. Anything else in braces is left as literal text and named in a note,
so a person decides what it should become.
"""

import re
from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

# Tag bodies are capped, so text full of unclosed braces scans in linear time, and stop at the next opening, so an unclosed
# tag can't swallow a real variable after it. The last two alternatives catch that unclosed opening, which Liquid would
# otherwise refuse to parse, failing every send of the template.
_TAG = re.compile(
    r"\{\{\{((?:(?!\{\{).){0,500}?)\}\}\}|\{\{((?:(?!\{\{).){0,500}?)\}\}|\{%(?:(?!\{%).){0,500}?%\}|\{\{|\{%",
    re.DOTALL,
)
_OPENING = re.compile(r"\{[{%]")
# The email renderer treats a backslash or an HTML entity inside a filter argument differently from Resend.
_UNSAFE_IN_LIQUID_STRING = re.compile(r"\\|&(?:\w+|#\d+|#[xX][0-9a-fA-F]+);")
_VARIABLE = re.compile(r"^[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*$")
_UNSUBSCRIBE_VARIABLES = {"UNSUBSCRIBE_URL", "RESEND_UNSUBSCRIBE_URL"}
_CONTACT_VARIABLES = {"FIRST_NAME", "LAST_NAME", "EMAIL"}
# Handlebars words that read like a variable name but aren't one.
_NOT_VARIABLES = {"else", "this", "true", "false", "null"}
_MAX_NOTED_TAGS = 5


@frozen
class ConvertedText:
    text: str
    # Variable names the text uses, with any `contact.` prefix removed.
    variables: tuple[str, ...] = ()
    contact_variables: tuple[str, ...] = ()
    unsupported_tags: tuple[str, ...] = ()
    dropped_fallbacks: tuple[str, ...] = ()
    uses_unsubscribe_link: bool = False


def convert_text(text: str | None, fallbacks: Mapping[str, Any], *, is_html: bool) -> ConvertedText:
    """Rewrites `text` to Liquid. `fallbacks` are the template-level fallback values by variable name."""
    if not text:
        return ConvertedText(text="")
    variables: list[str] = []
    contact_variables: list[str] = []
    unsupported: list[str] = []
    dropped: list[str] = []
    uses_unsubscribe = False

    def replace(match: re.Match[str]) -> str:
        nonlocal uses_unsubscribe
        triple, double = match.group(1), match.group(2)
        body = triple if triple is not None else double
        if body is None:
            unsupported.append(match.group(0))
            return _literal(match.group(0))
        name, separator, inline_fallback = body.partition("|")
        name = name.strip()
        if not _VARIABLE.match(name) or name in _NOT_VARIABLES:
            unsupported.append(match.group(0))
            return _literal(match.group(0))
        if name in _UNSUBSCRIBE_VARIABLES:
            uses_unsubscribe = True
            return "{{ unsubscribe_url }}"
        is_contact = name.startswith("contact.")
        plain_name = name.removeprefix("contact.")
        if is_contact or plain_name in _CONTACT_VARIABLES:
            contact_variables.append(plain_name)
        variables.append(plain_name)
        fallback = inline_fallback.strip() if separator else fallbacks.get(plain_name)
        filters = ""
        if fallback not in (None, ""):
            default = _liquid_string(fallback)
            if default is None:
                dropped.append(plain_name)
            else:
                filters += f" | default: {default}"
        if triple is not None and is_html:
            # Triple braces print the value without escaping it, the way Resend does.
            filters += " | raw"
        return f"{{{{ variables.{plain_name}{filters} }}}}"

    return ConvertedText(
        text=_TAG.sub(replace, text),
        variables=tuple(dict.fromkeys(variables)),
        contact_variables=tuple(dict.fromkeys(contact_variables)),
        unsupported_tags=tuple(dict.fromkeys(unsupported)),
        dropped_fallbacks=tuple(dict.fromkeys(dropped)),
        uses_unsubscribe_link=uses_unsubscribe,
    )


def _literal(tag: str) -> str:
    # A raw block ends at the first `endraw` and needs a close of its own, so these print their openings another way.
    if "endraw" in tag or tag in ("{{", "{%"):
        return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', tag)
    return f"{{% raw %}}{tag}{{% endraw %}}"


def _liquid_string(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if any(braces in text for braces in ("{{", "}}", "{%", "%}")) or _UNSAFE_IN_LIQUID_STRING.search(text):
        return None
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    return None


@frozen
class ConvertedTemplate:
    subject: str
    html: str
    text: str
    notes: tuple[str, ...]
    # About values the app passes when it sends. An automation fills these from its steps instead.
    send_notes: tuple[str, ...] = ()


def convert_template(template: dict[str, Any]) -> ConvertedTemplate:
    """The template's subject and bodies in Liquid, with notes on anything to review."""
    declared = [variable for variable in template.get("variables") or [] if isinstance(variable, dict)]
    fallbacks = {str(variable.get("key")): variable.get("fallback_value") for variable in declared}
    subject = convert_text(template.get("subject"), fallbacks, is_html=False)
    html = convert_text(template.get("html"), fallbacks, is_html=True)
    text = convert_text(template.get("text"), fallbacks, is_html=False)
    parts = (subject, html, text)
    notes: list[str] = []
    send_notes: list[str] = []

    if tags := list(dict.fromkeys(tag for part in parts for tag in part.unsupported_tags)):
        shown = ", ".join(tags[:_MAX_NOTED_TAGS])
        more = f" and {len(tags) - _MAX_NOTED_TAGS} more" if len(tags) > _MAX_NOTED_TAGS else ""
        notes.append(f"PostHog can't convert {shown}{more}, so it appears as plain text. Rewrite it in Liquid.")
    if contact := list(dict.fromkeys(name for part in parts for name in part.contact_variables)):
        send_notes.append(
            f"Resend fills {', '.join(contact)} from the contact. PostHog doesn't, so your app has to pass the value."
        )
    if dropped := list(dict.fromkeys(name for part in parts for name in part.dropped_fallbacks)):
        notes.append(
            f"The fallback for {', '.join(dropped)} has characters PostHog can't keep. Add it again in Liquid."
        )
    used = {name for part in parts for name in part.variables}
    if without_fallback := sorted(
        name for name in used if fallbacks.get(name) in (None, "") and name not in _CONTACT_VARIABLES
    ):
        if missing := [name for name in without_fallback if _has_no_inline_fallback(template, name)]:
            send_notes.append(
                f"Resend refuses to send without {', '.join(missing)}. PostHog sends with a blank value instead, "
                "so always pass a value or add a default."
            )
    if template.get("status") != "published":
        notes.append("This template isn't published in Resend. PostHog imported its current draft.")
    elif template.get("has_unpublished_versions"):
        notes.append("This template has unpublished edits in Resend. PostHog imported the published version.")
    return ConvertedTemplate(
        subject=subject.text, html=html.text, text=text.text, notes=tuple(notes), send_notes=tuple(send_notes)
    )


def _has_no_inline_fallback(template: dict[str, Any], name: str) -> bool:
    bodies = "".join(str(template.get(field) or "") for field in ("subject", "html", "text"))
    return re.search(r"\{\{\{?\s*(?:contact\.)?" + re.escape(name) + r"\s*\|", bodies) is None
