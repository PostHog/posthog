import re

from bs4 import BeautifulSoup, NavigableString, Tag

PARAGRAPH_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "pre", "hr"})
LINE_TAGS = frozenset({"div", "li", "tr", "section", "article", "header", "footer", "dd", "dt"})
HIDDEN_TAGS = frozenset({"head", "title", "style", "script", "template"})
LINK_SCHEMES = ("http://", "https://", "mailto:", "{{")
BLANK_LINES = re.compile(r"\n{3,}")
WHITESPACE = re.compile(r"\s+")


def text_from_html(html: str) -> str:
    text = "".join(_text_parts(BeautifulSoup(html, "html.parser")))
    lines = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", lines).strip()


def _text_parts(soup: BeautifulSoup) -> list[str]:
    parts: list[str] = []
    stack: list[Tag | NavigableString | str] = [soup]
    while stack:
        item = stack.pop()
        if isinstance(item, Tag):
            stack.extend(reversed(_expand(item)))
        elif type(item) is NavigableString:
            parts.append(WHITESPACE.sub(" ", item))
        elif type(item) is str:
            parts.append(item)
    return parts


def _expand(tag: Tag) -> list[Tag | NavigableString | str]:
    if tag.name in HIDDEN_TAGS:
        return []
    if tag.name == "br":
        return ["\n"]
    children: list[Tag | NavigableString | str] = list(tag.children)
    if tag.name == "a":
        children.extend(_link_address(tag))
    elif tag.name in ("td", "th"):
        children.append(" ")
    if tag.name in PARAGRAPH_TAGS:
        return ["\n\n", *children, "\n\n"]
    if tag.name in LINE_TAGS:
        return ["\n", *children]
    return children


def _link_address(link: Tag) -> list[str]:
    href = link.get("href")
    if not isinstance(href, str) or not href.startswith(LINK_SCHEMES) or href == link.get_text(strip=True):
        return []
    return [f" ({href})"]
