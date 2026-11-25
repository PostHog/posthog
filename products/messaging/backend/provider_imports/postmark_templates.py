"""Turns a Postmark template into PostHog's Liquid, and says what did not carry over.

Mustachio has no scope chain: inside `{{#person}}` a name reads only from `person`, and inside `{{#each items}}` the
parent of an item is the list, so `../../x` reaches the object holding the list. Liquid has no sections at all, so the
translator works out each name's full path while it reads the template. See
https://postmarkapp.com/support/article/1077-template-syntax and https://github.com/ActiveCampaign/mustachio, whose
parser is the source for the rules that page leaves out.
"""

import re
from typing import Any

from posthog.dataclasses import frozen

# The same token pattern as Mustachio's tokenizer, so text splits at the same places.
_TOKEN = re.compile(r"(\{\{[^{}]+?\}\})|(\{\{\{[^{}]+?\}\}\})")
# Mustachio refuses these paths when a template is saved.
_INVALID_PATH = re.compile(r"([.]{3,})|([^\w./_]+)|((?<![.]{2})/)|([.]{2,}($|[^/]))")
_PATH_ELEMENT = re.compile(r"(\.\.[\\/])|([^.]+)")
_PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPENING = re.compile(r"\{[{%]")
_UNSUBSCRIBE = re.compile(r"\s*pm:unsubscribe\s*")
_HREF_OPENING = re.compile(r"""href\s*=\s*\\?["']?$""", re.IGNORECASE)
# Postmark's pages show the placeholder both ways.
_CONTENT_PLACEHOLDER = re.compile(r"\{\{\{\s*@?content\s*\}\}\}|\{\{\s*@content\s*\}\}")
_STYLE_BLOCK = re.compile(r"<style[\s>]", re.IGNORECASE)
_MAX_NOTED_TAGS = 5
# Each name inside a section prints the section's whole path, so deep nesting grows the output much faster than the input.
_MIN_OUTPUT_BUDGET = 1_000_000
_OUTPUT_GROWTH_LIMIT = 20
_TOO_NESTED = "a part whose sections nest too deeply"


@frozen
class _Scope:
    # The Liquid expression for this scope's value. None when Mustachio always finds nothing there.
    expression: str | None
    parent: "_Scope | None" = None
    is_list: bool = False


@frozen
class _Block:
    # What closes the block, compared the way Mustachio compares it.
    token: str
    scope: _Scope
    outer_scope: _Scope
    closing: str
    is_if: bool = False


@frozen
class ConvertedText:
    text: str
    unsupported_tags: tuple[str, ...] = ()
    uses_this: bool = False
    uses_if: bool = False
    uses_unsubscribe_link: bool = False


def convert_text(text: str | None, *, is_html: bool) -> ConvertedText:
    """Rewrites one part of a template to Liquid. Subjects and text bodies print values unescaped in both tools."""
    if not text:
        return ConvertedText(text="")
    try:
        return _Converter(is_html, budget=max(_MIN_OUTPUT_BUDGET, _OUTPUT_GROWTH_LIMIT * len(text))).convert(text)
    except _OutputTooLarge:
        return ConvertedText(text=_literal(text), unsupported_tags=(_TOO_NESTED,))


class _OutputTooLarge(Exception):
    pass


class _Converter:
    def __init__(self, is_html: bool, *, budget: int) -> None:
        self._is_html = is_html
        self._budget = budget
        self._root = _Scope(expression="variables")
        self._scope = self._root
        self._blocks: list[_Block] = []
        self._loops = 0
        self._out: list[str] = []
        self._unsupported: list[str] = []
        self._uses_this = False
        self._uses_if = False
        self._uses_unsubscribe = False

    def _emit(self, part: str) -> None:
        self._spend(len(part))
        self._out.append(part)

    def _spend(self, size: int) -> None:
        self._budget -= size
        if self._budget < 0:
            raise _OutputTooLarge

    def convert(self, text: str) -> ConvertedText:
        position = 0
        for match in _TOKEN.finditer(text):
            self._emit(_literal(text[position : match.start()]))
            self._token(match.group(0), preceding=text[position : match.start()])
            position = match.end()
        self._emit(_literal(text[position:]))
        # Postmark refuses an unclosed block when it saves a template, so this only protects the Liquid parse.
        while self._blocks:
            self._unsupported.append(f"unclosed {self._blocks[-1].token}")
            self._close()
        return ConvertedText(
            text="".join(self._out),
            unsupported_tags=tuple(dict.fromkeys(self._unsupported)),
            uses_this=self._uses_this,
            uses_if=self._uses_if,
            uses_unsubscribe_link=self._uses_unsubscribe,
        )

    def _token(self, token: str, preceding: str) -> None:
        if token.startswith("{{#each"):
            self._open_each(token)
        elif token.startswith("{{/each"):
            self._close_each(token)
        elif re.match(r"\{\{#if\s", token):
            self._open_if(token)
        elif token.startswith("{{#"):
            self._open_section(token, token[3:-2].strip(), inverted=False)
        elif token.startswith("{{^"):
            self._open_section(token, token[3:-2].strip(), inverted=True)
        elif token.startswith("{{/"):
            self._close_section(token, token[3:-2].strip())
        elif token.startswith("{{!"):
            return
        elif token.startswith(("{{{", "{{&")):
            self._value(token, token.strip("{}").lstrip("&").strip(), escaped=False, preceding=preceding)
        elif token[2:-2].strip() == "else" and self._blocks and self._blocks[-1].is_if:
            self._emit("{% else %}")
        else:
            self._value(token, token[2:-2].strip(), escaped=True, preceding=preceding)

    def _value(self, token: str, path: str, *, escaped: bool, preceding: str) -> None:
        if _UNSUBSCRIBE.fullmatch(path):
            self._emit(self._unsubscribe_link(preceding))
            return
        if _INVALID_PATH.search(path):
            self._not_converted(token)
            return
        scope = self._resolve(path)
        if scope.expression is None or scope.is_list:
            return
        raw = " | raw" if not escaped and self._is_html else ""
        self._emit(f"{{{{ {scope.expression}{raw} }}}}")

    def _unsubscribe_link(self, preceding: str) -> str:
        self._uses_unsubscribe = True
        if self._is_html and not _HREF_OPENING.search(preceding):
            return '<a href="{{ unsubscribe_url }}">Unsubscribe</a>'
        return "{{ unsubscribe_url }}"

    def _open_section(self, token: str, path: str, *, inverted: bool) -> None:
        if _INVALID_PATH.search(path):
            self._not_converted(token)
            return
        # `{{#a}}...{{^a}}...{{/a}}` is Mustachio's if and else: opening the same path again closes the block.
        if self._blocks and self._blocks[-1].token == path:
            self._close()
        scope = self._resolve(path)
        condition = _truthy(scope)
        tag, closing = ("unless", "{% endunless %}") if inverted else ("if", "{% endif %}")
        self._emit(f"{{% {tag} {condition} %}}")
        self._push(_Block(token=path, scope=scope, outer_scope=self._scope, closing=closing))

    def _close_section(self, token: str, path: str) -> None:
        if not self._blocks or self._blocks[-1].token != path:
            self._not_converted(token)
            return
        self._close()

    def _open_each(self, token: str) -> None:
        path = token[2:-2].lstrip("#")[4:]
        if not path.startswith(" ") or not path.strip() or _INVALID_PATH.search(path.strip()):
            self._not_converted(token)
            return
        collection = self._resolve(path.strip())
        self._loops += 1
        item = f"item_{self._loops}"
        source = collection.expression if collection.expression is not None and not collection.is_list else "nil"
        self._emit(f"{{% for {item} in {source} %}}")
        list_scope = _Scope(expression=None, parent=collection.parent, is_list=True)
        self._push(
            _Block(
                token=token,
                scope=_Scope(expression=item, parent=list_scope),
                outer_scope=self._scope,
                closing="{% endfor %}",
            )
        )

    def _close_each(self, token: str) -> None:
        if token != "{{/each}}" or not self._blocks or not self._blocks[-1].token.startswith("{{#each"):
            self._not_converted(token)
            return
        self._close()

    def _open_if(self, token: str) -> None:
        # Postmark's syntax page has no `{{#if}}` but its migration guides show one, with names read in the same scope.
        path = token[2:-2][3:].strip()
        if _INVALID_PATH.search(path):
            self._not_converted(token)
            return
        self._uses_if = True
        self._emit(f"{{% if {_truthy(self._resolve(path))} %}}")
        self._push(_Block(token="if", scope=self._scope, outer_scope=self._scope, closing="{% endif %}", is_if=True))

    def _push(self, block: _Block) -> None:
        self._blocks.append(block)
        self._scope = block.scope

    def _close(self) -> None:
        block = self._blocks.pop()
        self._emit(block.closing)
        self._scope = block.outer_scope

    def _resolve(self, path: str) -> _Scope:
        scope = self._scope
        first = True
        for match in _PATH_ELEMENT.finditer(path):
            element = match.group(0)
            if element.startswith(".."):
                # Going above the top stays at the top, as in Mustachio.
                scope = scope.parent or scope
            else:
                self._uses_this = self._uses_this or (first and element == "this")
                expression = _child(scope, element)
                # Each step of a long path copies the whole path so far, so the work counts against the budget too.
                self._spend(len(expression or ""))
                scope = _Scope(expression=expression, parent=scope)
            first = False
        return scope

    def _not_converted(self, token: str) -> None:
        self._unsupported.append(token)
        self._emit(_literal(token))


def _child(scope: _Scope, name: str) -> str | None:
    if scope.expression is None or scope.is_list:
        return None
    if _PLAIN_NAME.fullmatch(name):
        return f"{scope.expression}.{name}"
    return f'{scope.expression}["{name}"]'


def _truthy(scope: _Scope) -> str:
    """Liquid treats an empty string, an empty list and 0 as true. Mustachio treats them as missing."""
    expression = scope.expression
    if expression is None:
        return "false"
    return f"{expression} and {expression} != empty and {expression} != 0"


def _literal(text: str) -> str:
    """Text that Mustachio prints as is, written so that Liquid does too."""
    escaped = _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', text)
    # A `{` right before a printed value would read as a longer tag.
    return f'{escaped[:-1]}{{{{ "{{" }}}}' if escaped.endswith("{") else escaped


@frozen
class ConvertedTemplate:
    subject: str
    html: str
    text: str
    notes: tuple[str, ...]


def merge_layout(body: str | None, layout_body: str | None) -> tuple[str, bool]:
    """Puts a template part into its layout, before translation, so the layout's sections scope it the same way."""
    if not body:
        return "", True
    if not layout_body:
        return body, True
    merged, count = _CONTENT_PLACEHOLDER.subn(lambda _: body, layout_body, count=1)
    return (merged, True) if count else (body, False)


def convert_template(template: dict[str, Any], layout: dict[str, Any] | None = None) -> ConvertedTemplate:
    """The template's subject and bodies in Liquid, with its layout copied in and notes on anything to review."""
    layout_alias = template.get("LayoutTemplate")
    html_source, html_placed = merge_layout(template.get("HtmlBody"), (layout or {}).get("HtmlBody"))
    text_source, text_placed = merge_layout(template.get("TextBody"), (layout or {}).get("TextBody"))

    subject = convert_text(template.get("Subject"), is_html=False)
    html = convert_text(html_source, is_html=True)
    text = convert_text(text_source, is_html=False)
    parts = (subject, html, text)
    notes: list[str] = []

    if layout_alias and layout is None:
        notes.append(f"Postmark couldn't find the layout {layout_alias}, so this template has no layout. Add it again.")
    elif layout is not None:
        notes.append(
            f"PostHog has no layouts, so this template has its own copy of the layout {layout_alias}. "
            "A change to one copy doesn't reach the others."
        )
        if not (html_placed and text_placed):
            notes.append(
                f"The layout {layout_alias} has no content placeholder in its HTML or its text, so that part has no "
                "layout."
            )
    if tags := list(dict.fromkeys(tag for part in parts for tag in part.unsupported_tags)):
        shown = ", ".join(tags[:_MAX_NOTED_TAGS])
        more = f" and {len(tags) - _MAX_NOTED_TAGS} more" if len(tags) > _MAX_NOTED_TAGS else ""
        notes.append(f"PostHog can't convert {shown}{more}, so it appears as plain text. Rewrite it in Liquid.")
    if any(part.uses_this for part in parts):
        notes.append(
            "This template uses `this`. Postmark's template engine reads it as a value named this, not the current "
            "value, and PostHog does the same. If you meant the current value, change it in Liquid."
        )
    if any(part.uses_if for part in parts):
        notes.append(
            "This template uses `{{#if}}`, which Postmark's syntax page doesn't describe. PostHog shows that part when "
            "the value isn't empty, so check that the output is right."
        )
    if _STYLE_BLOCK.search(html_source):
        notes.append(
            "Postmark copies CSS from a style block onto each element when it sends. PostHog sends the style block as "
            "it is, so check this email in the mail clients you care about."
        )
    if html_source and not any(part.uses_unsubscribe_link for part in parts):
        notes.append(
            "On a broadcast stream, Postmark adds an unsubscribe link when a template has none. PostHog doesn't, so add "
            "one with {{ unsubscribe_url }} if you send this as marketing email."
        )
    if template.get("Active") is False:
        notes.append("This template is inactive in Postmark, so it can't send there. Check that you still need it.")
    return ConvertedTemplate(subject=subject.text, html=html.text, text=text.text, notes=tuple(notes))
