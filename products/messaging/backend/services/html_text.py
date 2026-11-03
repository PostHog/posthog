import re

from bs4 import BeautifulSoup, NavigableString, Tag

from posthog.dataclasses import frozen

PARAGRAPH_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre", "hr"})
LINE_TAGS = frozenset({"div", "li", "tr", "section", "article", "header", "footer", "dd", "dt"})
HIDDEN_TAGS = frozenset({"head", "title", "style", "script", "template"})
LINK_SCHEMES = ("http://", "https://", "mailto:")
BLANK_LINES = re.compile(r"\n{3,}")
WHITESPACE = re.compile(r"\s+")
# Ends a line block. It becomes a line break unless a line break already sits next to it.
LINE_END = "\x00"
LINE_ENDS = re.compile(r"\n?\x00+\n?")


def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html.replace(LINE_END, ""), "html.parser")
    text = LINE_ENDS.sub(_line_break, "".join(_text_parts(soup)))
    lines = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", lines).strip()


def _line_break(match: re.Match[str]) -> str:
    return match.group(0).replace(LINE_END, "") or "\n"


@frozen
class _LinkEnd:
    href: str
    label_start: int


class _TextParts:
    def __init__(self) -> None:
        self.parts: list[str] = []
        # The stripped text of every string in document order, so that a link compares its label to its address
        # with one slice and does not walk its subtree again. A walk per link is quadratic for nested links.
        self.label_text: list[str] = []
        self.label_length = 0

    def add_text(self, text: NavigableString) -> None:
        self.parts.append(WHITESPACE.sub(" ", text))
        if stripped := text.strip():
            self.label_text.append(stripped)
            self.label_length += len(stripped)

    def end_link(self, link: _LinkEnd) -> None:
        if not self._label_is(link):
            self.parts.append(f" ({link.href})")

    def _label_is(self, link: _LinkEnd) -> bool:
        if self.label_length - link.label_start != len(link.href):
            return False
        label: list[str] = []
        length = 0
        for text in reversed(self.label_text):
            if length >= len(link.href):
                break
            label.append(text)
            length += len(text)
        return "".join(reversed(label))[length - len(link.href) :] == link.href


def _text_parts(soup: BeautifulSoup) -> list[str]:
    text = _TextParts()
    stack: list[Tag | NavigableString | str | _LinkEnd] = [soup]
    while stack:
        item = stack.pop()
        if isinstance(item, Tag):
            stack.extend(reversed(_expand(item, text.label_length)))
        elif isinstance(item, _LinkEnd):
            text.end_link(item)
        elif type(item) is NavigableString:
            text.add_text(item)
        elif type(item) is str:
            text.parts.append(item)
    return text.parts


def _expand(tag: Tag, label_length: int) -> list[Tag | NavigableString | str | _LinkEnd]:
    if tag.name in HIDDEN_TAGS:
        return []
    if tag.name == "br":
        return ["\n"]
    children: list[Tag | NavigableString | str | _LinkEnd] = list(tag.children)
    href = tag.get("href")
    if tag.name == "a" and isinstance(href, str) and href.startswith(LINK_SCHEMES):
        children.append(_LinkEnd(href=href, label_start=label_length))
    elif tag.name in ("td", "th"):
        children.append(" ")
    if tag.name in PARAGRAPH_TAGS:
        return ["\n\n", *children, "\n\n"]
    if tag.name in LINE_TAGS:
        return ["\n", *children, LINE_END]
    return children
