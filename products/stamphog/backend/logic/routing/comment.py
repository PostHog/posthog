"""The pull request comment that names the owners the cut step removed, and why."""

from __future__ import annotations

import re

from owners_yaml import owner_handle

from products.stamphog.backend.logic.routing.cut import RoutingDecision
from products.stamphog.backend.logic.scrubbing import neutralize_active_markdown

ROUTING_COMMENT_MARKER = "<!-- stamphog-reviewer-routing -->"

_REASON_MAX_CHARS = 200
_CODE_SPAN_BREAKERS_RE = re.compile(r"[`\x00-\x1f\x7f]")
# Backslash-escaped ASCII punctuation is literal in CommonMark, so a reason cannot open a link,
# an image, an HTML tag, a table cell or emphasis. Block markers such as `#` or `-` need no escape,
# because the reason never starts a line.
_MARKDOWN_PUNCTUATION_RE = re.compile(r"([\\*_\[\]<>!|~])")


def sanitize_for_code_span(text: str) -> str:
    # A backtick or a line break would end the code span and let the text write live markdown and
    # mentions into a comment that the app posts.
    return _CODE_SPAN_BREAKERS_RE.sub("?", text)


def _plain_reason(reason: str) -> str:
    # The model reads untrusted pull request content, so its reason is untrusted too. Joining on
    # whitespace removes every line break, which keeps the reason inside its list item.
    text = " ".join(reason.split())
    text = _CODE_SPAN_BREAKERS_RE.sub("", text)
    if len(text) > _REASON_MAX_CHARS:
        text = text[: _REASON_MAX_CHARS - 3].rstrip() + "..."
    text = neutralize_active_markdown(text)
    text = _MARKDOWN_PUNCTUATION_RE.sub(r"\\\1", text)
    # A zero-width space after `@` stops GitHub from turning the text into a mention.
    return text.replace("@", "@​")


def render_routing_comment(*, decision: RoutingDecision, org: str) -> str | None:
    """The comment body, or None when no owner was cut."""
    if not decision.cut:
        return None
    lines = [
        ROUTING_COMMENT_MARKER,
        "Review requests went to the owners of the changed code. "
        "These owners were not requested because their part of this change looks trivial:",
        "",
    ]
    for cut in decision.cut:
        handle = sanitize_for_code_span(owner_handle(cut.candidate.owner, org))
        lines.append(f"- `{handle}`: {_plain_reason(cut.reason)}")
    lines += ["", "If you were listed here and want to review, you can still assign yourself as a reviewer."]
    return "\n".join(lines)


def render_approved_routing_comment() -> str:
    """The comment for a head that stamphog approved, when owners of sensitive or new paths were requested."""
    return "\n".join(
        [
            ROUTING_COMMENT_MARKER,
            "Stamphog approved this pull request, so review requests went only to the owners of "
            "sensitive or new paths. The other owners of the changed code were not requested.",
        ]
    )
