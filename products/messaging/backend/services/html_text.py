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
# Matches ECMAScript \s so Django and CDP agree on {{ unsubscribe_url }}.
_JS_WHITESPACE = r"[\t\n\v\f\r \u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]"
_C0_AND_SPACE = "".join(chr(code) for code in range(0x21))
UNSUBSCRIBE_HREF = "{{ unsubscribe_url }}"
UNSUBSCRIBE_PLACEHOLDER = re.compile(rf"\{{\{{{_JS_WHITESPACE}*unsubscribe_url{_JS_WHITESPACE}*\}}\}}")
_EMITTED_UNSUBSCRIBE_PLACEHOLDER = re.compile(r"\{\{ ?unsubscribe_url ?\}\}")
# Leading C0 controls/space match WHATWG URL trimming used by CDP's link check.
_UNSUBSCRIBE_HREF_PREFIX = re.compile(rf"[\x00-\x20]*\{{\{{{_JS_WHITESPACE}*unsubscribe_url{_JS_WHITESPACE}*\}}\}}")
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
    emitted_start: int = 0


class _TextParser(HTMLParser):
    def __init__(self, *, keep_unsubscribe_link: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.keep_unsubscribe_link = keep_unsubscribe_link
        self.parts: list[str] = []
        self.emitted_text: list[str] = []
        self.emitted_length = 0
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
        self._append_part(WHITESPACE.sub(" ", data))
        if stripped := data.strip():
            self.label_text.append(stripped)
            self.label_length += len(stripped)

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self._end_last()

    def _append_part(self, text: str) -> None:
        self.parts.append(text)
        if not self.keep_unsubscribe_link:
            return
        if text == LINE_END:
            text = "\n"
        elif text.startswith(" ") and self.emitted_text and self.emitted_text[-1].endswith(" "):
            text = text[1:]
        if text:
            self.emitted_text.append(text)
            self.emitted_length += len(text)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.hidden_from is not None:
            return
        if tag in HIDDEN_TAGS:
            self.hidden_from = len(self.open_tags)
            return
        if tag == "br":
            self._append_part("\n")
        elif tag in PARAGRAPH_TAGS:
            self._append_part("\n\n")
        elif tag in LINE_TAGS:
            self._append_part("\n")
        href = dict(attrs).get("href") if tag == "a" else None
        if href is not None:
            if href.startswith(LINK_SCHEMES):
                self.open_links.append(_OpenLink(depth=len(self.open_tags), href=href, label_start=self.label_length))
            elif self._is_unsubscribe_link(href):
                self.open_links.append(
                    _OpenLink(
                        depth=len(self.open_tags),
                        href=UNSUBSCRIBE_HREF,
                        label_start=self.label_length,
                        emitted_start=self.emitted_length,
                    )
                )

    def _is_unsubscribe_link(self, href: str) -> bool:
        if not self.keep_unsubscribe_link:
            return False
        match = _UNSUBSCRIBE_HREF_PREFIX.match(href)
        if match is None:
            return False
        rest = href[match.end() :]
        return not rest.strip(_C0_AND_SPACE) or rest.lstrip("\t\n\r").startswith(("?", "#"))

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
                self._append_part(f" ({link.href})")
        elif tag in ("td", "th"):
            self._append_part(" ")
        if tag in PARAGRAPH_TAGS:
            self._append_part("\n\n")
        elif tag in LINE_TAGS:
            self._append_part(LINE_END)

    def _label_is(self, link: _OpenLink) -> bool:
        if link.href == UNSUBSCRIBE_HREF:
            span = self.emitted_length - link.emitted_start
            if not (len("{{unsubscribe_url}}") <= span <= len(UNSUBSCRIBE_HREF) + 2):
                return False
            emitted = self._suffix(self.emitted_text, span).strip(" ")
            return _EMITTED_UNSUBSCRIBE_PLACEHOLDER.fullmatch(emitted) is not None
        span = self.label_length - link.label_start
        if span != len(link.href):
            return False
        return self._suffix(self.label_text, span) == link.href

    def _suffix(self, chunks: list[str], span: int) -> str:
        label: list[str] = []
        length = 0
        for text in reversed(chunks):
            if length >= span:
                break
            label.append(text)
            length += len(text)
        return "".join(reversed(label))[length - span :]
