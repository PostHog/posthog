from datetime import date

from markdown_it import MarkdownIt
from markdown_it.token import Token

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


def _shortened_github_links(text: str) -> str:
    parts: list[str] = []
    last = 0
    for link in github_links(text, lambda link: _is_bare_link(text, link)):
        parts.extend((text[last : link.start], f"#{link.number}"))
        last = link.end
    parts.append(text[last:])
    return "".join(parts)


def _prose_text(text: str, in_link: bool) -> str:
    return replace_iso_dates(text if in_link else _shortened_github_links(text), readable_date)


def _inline_text(tokens: list[Token]) -> str:
    parts: list[str] = []
    link_depth = 0
    for token in tokens:
        if token.type == "link_open":
            link_depth += 1
        elif token.type == "link_close":
            link_depth -= 1
        elif token.type == "text":
            parts.append(_prose_text(token.content, link_depth > 0))
        elif token.type in _RAW_TOKENS:
            parts.append(token.content)
        elif token.type in _BREAK_TOKENS:
            parts.append(" ")
        elif token.type == "image":
            parts.append("".join(child.content for child in token.children or [] if child.type in _ALT_TOKENS))
    return "".join(parts)


def rendered_text(markdown: str) -> str:
    """The text a reader sees. Dates and bare GitHub links change only in prose, never in code or link targets."""
    tokens: list[Token] = MARKDOWN.parseInline(collapsed_whitespace(markdown))
    return "".join(_inline_text(token.children or []) for token in tokens)
