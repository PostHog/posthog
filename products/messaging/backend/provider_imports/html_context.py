"""Follows where text sits in an HTML email, the way a browser reads it, so a converter knows how a value there is
escaped."""

import re

# Elements whose content isn't page text, so a value inside one is escaped some other way.
_RAW_ELEMENTS = frozenset(
    {"script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"}
)
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

    def feed(self, chunk: str) -> None:
        if self.position > _SEARCH_OVERLAP:
            self.text = self.text[self.position :]
            self.position = 0
        self.text += chunk
        self._advance(len(self.text))

    def where(self) -> str:
        return {"dq": "value", "sq": "value", "text": "text", "raw": "raw", "comment": "comment"}.get(self.state, "tag")

    def plain_attribute(self) -> bool:
        return not self.attribute.startswith("on") and self.attribute not in ("style", "srcset")

    def _advance(self, target: int) -> None:
        text = self.text
        while self.position < target:
            i = self.position
            state = self.state
            if state == "text":
                opening = text.find("<", i, target)
                if opening < 0:
                    self.position = target
                    break
                self.position = opening + 1
                self._open(opening)
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

    def _open(self, opening: int) -> None:
        rest = self.text[opening + 1 : opening + 4]
        if rest.startswith("!--"):
            self.position = opening + 4
            self.state = "comment"
        elif rest[:1].isalpha():
            self.state, self.tag_name, self.closing = "tag_name", "", False
        elif rest[:1] == "/" and rest[1:2].isalpha():
            self.position = opening + 2
            self.state, self.tag_name, self.closing = "tag_name", "", True
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
            if character.isspace() or character == "/":
                self.state = "before_attribute"
            else:
                self.tag_name = (self.tag_name + character.lower())[:20]
        elif state == "before_attribute":
            if not character.isspace() and character != "/":
                self.state, self.attribute = "attribute", character.lower()
        elif state == "attribute":
            if character == "=":
                self.state = "before_value"
            elif character.isspace():
                self.state = "after_attribute"
            elif character == "/":
                self.state = "before_attribute"
            else:
                self.attribute = (self.attribute + character.lower())[:40]
        elif state == "after_attribute":
            if character == "=":
                self.state = "before_value"
            elif not character.isspace() and character != "/":
                self.state, self.attribute = "attribute", character.lower()
        elif state == "before_value":
            if character == '"':
                self.state = "dq"
            elif character == "'":
                self.state = "sq"
            elif not character.isspace():
                self.state = "unquoted"
        elif state == "unquoted" and character.isspace():
            self.state = "before_attribute"


def _find_end_tag(text: str, name: str, start: int) -> int:
    match = re.compile(rf"</{re.escape(name)}[\s/>]", re.IGNORECASE).search(text, start)
    return match.start() if match else -1
