from datetime import date, timedelta

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .formats import GitHubLink, collapsed_whitespace, github_links, is_word_char, replace_iso_dates

MARKDOWN = MarkdownIt("commonmark")
_TEXT_TOKENS = frozenset({"text", "code_inline", "html_inline"})
_BREAK_TOKENS = frozenset({"softbreak", "hardbreak"})
_LINK_OPENERS = frozenset("(<[")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def readable_date(year: int, month: int, day: int, original: str) -> str:
    if year < 1 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return original
    shown = date(year, month, 1) + timedelta(days=day - 1)
    return f"{shown.day} {MONTHS[shown.month - 1]}"


def _is_bare_link(text: str, link: GitHubLink) -> bool:
    opened = link.start > 0 and text[link.start - 1] in _LINK_OPENERS
    following = text[link.end] if link.end < len(text) else ""
    return not opened and not is_word_char(following) and following != "/"


def _shortened_github_links(markdown: str) -> str:
    parts: list[str] = []
    last = 0
    for link in github_links(markdown, lambda link: _is_bare_link(markdown, link)):
        url = markdown[link.start : link.end]
        parts.extend((markdown[last : link.start], f"[#{link.number}]({url})"))
        last = link.end
    parts.append(markdown[last:])
    return "".join(parts)


def _token_text(token: Token) -> str:
    if token.type in _TEXT_TOKENS:
        return token.content
    if token.type in _BREAK_TOKENS:
        return " "
    return "".join(_token_text(child) for child in token.children or [])


def rendered_text(markdown: str) -> str:
    text = replace_iso_dates(collapsed_whitespace(_shortened_github_links(markdown)), readable_date)
    return "".join(_token_text(token) for token in MARKDOWN.parseInline(text))
