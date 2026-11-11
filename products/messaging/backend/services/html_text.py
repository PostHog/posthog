import re
from collections import Counter
from html.parser import HTMLParser
from uuid import uuid4

from posthog.dataclasses import frozen

PARAGRAPH_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre", "hr"})
LINE_TAGS = frozenset({"div", "li", "tr", "section", "article", "header", "footer", "dd", "dt"})
HIDDEN_TAGS = frozenset({"head", "title", "style", "script", "template"})
RAW_TEXT_TAGS = frozenset({"script", "style", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"})
ESCAPABLE_RAW_TEXT_TAGS = frozenset({"textarea", "title"})
READABLE_AFTER_CLOSING_WITH_ONLY = {
    "svg": frozenset(
        {
            "svg",
            "g",
            "path",
            "circle",
            "ellipse",
            "line",
            "polyline",
            "polygon",
            "rect",
            "defs",
            "use",
            "symbol",
            "lineargradient",
            "radialgradient",
            "stop",
            "clippath",
            "mask",
            "pattern",
            "text",
            "tspan",
        }
    ),
    "math": frozenset(),
    "select": frozenset({"option", "optgroup"}),
}
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
JAVASCRIPT_WHITESPACE = r"[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
TEXT_WORDS = re.compile(rf"{JAVASCRIPT_WHITESPACE}+")
TEXT_LINK_START = re.compile(r"[hH][tT][tT][pP][sS]?://|[wW]{3}\.")
TEXT_LINK_END_PUNCTUATION = ".,;:!?'\")]}>*"
UNSUBSCRIBE_PLACEHOLDER = re.compile(rf"\{{\{{{JAVASCRIPT_WHITESPACE}*unsubscribe_url{JAVASCRIPT_WHITESPACE}*\}}\}}")
BLANK_LINES = re.compile(r"\n{3,}")
WHITESPACE = re.compile(r"\s+")
LINE_END = "\x00"
LINE_ENDS = re.compile(r"\n?\x00+\n?")
URL_PARSER_TRIMS = "".join(chr(code) for code in range(0x21))
SCRIPT_ESCAPE_START = re.compile(r"<!--(?!-*>)")
SCRIPT_ESCAPE_TOKENS = re.compile(r"-->|<script[\t\n\f\r />]", re.IGNORECASE)


def has_unsubscribe_link(html: str, text: str) -> bool:
    link = f"unsubscribe-link-{uuid4().hex}"
    if not html:
        url = f"https://{link}.invalid/"
        return "" in _text_links_to(UNSUBSCRIBE_PLACEHOLDER.sub(url, text), url)
    parser = _TextParser(keep_unsubscribe_link=False, reads_like_a_browser=True)
    parser.feed(UNSUBSCRIBE_PLACEHOLDER.sub(link, html))
    parser.close()
    return not parser.has_frames and link in parser.visible_hrefs


def _text_links_to(text: str, base: str) -> list[str]:
    links = (word[start.start() :] for word in TEXT_WORDS.split(text) if (start := TEXT_LINK_START.search(word)))
    return [link[len(base) :].rstrip(TEXT_LINK_END_PUNCTUATION) for link in links if link.startswith(base)]


def _script_stays_open_at_its_end_tag(script: str) -> bool:
    position = 0
    while (escape := SCRIPT_ESCAPE_START.search(script, position)) is not None:
        position = escape.end()
        double_escaped = False
        while (token := SCRIPT_ESCAPE_TOKENS.search(script, position)) is not None:
            position = token.end()
            if token.group() == "-->":
                break
            double_escaped = True
        else:
            return double_escaped
    return False


def text_from_html(html: str, *, keep_unsubscribe_link: bool = False) -> str:
    parser = _TextParser(keep_unsubscribe_link=keep_unsubscribe_link)
    parser.feed(html.replace(LINE_END, ""))
    parser.close()
    text = LINE_ENDS.sub(_line_break, "".join(parser.parts))
    lines = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", lines).strip()


def _line_break(match: re.Match[str]) -> str:
    return match.group(0).replace(LINE_END, "") or "\n"


def _first_href(attrs: list[tuple[str, str | None]]) -> str | None:
    return next((value for name, value in attrs if name == "href"), None)


@frozen
class _OpenLink:
    depth: int
    href: str
    label_start: int


class _TextParser(HTMLParser):
    def __init__(self, *, keep_unsubscribe_link: bool, reads_like_a_browser: bool = False) -> None:
        super().__init__(convert_charrefs=True, scripting=reads_like_a_browser)
        if reads_like_a_browser:
            self._set_support_cdata(False)  # type: ignore[attr-defined]
        self.keep_unsubscribe_link = keep_unsubscribe_link
        self.reads_like_a_browser = reads_like_a_browser
        self.parts: list[str] = []
        self.open_tags: list[str] = []
        self.open_counts: Counter[str] = Counter()
        self.open_counts_above_templates: list[Counter[str]] = [Counter()]
        self.open_links: list[_OpenLink] = []
        self.hidden_from: int | None = None
        self.label_text: list[str] = []
        self.label_length = 0
        self.visible_hrefs: set[str] = set()
        self.has_frames = False
        self.unreadable = False
        self.unreadable_from: int | None = None
        self.unreadable_tag = ""
        self.closing = ""
        self.script: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            self.handle_startendtag(tag, attrs)
            return
        if tag == "body" and self.open_tags and self.open_tags[-1] == "head":
            self._end_last()
        self._start(tag, attrs)
        self._push(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.reads_like_a_browser and tag not in VOID_TAGS:
            self.handle_starttag(tag, attrs)
            self._read_content_as_text(tag)
            return
        self._start(tag, attrs)
        self._push(tag)
        self._end_last()

    def _read_content_as_text(self, tag: str) -> None:
        if tag in RAW_TEXT_TAGS:
            self.set_cdata_mode(tag)
        elif tag in ESCAPABLE_RAW_TEXT_TAGS:
            self.set_cdata_mode(tag, escapable=True)

    def handle_endtag(self, tag: str) -> None:
        if self.reads_like_a_browser and self.cdata_elem == "script":
            self.unreadable = self.unreadable or _script_stays_open_at_its_end_tag("".join(self.script))
            self.script = []
        if tag in VOID_TAGS or not self.open_counts[tag]:
            return
        if self.reads_like_a_browser and tag != "template" and not self.open_counts_above_templates[-1][tag]:
            return
        self.closing = tag
        while self.open_tags[-1] != tag:
            self._end_last()
        self._end_last()
        self.closing = ""

    def handle_data(self, data: str) -> None:
        if self.reads_like_a_browser and self.cdata_elem == "script":
            self.script.append(data)
        if self.hidden_from is not None:
            return
        self.parts.append(WHITESPACE.sub(" ", data))
        if stripped := data.strip():
            self.label_text.append(stripped)
            self.label_length += len(stripped)

    def handle_comment(self, data: str) -> None:
        self._read_markup_other_than_tags()

    def handle_decl(self, decl: str) -> None:
        self._read_markup_other_than_tags()

    def unknown_decl(self, data: str) -> None:
        self._read_markup_other_than_tags()

    def handle_pi(self, data: str) -> None:
        self._read_markup_other_than_tags()

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self._end_last()

    def _read_markup_other_than_tags(self) -> None:
        if self.unreadable_from is not None:
            self.unreadable = True

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "frameset" and len(self.open_counts_above_templates) == 1:
            self.has_frames = True
        if self.reads_like_a_browser:
            self._track_readability(tag)
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
        href = _first_href(attrs) if tag == "a" else None
        if href is not None and not self.unreadable:
            self.visible_hrefs.add(href.strip(URL_PARSER_TRIMS))
        if href is not None and (href.startswith(LINK_SCHEMES) or self._is_unsubscribe_link(href)):
            self.open_links.append(_OpenLink(depth=len(self.open_tags), href=href, label_start=self.label_length))

    def _is_unsubscribe_link(self, href: str) -> bool:
        return self.keep_unsubscribe_link and UNSUBSCRIBE_PLACEHOLDER.fullmatch(href.strip()) is not None

    def _track_readability(self, tag: str) -> None:
        if self.unreadable_from is None:
            if tag in READABLE_AFTER_CLOSING_WITH_ONLY:
                self.unreadable_from = len(self.open_tags)
                self.unreadable_tag = tag
        elif tag not in READABLE_AFTER_CLOSING_WITH_ONLY[self.unreadable_tag]:
            self.unreadable = True

    def _push(self, tag: str) -> None:
        self.open_tags.append(tag)
        self.open_counts[tag] += 1
        self.open_counts_above_templates[-1][tag] += 1
        if tag == "template":
            self.open_counts_above_templates.append(Counter())

    def _end_last(self) -> None:
        tag = self.open_tags.pop()
        self.open_counts[tag] -= 1
        if tag == "template":
            self.open_counts_above_templates.pop()
        self.open_counts_above_templates[-1][tag] -= 1
        depth = len(self.open_tags)
        if depth == self.unreadable_from:
            self.unreadable = self.unreadable or self.closing != self.unreadable_tag
            self.unreadable_from = None
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
