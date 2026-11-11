from collections.abc import Callable

from posthog.dataclasses import frozen

_GITHUB_PREFIX = "https://github.com/"
_PATH_PUNCTUATION = frozenset(".-")
_ISO_DATE_LENGTH = 10
_ISO_DATE_DASHES = (4, 7)


@frozen
class GitHubLink:
    start: int
    end: int
    kind: str
    number: str


def is_word_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")


def is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def digits_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and is_digit(text[end]):
        end += 1
    return end


def _path_part_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and (is_word_char(text[end]) or text[end] in _PATH_PUNCTUATION):
        end += 1
    return end


def _github_link_at(text: str, start: int) -> GitHubLink | None:
    owner_start = start + len(_GITHUB_PREFIX)
    owner_end = _path_part_end(text, owner_start)
    if owner_end == owner_start or not text.startswith("/", owner_end):
        return None
    repo_end = _path_part_end(text, owner_end + 1)
    if repo_end == owner_end + 1:
        return None
    for kind in ("pull", "issues"):
        marker = f"/{kind}/"
        number_start = repo_end + len(marker)
        number_end = digits_end(text, number_start)
        if text.startswith(marker, repo_end) and number_end > number_start:
            return GitHubLink(start=start, end=number_end, kind=kind, number=text[number_start:number_end])
    return None


def github_links(text: str, accept: Callable[[GitHubLink], bool] = lambda link: True) -> list[GitHubLink]:
    links: list[GitHubLink] = []
    index = text.find(_GITHUB_PREFIX)
    while index >= 0:
        link = _github_link_at(text, index)
        if link is not None and accept(link):
            links.append(link)
            index = text.find(_GITHUB_PREFIX, link.end)
        else:
            index = text.find(_GITHUB_PREFIX, index + 1)
    return links


def _is_iso_date(candidate: str) -> bool:
    return len(candidate) == _ISO_DATE_LENGTH and all(
        char == "-" if index in _ISO_DATE_DASHES else is_digit(char) for index, char in enumerate(candidate)
    )


def _word_boundary(text: str, index: int) -> bool:
    before = text[index - 1] if index > 0 else ""
    after = text[index] if index < len(text) else ""
    return is_word_char(before) != is_word_char(after)


def replace_iso_dates(text: str, replacement: Callable[[int, int, int, str], str]) -> str:
    parts: list[str] = []
    last = 0
    index = 0
    while index + _ISO_DATE_LENGTH <= len(text):
        end = index + _ISO_DATE_LENGTH
        candidate = text[index:end]
        if _is_iso_date(candidate) and _word_boundary(text, index) and _word_boundary(text, end):
            parts.append(text[last:index])
            parts.append(replacement(int(candidate[:4]), int(candidate[5:7]), int(candidate[8:]), candidate))
            last = end
            index = end
        else:
            index += 1
    parts.append(text[last:])
    return "".join(parts)


def colon_duration_seconds(value: str) -> float | None:
    units = value.split(":")
    if not all(1 <= len(unit) <= 2 and all(is_digit(char) for char in unit) for unit in units):
        return None
    scales = (1, 60, 3600, 86400, 604800)
    return float(sum(int(unit) * scale for unit, scale in zip(reversed(units), scales)))


def collapsed_whitespace(text: str) -> str:
    return " ".join(text.split())


def utf16_offset(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2
