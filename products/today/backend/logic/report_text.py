import re
from datetime import date, timedelta

from markdown_it import MarkdownIt
from markdown_it.token import Token

_BARE_GITHUB_LINK = re.compile(
    r"(?<![(<\[])https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/(\d+)(?![\w/])", re.ASCII
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b", re.ASCII)
_MARKDOWN = MarkdownIt("commonmark")
_TEXT_TOKENS = frozenset({"text", "code_inline", "html_inline"})
_BREAK_TOKENS = frozenset({"softbreak", "hardbreak"})
_WHITESPACE = re.compile(r"\s+")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def readable_date(match: re.Match[str]) -> str:
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return match.group(0)
    shown = date(year, month, 1) + timedelta(days=day - 1)
    return f"{shown.day} {_MONTHS[shown.month - 1]}"


def _shortened_github_links(markdown: str) -> str:
    return _BARE_GITHUB_LINK.sub(lambda match: f"[#{match.group(1)}]({match.group(0)})", markdown)


def _token_text(token: Token) -> str:
    if token.type in _TEXT_TOKENS:
        return token.content
    if token.type in _BREAK_TOKENS:
        return " "
    return "".join(_token_text(child) for child in token.children or [])


def rendered_text(markdown: str) -> str:
    text = _ISO_DATE.sub(readable_date, _WHITESPACE.sub(" ", _shortened_github_links(markdown)).strip())
    return "".join(_token_text(token) for token in _MARKDOWN.parseInline(text))
