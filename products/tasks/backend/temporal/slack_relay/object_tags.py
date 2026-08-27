"""Rewrite agent object tags into markdown Slack can show.

Agents cite PostHog objects with XML-style tags (``<insight id="9pQx3">checkout funnel</insight>``,
``<hogql display="block" title="DAU">SELECT ...</hogql>``). The desktop and web task views parse
those into chips and chart cards; Slack has no renderer, so a raw tag reaches the thread as
escaped XML. This module runs before markdown conversion and turns each tag into the closest
thing Slack has: a link to the object, a fenced SQL block, or just the label.

The kind registry mirrors the desktop one (``products/desktop/packages/core/src/inbox/objectTags.ts``).
Keep the two in sync when a kind or path changes.
"""

import re
import html
from collections.abc import Callable
from urllib.parse import quote

from posthog.dataclasses import frozen

# Slack keeps a link's URL out of the message text limit, but the chat API rejects URLs past
# this size, and a SQL editor deep link carries the whole query in the query string.
_MAX_LINK_URL_LENGTH = 2000

# Bound the work done per message: a message is at most a few tens of KB, and the desktop
# renderer stops at a similar count.
_MAX_TAGS_PER_MESSAGE = 200

# Links we post ourselves carry this so PostHog's own unfurler leaves inline references alone;
# a block-display reference keeps unfurling on because the unfurl card is the nearest thing
# Slack has to the chart card the desktop renders.
_UNFURL_OPT_OUT_QUERY = "unfurl=false"

_RE_OPEN_TAG = re.compile(r"<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*\"[^\"]*\")*)\s*(/>|>)")
_RE_ATTR = re.compile(r"([a-z][\w-]*)\s*=\s*\"([^\"]*)\"")
_RE_CODE_SEGMENT = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)")
_RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,}$", re.IGNORECASE)
_RE_LABEL_UNSAFE = re.compile(r"[\[\]<>|]")
_RE_NUMERIC = re.compile(r"^\d+$")


@frozen
class _ObjectKind:
    label: str
    # Project-relative path for an id, or None when the id has no page of its own.
    web_path: Callable[[str], str | None]


def _plain_path(prefix: str) -> Callable[[str], str | None]:
    return lambda object_id: f"{prefix}/{quote(object_id, safe='')}"


def _flag_path(object_id: str) -> str | None:
    # Flag pages resolve by numeric id only; a flag cited by key has no direct page.
    return f"/feature_flags/{object_id}" if _RE_NUMERIC.match(object_id) else None


def _event_path(object_id: str) -> str | None:
    # Event definition pages resolve by uuid; an event cited by name has no direct page.
    return f"/data-management/events/{quote(object_id, safe='')}" if _RE_UUID.match(object_id) else None


def _sql_editor_path(sql: str) -> str | None:
    return f"/sql?open_query={quote(sql, safe='')}"


_HOGQL_KIND = _ObjectKind(label="SQL query", web_path=_sql_editor_path)

_OBJECT_KINDS: dict[str, _ObjectKind] = {
    "insight": _ObjectKind(label="Insight", web_path=_plain_path("/insights")),
    "hogql": _HOGQL_KIND,
    "dashboard": _ObjectKind(label="Dashboard", web_path=_plain_path("/dashboard")),
    "error": _ObjectKind(label="Error issue", web_path=_plain_path("/error_tracking")),
    "replay": _ObjectKind(label="Session replay", web_path=_plain_path("/replay")),
    "flag": _ObjectKind(label="Feature flag", web_path=_flag_path),
    "experiment": _ObjectKind(label="Experiment", web_path=_plain_path("/experiments")),
    "survey": _ObjectKind(label="Survey", web_path=_plain_path("/surveys")),
    "ticket": _ObjectKind(label="Support ticket", web_path=_plain_path("/support/tickets")),
    "trace": _ObjectKind(label="LLM trace", web_path=_plain_path("/ai-observability/traces")),
    "eval": _ObjectKind(label="Evaluation", web_path=_plain_path("/ai-evals/evaluations")),
    "event": _ObjectKind(label="Event", web_path=_event_path),
    "cohort": _ObjectKind(label="Cohort", web_path=_plain_path("/cohorts")),
    "action": _ObjectKind(label="Action", web_path=_plain_path("/data-management/actions")),
    "person": _ObjectKind(label="Person", web_path=_plain_path("/persons")),
}

_OBJECT_KIND_ALIASES: dict[str, str] = {
    "session-replay": "replay",
    "recording": "replay",
    "feature-flag": "flag",
    "feature_flag": "flag",
    "sql": "hogql",
}


@frozen
class _Tag:
    name: str
    attrs: dict[str, str]
    body: str
    start: int
    end: int


def _resolve_kind(name: str) -> _ObjectKind | None:
    return _OBJECT_KINDS.get(_OBJECT_KIND_ALIASES.get(name, name))


def _parse_attrs(raw: str) -> dict[str, str]:
    return {match.group(1): html.unescape(match.group(2)) for match in _RE_ATTR.finditer(raw)}


def _scan_tags(text: str) -> list[_Tag]:
    """Find complete tags in ``text`` in order, without overlaps.

    A tag whose closer never arrives is not a tag: the text stays as it was, which matches the
    desktop renderer leaving an unterminated tag alone.
    """
    tags: list[_Tag] = []
    position = 0
    while len(tags) < _MAX_TAGS_PER_MESSAGE:
        match = _RE_OPEN_TAG.search(text, position)
        if match is None:
            break
        name = match.group(1)
        attrs = _parse_attrs(match.group(2))
        open_end = match.end()
        if match.group(3) == "/>":
            tags.append(_Tag(name=name, attrs=attrs, body="", start=match.start(), end=open_end))
            position = open_end
            continue
        close = re.compile(rf"</{re.escape(name)}\s*>").search(text, open_end)
        if close is None:
            position = open_end
            continue
        tags.append(
            _Tag(name=name, attrs=attrs, body=text[open_end : close.start()], start=match.start(), end=close.end())
        )
        position = close.end()
    return tags


def _safe_label(label: str) -> str:
    # The label ends up inside a Slack ``<url|label>`` link, where ``|``, ``<`` and ``>`` end the
    # link early, and inside a markdown ``[label](url)`` on the way there, where brackets do.
    return " ".join(_RE_LABEL_UNSAFE.sub(" ", label).split())


def _link(label: str, url: str | None) -> str:
    if url is None or len(url) > _MAX_LINK_URL_LENGTH:
        return label
    return f"[{label}]({url})"


def _object_url(project_url: str, kind: _ObjectKind, object_id: str, *, unfurl: bool) -> str | None:
    path = kind.web_path(object_id)
    if path is None:
        return None
    if unfurl:
        return f"{project_url}{path}"
    separator = "&" if "?" in path else "?"
    return f"{project_url}{path}{separator}{_UNFURL_OPT_OUT_QUERY}"


def _render_hogql(tag: _Tag, project_url: str) -> str | None:
    sql = tag.body.strip()
    if not sql:
        return None
    url = _object_url(project_url, _HOGQL_KIND, sql, unfurl=False)
    if tag.attrs.get("display") != "block":
        label = _safe_label(tag.attrs.get("label") or tag.attrs.get("title") or "") or _HOGQL_KIND.label
        return _link(label, url)

    title = _safe_label(tag.attrs.get("title") or "") or _HOGQL_KIND.label
    # No language hint on the fence: Slack shows one as literal text inside the block.
    lines = [f"**{_link(title, url)}**", "```", sql, "```"]
    caption = " ".join((tag.attrs.get("caption") or "").split())
    if caption:
        lines.append(f"_{caption}_")
    return "\n".join(lines)


def _render_reference(tag: _Tag, kind: _ObjectKind, project_url: str) -> str | None:
    object_id = (tag.attrs.get("id") or "").strip()
    if not object_id:
        return None
    is_block = tag.attrs.get("display") == "block"
    label = _safe_label(tag.body) or f"{kind.label} {_safe_label(object_id)}"
    return _link(label, _object_url(project_url, kind, object_id, unfurl=is_block))


def _render_tag(tag: _Tag, project_url: str) -> str | None:
    kind = _resolve_kind(tag.name)
    if kind is None:
        # An agent sometimes extends the convention to a kind nobody renders (``<inbox id="…">``).
        # The label is still the useful part, so keep it and drop the markup.
        label = _safe_label(tag.body)
        return label if "id" in tag.attrs and label else None
    if kind is _HOGQL_KIND:
        return _render_hogql(tag, project_url)
    return _render_reference(tag, kind, project_url)


def _rewrite_segment(text: str, project_url: str) -> str:
    tags = _scan_tags(text)
    if not tags:
        return text
    output = ""
    position = 0
    needs_paragraph_break = False
    for tag in tags:
        rendered = _render_tag(tag, project_url)
        if rendered is None:
            continue
        before = text[position : tag.start]
        if needs_paragraph_break and before.strip():
            before = "\n\n" + before.lstrip("\n")
        needs_paragraph_break = False
        output += before
        if "\n" in rendered:
            # A fenced block only survives markdown conversion as its own paragraph.
            if output.strip() and not output.endswith("\n\n"):
                output = output.rstrip("\n") + "\n\n"
            needs_paragraph_break = True
        output += rendered
        position = tag.end
    rest = text[position:]
    if needs_paragraph_break and rest.strip():
        rest = "\n\n" + rest.lstrip("\n")
    return output + rest


def rewrite_object_tags_for_slack(text: str, *, project_url: str) -> str:
    """Replace agent object tags in ``text`` with markdown Slack can render.

    ``project_url`` is the absolute ``/project/<id>`` base every object link hangs off. Tags inside
    fenced code blocks and inline code spans stay literal, as they do in the desktop renderer.
    """
    if "<" not in text:
        return text
    base = project_url.rstrip("/")
    # ``split`` with one capture group alternates prose and code segments, starting with prose.
    segments = _RE_CODE_SEGMENT.split(text)
    return "".join(segment if index % 2 else _rewrite_segment(segment, base) for index, segment in enumerate(segments))
