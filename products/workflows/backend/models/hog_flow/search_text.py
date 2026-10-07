import re
from collections.abc import Iterator
from typing import Final

import re2
import posthoganalytics

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import (
    StepSearchField,
    StepSearchVersion,
    WorkflowMetadataField,
    WorkflowSearchOutput,
)

MAX_SEARCH_TERM_LENGTH: Final = 200


def workflow_search_enabled(team_id: int) -> bool:
    try:
        return (
            posthoganalytics.feature_enabled(
                "workflows-search-mcp-tool",
                f"team_{team_id}",
                groups={"project": str(team_id)},
                group_properties={"project": {"id": str(team_id)}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        return False


DEFAULT_MAX_MATCHED_STEPS: Final = 2
MAX_MATCHED_STEPS: Final = 10
DEFAULT_EXCERPT_CHARS: Final = 80
MAX_EXCERPT_CHARS: Final = 160
_WHITESPACE: Final = re.compile(r"\s+")

SEARCH_TEXT_SOURCE_FIELDS: Final[frozenset[str]] = frozenset({"name", "description", "actions", "draft"})

# Joins the fields in `HogFlow.search_text`. It is a Unicode noncharacter, which no Postgres locale provider counts
# as whitespace, so the `[\s\-_]*` that a space in the search term becomes cannot match across it. The search
# rejects a term that contains it, so a term never spans two fields.
SEARCH_TEXT_SEPARATOR: Final = "﷐"

# The characters that Postgres counts as `\s` under a glibc UTF-8 locale, so the step matcher finds the text that
# the row search matched. RE2's `\s` is ASCII only and omits the vertical tab. No-break spaces are not in the set.
_STEP_MATCH_SPACE: Final = r"[\t\n\v\f\r \x{85}\x{2000}-\x{2006}\x{2008}-\x{200A}\x{2028}\x{2029}\x{205F}\x{3000}\-_]*"

_STYLE_OPEN = re.compile(r"<style", re.IGNORECASE | re.ASCII)
_STYLE_CLOSE = re.compile(r"</style>", re.IGNORECASE | re.ASCII)
_SCRIPT_OPEN = re.compile(r"<script", re.IGNORECASE | re.ASCII)
_SCRIPT_CLOSE = re.compile(r"</script>", re.IGNORECASE | re.ASCII)
_TAG_SYNTAX = re.compile(r"""[<>"']""")


@frozen
class StepSearchText:
    action_id: str
    field: StepSearchField
    matched_in: StepSearchVersion
    text: str


@frozen
class StepSearchMatch:
    action_id: str
    field: StepSearchField
    matched_in: StepSearchVersion
    excerpt: str


@frozen
class SearchResultShape:
    regex: re2._Regexp
    output: WorkflowSearchOutput
    max_steps: int
    excerpt_chars: int


@frozen
class StepMatches:
    count: int
    steps: list[StepSearchMatch]


def search_pattern(term: str) -> str:
    """The search term as a Postgres regex for `~*`: literal characters, where a run of spaces also matches any run
    of whitespace, dashes and underscores."""
    return r"[\s\-_]*".join(re.escape(part) for part in re.split(r" +", term))


def step_regex(term: str) -> re2._Regexp:
    # The same rule as search_pattern, compiled with RE2. The term comes from the request and the text can be a whole
    # email, and RE2 matches in linear time where Python's backtracking `re` can take exponential time.
    return re2.compile("(?i)" + _STEP_MATCH_SPACE.join(re2.escape(part) for part in re.split(r" +", term)))


def _json_text(value: object) -> str | None:
    """A JSON scalar as the text that the Postgres `#>>` operator returns for it."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return None


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
    # tag_close_position[i] is the position in `html` of the `>` that ends a tag body scanned from syntax[i], or -1
    # when no `>` ends it.
    tag_close_position = [-1] * (len(syntax) + 1)
    next_quote: dict[str, int] = {}
    for index in range(len(syntax) - 1, -1, -1):
        position, char = syntax[index]
        if char == ">":
            tag_close_position[index] = position
        elif char == "<":
            tag_close_position[index] = tag_close_position[index + 1]
        else:
            closing_quote = next_quote.get(char)
            tag_close_position[index] = -1 if closing_quote is None else tag_close_position[closing_quote + 1]
            next_quote[char] = index

    parts: list[str] = []
    cursor = 0
    for index, (position, char) in enumerate(syntax):
        if char != "<" or position < cursor:
            continue
        end = tag_close_position[index + 1]
        if end == -1:
            continue
        parts.append(html[cursor:position])
        parts.append(" ")
        cursor = end + 1
    parts.append(html[cursor:])
    return "".join(parts)


def email_body_text(email: dict[str, object]) -> str | None:
    """The email body as a person reads it: the editor's plain-text export when it is set, otherwise the HTML without
    style blocks, script blocks and tags.

    Three copies of this rule exist and must agree: this one, `_EMAIL_BODY_TEXT_SQL` in the workflows API, and
    `emailBodyText` in the frontend's `workflowSearchMatches.ts`.
    """
    text = _json_text(email.get("text"))
    if text:
        return text
    html = email.get("html")
    if not isinstance(html, str):
        return None
    html = _remove_blocks(html, _STYLE_OPEN, _STYLE_CLOSE)
    html = _remove_blocks(html, _SCRIPT_OPEN, _SCRIPT_CLOSE)
    return _remove_tags(html)


def _email_value(action: dict[str, object]) -> dict[str, object] | None:
    value: object = action
    for key in ("config", "inputs", "email", "value"):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def _step_texts(action: object, matched_in: StepSearchVersion) -> Iterator[StepSearchText]:
    if not isinstance(action, dict):
        return
    action_id = str(action.get("id") or "")
    name = _json_text(action.get("name"))
    if name is not None:
        yield StepSearchText(action_id=action_id, field=StepSearchField.STEP_NAME, matched_in=matched_in, text=name)

    email = _email_value(action)
    if email is None:
        return
    for field in (StepSearchField.SUBJECT, StepSearchField.PREHEADER):
        value = _json_text(email.get(field.value))
        if value is not None:
            yield StepSearchText(action_id=action_id, field=field, matched_in=matched_in, text=value)
    body = email_body_text(email)
    if body is not None:
        yield StepSearchText(action_id=action_id, field=StepSearchField.BODY, matched_in=matched_in, text=body)


def _action_list(value: object) -> list[object]:
    # `actions` defaults to {} on a workflow that never got a graph, and a draft may carry no actions.
    return value if isinstance(value, list) else []


def iter_step_search_texts(actions: object, draft: object) -> Iterator[StepSearchText]:
    for action in _action_list(actions):
        yield from _step_texts(action, StepSearchVersion.LIVE)
    draft_actions = draft.get("actions") if isinstance(draft, dict) else None
    for action in _action_list(draft_actions):
        yield from _step_texts(action, StepSearchVersion.DRAFT)


def build_search_text(*, name: str | None, description: str | None, actions: object, draft: object) -> str:
    values = [name or "", description or ""]
    values.extend(step.text for step in iter_step_search_texts(actions, draft))
    # A draft is a full copy of the live content, so most of its values repeat one that is already present.
    return SEARCH_TEXT_SEPARATOR.join(dict.fromkeys(value for value in values if value))


def _excerpt(text: str, regex: re2._Regexp, max_chars: int) -> str:
    if max_chars == 0:
        return ""
    match = regex.search(text)
    if match is None:
        return " ".join(text.split())[:max_chars]
    # Find the match before collapsing whitespace: the term can hold a literal tab or no-break space.
    before = _WHITESPACE.sub(" ", text[: match.start()]).lstrip()
    matched = _WHITESPACE.sub(" ", match.group())
    collapsed = before + matched + _WHITESPACE.sub(" ", text[match.end() :]).rstrip()
    match_start, match_end = len(before), len(before) + len(matched)
    padding = max(0, (max_chars - len(matched)) // 2)
    start = max(0, match_start - padding)
    end = min(len(collapsed), match_end + padding, start + max_chars)
    # Snap to word boundaries so the excerpt does not open or close in the middle of a word.
    first_space = collapsed.find(" ", start, match_start)
    if start > 0 and first_space != -1:
        start = first_space + 1
    last_space = collapsed.rfind(" ", match_end + 1, end)
    if end < len(collapsed) and last_space != -1:
        end = last_space
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(collapsed) else ""
    return f"{prefix}{collapsed[start:end]}{suffix}"


def find_step_matches(
    actions: object, draft: object, regex: re2._Regexp, *, max_steps: int, excerpt_chars: int
) -> StepMatches:
    """A staged step is listed only when its live version did not match, so each step appears once, with the text a
    person most likely looks at."""
    first_match: dict[str, StepSearchText] = {}
    for step in iter_step_search_texts(actions, draft):
        if step.action_id not in first_match and regex.search(step.text) is not None:
            first_match[step.action_id] = step
    steps = [
        StepSearchMatch(
            action_id=step.action_id,
            field=step.field,
            matched_in=step.matched_in,
            excerpt=_excerpt(step.text, regex, excerpt_chars),
        )
        for step in list(first_match.values())[:max_steps]
    ]
    return StepMatches(count=len(first_match), steps=steps)


def matched_metadata_fields(
    name: str | None, description: str | None, regex: re2._Regexp
) -> list[WorkflowMetadataField]:
    values = ((WorkflowMetadataField.NAME, name), (WorkflowMetadataField.DESCRIPTION, description))
    return [field for field, value in values if value and regex.search(value) is not None]
