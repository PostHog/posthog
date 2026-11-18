from datetime import date

from markdown_it import MarkdownIt
from markdown_it.token import Token

from posthog.dataclasses import frozen

from .formats import GitHubLink, collapsed_whitespace, github_links, is_word_char, replace_iso_dates

MARKDOWN = MarkdownIt("commonmark")
_RAW_TOKENS = frozenset({"code_inline", "html_inline"})
_ALT_TOKENS = _RAW_TOKENS | {"text"}
_BREAK_TOKENS = frozenset({"softbreak", "hardbreak"})
_LINK_OPENERS = frozenset("(<[")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def readable_date(year: int, month: int, day: int, original: str) -> str:
    try:
        shown = date(year, month, day)
    except ValueError:
        return original
    return f"{shown.day} {MONTHS[shown.month - 1]}"


def _is_bare_link(text: str, link: GitHubLink) -> bool:
    opened = link.start > 0 and text[link.start - 1] in _LINK_OPENERS
    following = text[link.end] if link.end < len(text) else ""
    return not opened and not is_word_char(following) and following != "/"


@frozen
class _Part:
    text: str
    prose: bool


def _dated(text: str) -> str:
    return replace_iso_dates(text, readable_date)


def _prose_parts(text: str) -> list[_Part]:
    parts: list[_Part] = []
    last = 0
    for link in github_links(text, lambda link: _is_bare_link(text, link)):
        parts.extend(
            (_Part(text=_dated(text[last : link.start]), prose=True), _Part(text=f"#{link.number}", prose=False))
        )
        last = link.end
    parts.append(_Part(text=_dated(text[last:]), prose=True))
    return parts


def _inline_parts(tokens: list[Token]) -> list[_Part]:
    parts: list[_Part] = []
    link_depth = 0
    for token in tokens:
        if token.type == "link_open":
            link_depth += 1
        elif token.type == "link_close":
            link_depth -= 1
        elif token.type == "text" and link_depth:
            parts.append(_Part(text=_dated(token.content), prose=False))
        elif token.type == "text":
            parts.extend(_prose_parts(token.content))
        elif token.type in _RAW_TOKENS:
            parts.append(_Part(text=token.content, prose=False))
        elif token.type in _BREAK_TOKENS:
            parts.append(_Part(text=" ", prose=True))
        elif token.type == "image":
            alt = "".join(child.content for child in token.children or [] if child.type in _ALT_TOKENS)
            parts.append(_Part(text=alt, prose=False))
    return parts


def _rendered_parts(markdown: str) -> list[_Part]:
    tokens: list[Token] = MARKDOWN.parseInline(collapsed_whitespace(markdown))
    return [part for token in tokens for part in _inline_parts(token.children or [])]


def rendered_text(markdown: str) -> str:
    """The text a reader sees. Dates and bare GitHub links change only in prose, never in code or link targets."""
    return "".join(part.text for part in _rendered_parts(markdown))


def rendered_prose(markdown: str) -> str:
    """`rendered_text` with code, links and images blanked, so offsets still match it."""
    return "".join(part.text if part.prose else " " * len(part.text) for part in _rendered_parts(markdown))
