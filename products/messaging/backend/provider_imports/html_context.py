"""Follows where text sits in an HTML email, the way a browser reads it, so a converter knows how a value there is
escaped."""

import re
from dataclasses import field

from posthog.dataclasses import frozen


@frozen
class Place:
    state: str
    attribute: str = ""
    tag_name: str = ""
    closing: bool = False
    raw_element: str = ""
    partial: str = ""
    # Text fed but not read yet, such as the tail kept back while a closing tag is looked for. Restoring it means
    # the next branch is read from where this place was, not after what another branch fed.
    unread: str = field(default="", compare=False, repr=False)
    # The end of `unread` that could still be the start of the closing `-->` or `</name`. Two branches that differ
    # here can read the same next text differently, so they count as different places.
    unread_end: str = ""


# Elements whose content isn't page text, so a value inside one is escaped some other way.
_RAW_ELEMENTS = frozenset(
    {"script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"}
)
# HTML separates attributes only by these. Python's isspace() also matches characters such as U+00A0, which a browser
# reads as part of a name or an unquoted value.
_HTML_SPACE = frozenset("\t\n\f\r ")
# Long enough to hold the longest closing tag or comment end that a search could split.
_SEARCH_OVERLAP = 16


class HtmlContext:
    """Follows where the printed text sits in HTML, the way a browser reads it, as the converter writes it out."""

    def __init__(self) -> None:
        self.text = ""
        self.position = 0
        self.state = "text"
        self.attribute = ""
        self.tag_name = ""
        self.closing = False
        self.raw_element = ""
        # A script's end can hide inside a comment or a string in it, so nothing after one opens is trusted.
        self.untrusted = False
        # A `<` at the end of what was fed, with what follows it so far. The next text decides whether it opens a tag.
        self.partial = ""

    def snapshot(self) -> "Place":
        """Where the text is now, so two branches of a condition can be compared. Outside a tag the last tag's name
        and attribute no longer matter, so they don't count."""
        unread = self.text[self.position :]
        if self.state in ("text", "comment", "bogus"):
            unread_end = _closer_start(unread, "-->") if self.state == "comment" else ""
            return Place(state=self.state, partial=self.partial, unread=unread, unread_end=unread_end)
        if self.state == "raw":
            unread_end = _closer_start(unread, f"</{self.raw_element}")
            return Place(state=self.state, raw_element=self.raw_element, unread=unread, unread_end=unread_end)
        return Place(
            state=self.state,
            attribute=self.attribute,
            tag_name=self.tag_name,
            closing=self.closing,
            raw_element=self.raw_element,
            unread=unread,
        )

    def restore(self, place: "Place") -> None:
        self.state, self.attribute, self.tag_name = place.state, place.attribute, place.tag_name
        self.closing, self.raw_element, self.partial = place.closing, place.raw_element, place.partial
        self.text, self.position = place.unread, 0

    def feed(self, chunk: str) -> None:
        if self.position > _SEARCH_OVERLAP:
            self.text = self.text[self.position :]
            self.position = 0
        self.text += chunk
        self._advance(len(self.text))

    def where(self) -> str:
        if self.partial:
            return "tag"
        return {"dq": "value", "sq": "value", "text": "text", "raw": "raw", "comment": "comment"}.get(self.state, "tag")

    def plain_attribute(self) -> bool:
        return not self.attribute.startswith("on") and self.attribute not in ("style", "srcset", "srcdoc")

    def _advance(self, target: int) -> None:
        text = self.text
        while self.position < target:
            i = self.position
            state = self.state
            if state == "text":
                if self.partial:
                    self._open(self.partial[1:], i)
                    continue
                opening = text.find("<", i, target)
                if opening < 0:
                    self.position = target
                    break
                self._open("", opening + 1)
            elif state == "raw":
                found = _find_end_tag(text, self.raw_element, i)
                if found < 0:
                    self.position = max(i, target - _SEARCH_OVERLAP)
                    break
                self.position = found + 2
                self.state, self.tag_name, self.closing = "tag_name", "", True
            elif state in ("comment", "bogus"):
                end = "-->" if state == "comment" else ">"
                found = text.find(end, i)
                if found < 0:
                    self.position = max(i, target - _SEARCH_OVERLAP)
                    break
                self.position = found + len(end)
                self.state = "text"
            elif state in ("dq", "sq"):
                found = text.find('"' if state == "dq" else "'", i, target)
                if found < 0:
                    self.position = target
                    break
                self.position = found + 1
                self.state = "before_attribute"
            else:
                self._tag_character(text[i])
                self.position = i + 1

    def _open(self, before: str, at: int) -> None:
        """Reads what follows a `<`: `before` is the part already fed, and the rest starts at `at`."""
        rest = (before + self.text[at : at + 3])[:3]
        self.partial = ""
        self.position = at
        if rest.startswith("!--"):
            self.position = at + 3 - len(before)
            self.state = "comment"
        elif rest[:1].isalpha():
            self.state, self.tag_name, self.closing = "tag_name", "", False
        elif rest[:1] == "/" and rest[1:2].isalpha():
            self.position = at + 1 - len(before)
            self.state, self.tag_name, self.closing = "tag_name", "", True
        elif "!--".startswith(rest) or rest == "/":
            self.partial = "<" + rest
            self.position = len(self.text)
        elif rest[:1] in ("!", "?", "/"):
            self.state = "bogus"

    def _tag_character(self, character: str) -> None:
        state = self.state
        if character == ">":
            opened_raw = not self.closing and self.tag_name in _RAW_ELEMENTS
            self.state = "raw" if opened_raw else "text"
            self.raw_element = self.tag_name if opened_raw else ""
            self.untrusted = self.untrusted or (opened_raw and self.tag_name == "script")
            return
        if state == "tag_name":
            if character in _HTML_SPACE or character == "/":
                self.state = "before_attribute"
            else:
                self.tag_name = (self.tag_name + character.lower())[:20]
        elif state == "before_attribute":
            if character not in _HTML_SPACE and character != "/":
                self.state, self.attribute = "attribute", character.lower()
        elif state == "attribute":
            if character == "=":
                self.state = "before_value"
            elif character in _HTML_SPACE:
                self.state = "after_attribute"
            elif character == "/":
                self.state = "before_attribute"
            else:
                self.attribute = (self.attribute + character.lower())[:40]
        elif state == "after_attribute":
            if character == "=":
                self.state = "before_value"
            elif character not in _HTML_SPACE and character != "/":
                self.state, self.attribute = "attribute", character.lower()
        elif state == "before_value":
            if character == '"':
                self.state = "dq"
            elif character == "'":
                self.state = "sq"
            elif character not in _HTML_SPACE:
                self.state = "unquoted"
        elif state == "unquoted" and character in _HTML_SPACE:
            self.state = "before_attribute"


def _closer_start(unread: str, closer: str) -> str:
    """The longest end of `unread` that the next text could complete into `closer`."""
    lowered = unread[-len(closer) :].lower()
    for length in range(min(len(closer), len(lowered)), 0, -1):
        if lowered[-length:] == closer[:length]:
            return lowered[-length:]
    return ""


def _find_end_tag(text: str, name: str, start: int) -> int:
    match = re.compile(rf"</{re.escape(name)}[\t\n\f\r />]", re.IGNORECASE).search(text, start)
    return match.start() if match else -1
