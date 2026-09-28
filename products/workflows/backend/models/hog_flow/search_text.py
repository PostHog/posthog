import re
from collections.abc import Iterator
from typing import Any, Final

from django.db import models

from posthog.dataclasses import frozen


class StepSearchField(models.TextChoices):
    STEP_NAME = "step_name"
    SUBJECT = "subject"
    PREHEADER = "preheader"
    BODY = "body"


class StepSearchSource(models.TextChoices):
    LIVE = "live"
    DRAFT = "draft"


MAX_SEARCH_TERM_LENGTH: Final = 200

# Joins the fields in `HogFlow.search_text`. Postgres does not count U+001F as whitespace, so the `[\s\-_]*`
# that a space in the search term becomes cannot match across it, and a term never spans two fields.
SEARCH_TEXT_SEPARATOR: Final = "\x1f"

EXCERPT_PADDING: Final = 40

_STYLE_OPEN = re.compile(r"<style", re.IGNORECASE | re.ASCII)
_STYLE_CLOSE = re.compile(r"</style>", re.IGNORECASE | re.ASCII)
_SCRIPT_OPEN = re.compile(r"<script", re.IGNORECASE | re.ASCII)
_SCRIPT_CLOSE = re.compile(r"</script>", re.IGNORECASE | re.ASCII)
_TAG_SYNTAX = re.compile(r"""[<>"']""")


@frozen
class StepSearchText:
    action_id: str
    field: StepSearchField
    source: StepSearchSource
    text: str


@frozen
class StepSearchMatch:
    action_id: str
    field: StepSearchField
    source: StepSearchSource
    excerpt: str


def search_pattern(term: str) -> str:
    """The search term as a case-insensitive regex source: literal characters, with a space also matching dashes and
    underscores. The same source is valid for Python's `re` and for Postgres `~*`."""
    return re.escape(term).replace(r"\ ", r"[\s\-_]*")


def _remove_blocks(html: str, opening: re.Pattern[str], closing: re.Pattern[str]) -> str:
    # Same result as the SQL `'<style[^>]*?>.*?</style>'` with the `gi` flags. A regex would rescan to the end of
    # the text from every unclosed opening tag, which is quadratic. When no closing tag follows one opening tag,
    # none follows a later one either, so the loop can stop there.
    parts: list[str] = []
    cursor = 0
    while (start := opening.search(html, cursor)) is not None:
        opening_end = html.find(">", start.end())
        if opening_end == -1:
            break
        end = closing.search(html, opening_end + 1)
        if end is None:
            break
        parts.append(html[cursor : start.start()])
        parts.append(" ")
        cursor = end.end()
    parts.append(html[cursor:])
    return "".join(parts)


def _remove_tags(html: str) -> str:
    """Same result as the SQL `'<[^>"'']*(("[^"]*"|''[^'']*'')[^>"'']*)*>'` with the `g` flag, in linear time.

    A tag body is scanned left to right: a quote skips to the next quote of the same kind, and the first `>` outside
    quotes ends the tag. The scan from one position always takes the same path, so the end of a tag that starts at
    each syntax character is computed once, from the right. A backtracking regex would instead rescan the rest of the
    text from every `<` that no `>` closes.
    """
    syntax = [(match.start(), match.group()) for match in _TAG_SYNTAX.finditer(html)]
    # tag_end[i] is the index of the `>` that ends a tag body scanned from syntax[i], or -1 when nothing ends it.
    tag_end = [-1] * (len(syntax) + 1)
    next_quote: dict[str, int] = {}
    for index in range(len(syntax) - 1, -1, -1):
        position, char = syntax[index]
        if char == ">":
            tag_end[index] = position
        elif char == "<":
            tag_end[index] = tag_end[index + 1]
        else:
            closing_quote = next_quote.get(char)
            tag_end[index] = -1 if closing_quote is None else tag_end[closing_quote + 1]
            next_quote[char] = index

    parts: list[str] = []
    cursor = 0
    for index, (position, char) in enumerate(syntax):
        if char != "<" or position < cursor:
            continue
        end = tag_end[index + 1]
        if end == -1:
            continue
        parts.append(html[cursor:position])
        parts.append(" ")
        cursor = end + 1
    parts.append(html[cursor:])
    return "".join(parts)


def email_body_text(email: dict[str, Any]) -> str | None:
    """The email body as a person reads it. Mirrors `_EMAIL_BODY_TEXT_SQL` in the workflows API: the editor's
    plain-text export when it is set, otherwise the HTML without style blocks, script blocks and tags."""
    text = email.get("text")
    if isinstance(text, str) and text:
        return text
    html = email.get("html")
    if not isinstance(html, str):
        return None
    html = _remove_blocks(html, _STYLE_OPEN, _STYLE_CLOSE)
    html = _remove_blocks(html, _SCRIPT_OPEN, _SCRIPT_CLOSE)
    return _remove_tags(html)


def _step_texts(action: Any, source: StepSearchSource) -> Iterator[StepSearchText]:
    if not isinstance(action, dict):
        return
    action_id = str(action.get("id") or "")
    name = action.get("name")
    if isinstance(name, str):
        yield StepSearchText(action_id=action_id, field=StepSearchField.STEP_NAME, source=source, text=name)

    email = _email_value(action)
    if email is None:
        return
    for field in (StepSearchField.SUBJECT, StepSearchField.PREHEADER):
        value = email.get(field.value)
        if isinstance(value, str):
            yield StepSearchText(action_id=action_id, field=field, source=source, text=value)
    body = email_body_text(email)
    if body is not None:
        yield StepSearchText(action_id=action_id, field=StepSearchField.BODY, source=source, text=body)


def _email_value(action: dict[str, Any]) -> dict[str, Any] | None:
    value: Any = action
    for key in ("config", "inputs", "email", "value"):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def _action_list(value: Any) -> list[Any]:
    # `actions` defaults to {} on a workflow that never got a graph, and a draft may carry no actions.
    return value if isinstance(value, list) else []


def iter_step_search_texts(actions: Any, draft: Any) -> Iterator[StepSearchText]:
    """Every searchable text of every step, live steps first, then the steps staged in the draft."""
    for action in _action_list(actions):
        yield from _step_texts(action, StepSearchSource.LIVE)
    draft_actions = draft.get("actions") if isinstance(draft, dict) else None
    for action in _action_list(draft_actions):
        yield from _step_texts(action, StepSearchSource.DRAFT)


def build_search_text(*, name: str | None, description: str | None, actions: Any, draft: Any) -> str:
    """The text the workflow search matches against, stored as `HogFlow.search_text`."""
    values = [name or "", description or ""]
    values.extend(step.text for step in iter_step_search_texts(actions, draft))
    # A draft is a full copy of the live content, so most of its values repeat one that is already present.
    return SEARCH_TEXT_SEPARATOR.join(dict.fromkeys(value for value in values if value))


def _excerpt(text: str, regex: re.Pattern[str]) -> str:
    collapsed = " ".join(text.split())
    match = regex.search(collapsed)
    if match is None:
        return collapsed[: 2 * EXCERPT_PADDING]
    start = max(0, match.start() - EXCERPT_PADDING)
    end = min(len(collapsed), match.end() + EXCERPT_PADDING)
    # Snap to word boundaries so the excerpt does not open or close in the middle of a word.
    first_space = collapsed.find(" ", start, match.start())
    if start > 0 and first_space != -1:
        start = first_space + 1
    last_space = collapsed.rfind(" ", match.end() + 1, end)
    if end < len(collapsed) and last_space != -1:
        end = last_space
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(collapsed) else ""
    return f"{prefix}{collapsed[start:end]}{suffix}"


def find_step_matches(actions: Any, draft: Any, term: str) -> list[StepSearchMatch]:
    """The steps whose text matches the search term, one entry per step with the first field that matched.

    A staged step is listed only when its live version did not match, so each step appears once, with the text a
    person most likely looks at.
    """
    regex = re.compile(search_pattern(term), re.IGNORECASE)
    matches: dict[str, StepSearchMatch] = {}
    for step in iter_step_search_texts(actions, draft):
        if step.action_id in matches or regex.search(step.text) is None:
            continue
        matches[step.action_id] = StepSearchMatch(
            action_id=step.action_id,
            field=step.field,
            source=step.source,
            excerpt=_excerpt(step.text, regex),
        )
    return list(matches.values())
