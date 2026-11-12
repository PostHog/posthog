import re
from collections import Counter
from html.parser import HTMLParser

from posthog.dataclasses import frozen

PARAGRAPH_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre", "hr"})
LINE_TAGS = frozenset({"div", "li", "tr", "section", "article", "header", "footer", "dd", "dt"})
HIDDEN_TAGS = frozenset({"head", "title", "style", "script", "template"})
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "basefont",
        "bgsound",
        "br",
        "col",
        "command",
        "embed",
        "frame",
        "hr",
        "image",
        "img",
        "input",
        "isindex",
        "keygen",
        "link",
        "menuitem",
        "meta",
        "nextid",
        "param",
        "source",
        "spacer",
        "track",
        "wbr",
    }
)
LINK_SCHEMES = ("http://", "https://", "mailto:")
UNSUBSCRIBE_PLACEHOLDER = re.compile(r"\{\{\s*unsubscribe_url\s*\}\}", re.ASCII)
BLANK_LINES = re.compile(r"\n{3,}")
WHITESPACE = re.compile(r"\s+")
LINE_END = "\x00"
LINE_ENDS = re.compile(r"\n?\x00+\n?")


def text_from_html(html: str, *, keep_unsubscribe_link: bool = False) -> str:
    parser = _TextParser(keep_unsubscribe_link=keep_unsubscribe_link)
    parser.feed(html.replace(LINE_END, ""))
    parser.close()
    text = LINE_ENDS.sub(_line_break, "".join(parser.parts))
    lines = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", lines).strip()


def _line_break(match: re.Match[str]) -> str:
    return match.group(0).replace(LINE_END, "") or "\n"


@frozen
class _OpenLink:
    depth: int
    href: str
    label_start: int


class _TextParser(HTMLParser):
    def __init__(self, *, keep_unsubscribe_link: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.keep_unsubscribe_link = keep_unsubscribe_link
        self.parts: list[str] = []
        self.open_tags: list[str] = []
        self.open_counts: Counter[str] = Counter()
        self.open_links: list[_OpenLink] = []
        self.hidden_from: int | None = None
        self.label_text: list[str] = []
        self.label_length = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            self.handle_startendtag(tag, attrs)
            return
        self._start(tag, attrs)
        self._push(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs)
        self._push(tag)
        self._end_last()

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS or not self.open_counts[tag]:
            return
        while self.open_tags[-1] != tag:
            self._end_last()
        self._end_last()

    def handle_data(self, data: str) -> None:
        if self.hidden_from is not None:
            return
        self.parts.append(WHITESPACE.sub(" ", data))
        if stripped := data.strip():
            self.label_text.append(stripped)
            self.label_length += len(stripped)

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self._end_last()

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.hidden_from is not None:
            return
        if tag in HIDDEN_TAGS:
            self.hidden_from = len(self.open_tags)
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag in PARAGRAPH_TAGS:
            self.parts.append("\n\n")
        elif tag in LINE_TAGS:
            self.parts.append("\n")
        href = dict(attrs).get("href") if tag == "a" else None
        if href is not None and (href.startswith(LINK_SCHEMES) or self._is_unsubscribe_link(href)):
            self.open_links.append(_OpenLink(depth=len(self.open_tags), href=href, label_start=self.label_length))

    def _is_unsubscribe_link(self, href: str) -> bool:
        return self.keep_unsubscribe_link and UNSUBSCRIBE_PLACEHOLDER.fullmatch(href.strip()) is not None

    def _push(self, tag: str) -> None:
        self.open_tags.append(tag)
        self.open_counts[tag] += 1

    def _end_last(self) -> None:
        tag = self.open_tags.pop()
        self.open_counts[tag] -= 1
        depth = len(self.open_tags)
        if self.hidden_from is not None:
            if depth == self.hidden_from:
                self.hidden_from = None
            return
        if self.open_links and self.open_links[-1].depth == depth:
            link = self.open_links.pop()
            if not self._label_is(link):
                self.parts.append(f" ({link.href})")
        elif tag in ("td", "th"):
            self.parts.append(" ")
        if tag in PARAGRAPH_TAGS:
            self.parts.append("\n\n")
        elif tag in LINE_TAGS:
            self.parts.append(LINE_END)

    def _label_is(self, link: _OpenLink) -> bool:
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
