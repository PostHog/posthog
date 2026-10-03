import re
from datetime import date, timedelta

_BARE_GITHUB_LINK = re.compile(
    r"(?<![(<\[])https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/(\d+)(?![\w/])", re.ASCII
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b", re.ASCII)
_INLINE_MARKDOWN = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")
_WHITESPACE = re.compile(r"\s+")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _readable_date(match: re.Match[str]) -> str:
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return match.group(0)
    shown = date(year, month, 1) + timedelta(days=day - 1)
    return f"{shown.day} {_MONTHS[shown.month - 1]}"


def _shortened_github_links(markdown: str) -> str:
    return _BARE_GITHUB_LINK.sub(lambda match: f"[#{match.group(1)}]({match.group(0)})", markdown)


def rendered_text(markdown: str) -> str:
    text = _ISO_DATE.sub(_readable_date, _WHITESPACE.sub(" ", _shortened_github_links(markdown)).strip())
    parts: list[str] = []
    last = 0
    for match in _INLINE_MARKDOWN.finditer(text):
        parts.append(text[last : match.start()])
        if match.group(1) is not None:
            parts.append(match.group(1))
        elif match.group(2) is not None:
            parts.append(rendered_text(match.group(2)))
        else:
            parts.append(match.group(3))
        last = match.end()
    parts.append(text[last:])
    return "".join(parts)
