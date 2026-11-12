"""Turns a Mailgun template version into PostHog's Liquid, and says what did not carry over.

Mailgun renders versions with its Handlebars dialect (`if`, `unless`, `each`, `with`, `equal`) or with Go templates,
then replaces `%recipient.x%` style variables. Anything else in braces stays as literal text and is named in a note,
so a person decides what it should become, and the result always parses, so a send can't fail on it.

A variable renders as `{{ variables.x }}`. Truthiness is spelled out because Handlebars and Go treat an empty string,
0 and an empty list as false, and Liquid treats them as true. See
https://documentation.mailgun.com/docs/mailgun/user-manual/sending-messages/send-templates.
"""

import re
from collections.abc import Mapping
from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

_MAX_NOTED_TAGS = 5
# Liquid can't parse a longer template, and deep blocks can make the result far longer than the source.
_MAX_OUTPUT_CHARS = 5_000_000
# Tag bodies are capped, so text full of unclosed braces scans in linear time, and stop at the next opening, so an
# unclosed tag can't swallow a real variable after it.
_TOKEN = re.compile(
    r"\\\{\{(?P<escaped>[^{}]{0,500})\}\}"
    r"|\{\{~?!--(?s:.{0,20000}?)--~?\}\}"
    r"|\{\{~?!(?s:.{0,20000}?)\}\}"
    r"|\{\{/\*(?s:.{0,20000}?)\*/\}\}"
    r"|\{\{-\s/\*(?s:.{0,20000}?)\*/\s-\}\}"
    r"|\{\{\{(?P<triple>(?:(?!\{\{)(?s:.)){0,500}?)\}\}\}"
    r"|\{\{(?P<body>(?:(?!\{\{)(?s:.)){0,500}?)\}\}"
    r"|\{\{|\{%"
)
_OPENING = re.compile(r"\{[{%]")
_RECIPIENT_VARIABLE = re.compile(r"%recipient\.([^%\s<>\"'{}]{1,128})%")
_FIXED_VARIABLE = re.compile(
    r"%(recipient|recipient_email|recipient_name|recipient_fname|recipient_lname"
    r"|unsubscribe_url|tag_unsubscribe_url|mailing_list_unsubscribe_url|unsubscribe_email)%"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][\w-]*$")
# Text every Handlebars or Go parser would read as an argument, such as "x", 5 or true.
_LITERAL_ARGUMENT = re.compile(r"""^(?:"[^"\\{}%]*"|'[^'\\{}%]*'|-?\d+(?:\.\d+)?|true|false)$""")
_ENTITY = re.compile(r"&(?:\w+|#\d+|#[xX][0-9a-fA-F]+);")
_ARGUMENT = re.compile(r"""\[[^\]]*\]|"[^"]*"|'[^']*'|\S+""")
# Syntax Handlebars can't parse, for a version whose engine field is blank.
_GO_ONLY = re.compile(r"\{\{-?\s*(?:\.[A-Za-z_]|end\b|range\b|\$)")
_ELSE_TOKEN = re.compile(r"\{\{~?-?\s*(?:else|\^)(?:\s+[^{}]*?)?\s*~?-?\}\}")

Engine = Literal["handlebars", "go"]


@frozen
class _Frame:
    """A level of template context: what `this` means inside a `with` or `each`."""

    expression: str
    key: str | None = None
    in_loop: bool = False


@frozen
class _Block:
    closer: str
    # False for a block PostHog couldn't convert: its tags stay as text, and its body still converts.
    converted: bool = True
    pops_frame: bool = False
    saved_go_variables: Mapping[str, str] | None = None


@frozen
class _Comparison:
    # Liquid tags that must run before the `if`.
    setup: str
    condition: str


@frozen
class ConvertedText:
    text: str
    # Variables Mailgun fills from recipient-variables or the list member, so the app must pass them.
    recipient_variables: tuple[str, ...] = ()
    unsupported_tags: tuple[str, ...] = ()
    has_tags: bool = False
    tag_unsubscribe: bool = False
    list_unsubscribe: bool = False
    unsubscribe_email: bool = False
    unclosed_blocks: bool = False
    go_value_in_tag: bool = False
    too_large: bool = False


@frozen
class ConvertedVersion:
    subject: str
    html: str
    notes: tuple[str, ...] = ()
    # About values the app passes when it sends.
    send_notes: tuple[str, ...] = field(default_factory=tuple)
    has_content: bool = True


def detect_engine(version: Mapping[str, Any]) -> Engine:
    engine = str(version.get("engine") or "").strip().lower()
    if engine == "go":
        return "go"
    if engine:
        return "handlebars"
    return "go" if _GO_ONLY.search(str(version.get("template") or "")) else "handlebars"


def convert_text(text: str | None, *, engine: Engine = "handlebars", is_html: bool = True) -> ConvertedText:
    if not text:
        return ConvertedText(text="")
    return _Converter(text.replace("\x00", ""), engine, is_html).convert()


def convert_version(version: Mapping[str, Any]) -> ConvertedVersion:
    """A version's subject and body in Liquid, with notes on anything to review."""
    engine = detect_engine(version)
    raw_headers = version.get("headers")
    headers: Mapping[str, Any] = raw_headers if isinstance(raw_headers, dict) else {}
    subject_source = str(_header(headers, "Subject") or "")
    subject = convert_text(subject_source, engine=engine, is_html=False)
    body_source = version.get("template")
    html = convert_text(body_source if isinstance(body_source, str) else "", engine=engine)
    parts = (subject, html)
    notes: list[str] = []
    send_notes: list[str] = []
    named_engine = str(version.get("engine") or "").strip().lower()

    if tags := list(dict.fromkeys(tag for part in parts for tag in part.unsupported_tags)):
        shown = ", ".join(tags[:_MAX_NOTED_TAGS])
        more = f" and {len(tags) - _MAX_NOTED_TAGS} more" if len(tags) > _MAX_NOTED_TAGS else ""
        notes.append(f"PostHog can't convert {shown}{more}, so it appears as plain text. Rewrite it in Liquid.")
    if any(part.unclosed_blocks for part in parts):
        notes.append("A block in this template was never closed. PostHog closed it at the end, so check the layout.")
    if any(part.too_large for part in parts):
        notes.append("This template is too large to convert, so it appears as plain text. Rewrite it in Liquid.")
    if any(part.go_value_in_tag for part in parts):
        notes.append(
            "Go templates check values inside HTML tags, such as a link's address, and PostHog doesn't. Make sure "
            "those values come from a source you trust."
        )
    if engine == "go":
        notes.append(
            "Mailgun renders this version with Go templates. PostHog converted it to Liquid and escapes values for "
            "HTML, so send a test and check any value that holds HTML."
        )
    elif named_engine not in ("", "handlebars"):
        notes.append(f"Mailgun lists the engine {named_engine}. PostHog read it as Handlebars, so send a test.")
    if not subject_source:
        notes.append("This template has no subject in Mailgun, so your app set it on each send. Add one here.")
    elif subject.has_tags:
        notes.append("The subject uses variables, so send a test to check how it reads.")
    if version.get("mjml") and isinstance(body_source, str) and body_source:
        notes.append("PostHog imported the HTML of this template. Its MJML source stays in Mailgun.")
    if any(part.tag_unsubscribe for part in parts):
        notes.append(
            "%tag_unsubscribe_url% now opens the PostHog preferences page. To let people leave one type of email, "
            "put this template in a message category."
        )
    if any(part.list_unsubscribe for part in parts):
        notes.append(
            "%mailing_list_unsubscribe_url% now opens the PostHog preferences page. Put this template in the message "
            "category imported from the list."
        )
    if any(part.unsubscribe_email for part in parts):
        notes.append("PostHog has no %unsubscribe_email% address, so it stays as text. Remove it.")
    if recipient := list(dict.fromkeys(name for part in parts for name in part.recipient_variables)):
        send_notes.append(
            f"Mailgun fills {', '.join(recipient[:_MAX_NOTED_TAGS])} for each recipient. PostHog doesn't, so your app "
            "has to pass them as variables."
        )
    return ConvertedVersion(
        subject=subject.text,
        html=html.text,
        notes=tuple(notes),
        send_notes=tuple(send_notes),
        has_content=bool(html.text),
    )


def _header(headers: Mapping[str, Any], name: str) -> Any:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


class _TooLarge(Exception):
    pass


class _Converter:
    def __init__(self, text: str, engine: Engine, is_html: bool) -> None:
        self.text = text
        self.engine = engine
        self.is_html = is_html
        self.frames: list[_Frame] = [_Frame(expression="variables")]
        self.blocks: list[_Block] = []
        self.loop_depth = 0
        self.compare_count = 0
        self.unsupported: list[str] = []
        self.recipient_variables: list[str] = []
        self.tag_unsubscribe = False
        self.list_unsubscribe = False
        self.unsubscribe_email = False
        self.has_tags = False
        self.go_variables: dict[str, str] = {}
        # Whether the text so far ends inside an HTML tag, where an unquoted attribute can end at a space or `=`.
        self.in_tag = False
        self.tag_quote = ""
        self.go_value_in_tag = False
        # Per open block: the tag state where it opened, and where each earlier branch ended.
        self.tag_branches: list[tuple[tuple[bool, str], list[tuple[bool, str]]]] = []

    def convert(self) -> ConvertedText:
        try:
            return self._convert()
        except _TooLarge:
            return ConvertedText(text=_literal(self.text), has_tags=True, too_large=True)

    def _convert(self) -> ConvertedText:
        matches = list(_TOKEN.finditer(self.text))
        # Text and tags alternate: [text, tag, text, tag, ..., text].
        pieces: list[str] = []
        kept: list[tuple[str, bool]] = []
        cursor = 0
        size = 0
        for match in matches:
            before = self.text[cursor : match.start()]
            pieces.append(before)
            self._track_tag(before)
            depth = len(self.blocks)
            kept.append(self._read_token(match))
            self._track_branches(match.group(0), depth)
            size += len(before) + len(kept[-1][0])
            if size > _MAX_OUTPUT_CHARS:
                raise _TooLarge
            cursor = match.end()
        pieces.append(self.text[cursor:])
        self._strip_whitespace(pieces, matches, kept)

        out: list[str] = []
        for index, piece in enumerate(pieces):
            out.append(self._convert_plain_text(piece))
            if index < len(kept):
                out.append(kept[index][0])
        unclosed = bool(self.blocks)
        while self.blocks:
            out.append(self._close(self.blocks[-1].closer) or "")
        return ConvertedText(
            text="".join(out),
            recipient_variables=tuple(dict.fromkeys(self.recipient_variables)),
            unsupported_tags=tuple(dict.fromkeys(self.unsupported)),
            has_tags=self.has_tags,
            tag_unsubscribe=self.tag_unsubscribe,
            list_unsubscribe=self.list_unsubscribe,
            unsubscribe_email=self.unsubscribe_email,
            unclosed_blocks=unclosed,
            go_value_in_tag=self.go_value_in_tag,
        )

    def _track_tag(self, text: str) -> None:
        # A `>` inside a quoted attribute value doesn't close the tag.
        for character in text:
            if not self.in_tag:
                if character == "<":
                    self.in_tag, self.tag_quote = True, ""
            elif self.tag_quote:
                if character == self.tag_quote:
                    self.tag_quote = ""
            elif character in "\"'":
                self.tag_quote = character
            elif character == ">":
                self.in_tag = False

    def _track_branches(self, token: str, depth: int) -> None:
        """Only one branch of an if/else renders, so after the block a value is inside a tag if any branch left one
        open."""
        if len(self.blocks) > depth:
            self.tag_branches.append(((self.in_tag, self.tag_quote), []))
        elif len(self.blocks) < depth and self.tag_branches:
            _, ended = self.tag_branches.pop()
            states = [*ended, (self.in_tag, self.tag_quote)]
            self.in_tag, self.tag_quote = next((state for state in states if state[0]), states[-1])
        elif _ELSE_TOKEN.fullmatch(token) and self.tag_branches:
            opened, ended = self.tag_branches[-1]
            ended.append((self.in_tag, self.tag_quote))
            self.in_tag, self.tag_quote = opened

    def _strip_whitespace(self, pieces: list[str], matches: list[re.Match[str]], kept: list[tuple[str, bool]]) -> None:
        previous_ended_its_line = False
        for index, match in enumerate(matches):
            token = match.group(0)
            before, after = pieces[index], pieces[index + 1]
            ended_its_line = False
            if self.engine == "go":
                strip_before, strip_after = token.startswith(("{{- ", "{{-\n")), token.endswith((" -}}", "\n-}}"))
            else:
                strip_before, strip_after = token.startswith("{{~"), token.endswith("~}}")
            if strip_before:
                before = before.rstrip()
            if strip_after:
                after = after.lstrip()
            # Handlebars drops the line around a block tag that stands alone on it, so templates don't gain blank lines.
            if self.engine == "handlebars" and kept[index][1]:
                line_start = before.rfind("\n") + 1
                line_end = after.find("\n")
                at_start = not before[line_start:].strip() and (line_start > 0 or index == 0 or previous_ended_its_line)
                at_end = (line_end >= 0 and not after[:line_end].strip()) or (
                    line_end < 0 and not after.strip() and index == len(matches) - 1
                )
                if at_start and at_end:
                    before = before[:line_start]
                    after = after[line_end + 1 :] if line_end >= 0 else ""
                    ended_its_line = True
            pieces[index], pieces[index + 1] = before, after
            previous_ended_its_line = ended_its_line

    def _read_token(self, match: re.Match[str]) -> tuple[str, bool]:
        """The Liquid for one tag, and whether Handlebars treats it as able to stand alone on its line."""
        token = match.group(0)
        if match.group("escaped") is not None:
            return _literal(token[1:]), False
        if token.startswith(("{{!", "{{~!", "{{/*", "{{- /*")):
            return "", True
        triple, body = match.group("triple"), match.group("body")
        if triple is None and body is None:
            return self._unsupported(token), False
        self.has_tags = True
        if self.engine == "go":
            return self._read_go(token, body if body is not None else token), False
        return self._read_handlebars(token, triple, body)

    # Handlebars

    def _read_handlebars(self, token: str, triple: str | None, body: str | None) -> tuple[str, bool]:
        source = (triple if triple is not None else body or "").strip()
        source = source.strip("~").strip()
        if triple is not None or source.startswith("&"):
            return self._output(token, source.removeprefix("&").strip(), raw=True), False
        if source.startswith("#"):
            return self._open_handlebars(token, source[1:].strip()), True
        if source.startswith("/"):
            return self._close_handlebars(token, source[1:].strip()), True
        if source in ("else", "^"):
            return self._else(token), True
        if source.startswith("else "):
            return self._else_if(token, source[5:].strip()), True
        if source.startswith(("^", ">", "*")) or source == "":
            self._mark_unknown_block(source)
            return self._unsupported(token), source.startswith(("^", ">"))
        return self._output(token, source, raw=False), False

    def _mark_unknown_block(self, source: str) -> None:
        if source.startswith("^") and len(source) > 1:
            self.blocks.append(_Block(closer=source[1:].strip(), converted=False))

    def _open_handlebars(self, token: str, source: str) -> str:
        parts = _ARGUMENT.findall(source)
        helper = parts[0] if parts else ""
        args = parts[1:]
        if helper in ("if", "unless") and len(args) == 1 and (path := self._value(args[0])) is not None:
            self.blocks.append(_Block(closer=helper))
            return f"{{% {helper} {self._truthy(path)} %}}"
        if helper == "with" and len(args) == 1 and (path := self._path(args[0])) is not None:
            self.blocks.append(_Block(closer="with", pops_frame=True))
            self.frames.append(_Frame(expression=path))
            return f"{{% if {self._truthy(path)} %}}"
        if helper == "each" and len(args) == 1 and (path := self._path(args[0])) is not None:
            return self._open_loop(path, closer="each")
        if helper == "equal" and len(args) == 2:
            comparison = self._equal(args[0], args[1])
            if comparison is not None:
                self.blocks.append(_Block(closer="equal"))
                return f"{comparison.setup}{{% if {comparison.condition} %}}"
        self.blocks.append(_Block(closer=helper, converted=False))
        return self._unsupported(token)

    def _open_loop(self, path: str, *, closer: str, saved_go_variables: Mapping[str, str] | None = None) -> str:
        # Handlebars and Go loop over an object's values, and Liquid over [key, value] pairs. Only the data says which
        # one a send passes, and an object is the one with no length.
        self.loop_depth += 1
        item = f"item{self.loop_depth}"
        is_object, key, value = f"{item}_is_object", f"{item}_key", f"{item}_value"
        self.frames.append(_Frame(expression=value, key=key, in_loop=True))
        self.blocks.append(_Block(closer=closer, pops_frame=True, saved_go_variables=saved_go_variables))
        return (
            f"{{% assign {is_object} = false %}}{{% if {path}.length == nil and {path}.size > 0 %}}"
            f"{{% assign {is_object} = true %}}{{% endif %}}{{% for {item} in {path} %}}{{% if {is_object} %}}"
            f"{{% assign {key} = {item}[0] %}}{{% assign {value} = {item}[1] %}}{{% else %}}"
            f"{{% assign {key} = forloop.index0 %}}{{% assign {value} = {item} %}}{{% endif %}}"
        )

    def _truthy(self, path: str) -> str:
        # Liquid treats "", 0 and empty lists as true. Handlebars treats an empty object as true and Go as false.
        if self.engine == "go":
            return f"{path} and {path} != empty and {path} != 0"
        return f"{path} and {path}.length != 0 and {path} != 0"

    def _equal(self, left: str, right: str) -> _Comparison | None:
        # Mailgun's `equal` compares both sides as strings, so 5 equals "5". Liquid can't filter inside an `if`.
        prefix = ""
        sides: list[str] = []
        for argument in (left, right):
            if _LITERAL_ARGUMENT.match(argument):
                sides.append(_string_literal(argument))
                continue
            path = self._path(argument)
            if path is None:
                return None
            self.compare_count += 1
            name = f"compared{self.compare_count}"
            prefix += f'{{% assign {name} = {path} | append: "" %}}'
            sides.append(name)
        return _Comparison(setup=prefix, condition=f"{sides[0]} == {sides[1]}")

    def _close_handlebars(self, token: str, name: str) -> str:
        if self.blocks and self.blocks[-1].closer == name:
            return self._close(name) if self.blocks[-1].converted else self._pop_unconverted(token)
        return self._unsupported(token)

    def _pop_unconverted(self, token: str) -> str:
        self.blocks.pop()
        return self._unsupported(token)

    def _close(self, closer: str) -> str:
        block = self.blocks.pop()
        if block.saved_go_variables is not None:
            self.go_variables = dict(block.saved_go_variables)
        if block.pops_frame:
            if self.frames[-1].in_loop:
                self.loop_depth -= 1
            self.frames.pop()
        if not block.converted:
            return ""
        return {"each": "{% endfor %}", "range": "{% endfor %}", "unless": "{% endunless %}"}.get(
            block.closer, "{% endif %}"
        )

    def _else(self, token: str) -> str:
        if not self.blocks or not self.blocks[-1].converted:
            return self._unsupported(token)
        block = self.blocks[-1]
        if block.pops_frame:
            # The else of `with` or `each` runs in the outer context.
            if self.frames[-1].in_loop:
                self.loop_depth -= 1
            self.frames.pop()
            self.blocks[-1] = _Block(closer=block.closer, pops_frame=False, saved_go_variables=block.saved_go_variables)
        return "{% else %}"

    def _else_if(self, token: str, source: str) -> str:
        if not self.blocks or not self.blocks[-1].converted or self.blocks[-1].closer not in ("if", "unless", "equal"):
            return self._unsupported(token)
        parts = _ARGUMENT.findall(source)
        if len(parts) == 2 and parts[0] == "if" and (path := self._value(parts[1])) is not None:
            return f"{{% elsif {self._truthy(path)} %}}"
        return self._unsupported(token)

    def _output(self, token: str, source: str, *, raw: bool) -> str:
        path = self._value(source)
        if path is None:
            return self._unsupported(token)
        if raw and self.is_html:
            return f"{{{{ {path} | raw }}}}"
        if self.in_tag and self.is_html:
            return _attribute_safe(path)
        return f"{{{{ {path} }}}}"

    def _value(self, source: str) -> str | None:
        return self._loop_value(source) or self._path(source)

    def _loop_value(self, source: str) -> str | None:
        frame = next((frame for frame in reversed(self.frames) if frame.in_loop), None)
        if frame is None:
            return None
        if source == "@index":
            return "forloop.index0"
        if source == "@first":
            return "forloop.first"
        if source == "@last":
            return "forloop.last"
        if source == "@key":
            return frame.key
        return None

    def _path(self, source: str) -> str | None:
        source = source.strip()
        if source.startswith("@root"):
            frame = self.frames[0].expression
            source = source[len("@root") :].lstrip("./")
            return _join(frame, source) if source else frame
        if source.startswith("@"):
            return None
        depth = 0
        while source.startswith("../"):
            depth += 1
            source = source[3:]
        if source == "..":
            depth += 1
            source = ""
        if depth >= len(self.frames):
            return None
        base = self.frames[-1 - depth].expression
        if source in ("", "this", "."):
            return base
        for prefix in ("this.", "this/", "./"):
            if source.startswith(prefix):
                source = source[len(prefix) :]
                break
        return _join(base, source)

    # Go templates

    def _read_go(self, token: str, source: str) -> str:
        source = source.strip()
        if source.startswith("-"):
            source = source[1:].strip()
        if source.endswith("-"):
            source = source[:-1].strip()
        words = source.split(None, 1)
        keyword = words[0] if words else ""
        rest = words[1].strip() if len(words) > 1 else ""
        if keyword in ("if", "with"):
            return self._open_go_condition(token, keyword, rest)
        if keyword == "range":
            return self._open_go_range(token, rest)
        if keyword == "end":
            if self.blocks and self.blocks[-1].converted:
                return self._close(self.blocks[-1].closer)
            if self.blocks:
                return self._pop_unconverted(token)
            return self._unsupported(token)
        if keyword == "else":
            if not rest:
                return self._else(token)
            if rest.startswith("if ") and self.blocks and self.blocks[-1].closer == "if":
                condition = self._go_condition(rest[3:].strip())
                if condition is not None:
                    return f"{{% elsif {condition} %}}"
            return self._unsupported(token)
        if keyword in ("define", "block", "template", "break", "continue"):
            if keyword in ("define", "block"):
                self.blocks.append(_Block(closer="end", converted=False))
            return self._unsupported(token)
        path = self._go_path(source)
        if path is None:
            return self._unsupported(token)
        if self.in_tag and self.is_html:
            self.go_value_in_tag = True
            return _attribute_safe(path)
        return f"{{{{ {path} }}}}"

    def _open_go_condition(self, token: str, keyword: str, source: str) -> str:
        if keyword == "with":
            path = self._go_path(source)
            if path is not None:
                self.blocks.append(_Block(closer="with", pops_frame=True))
                self.frames.append(_Frame(expression=path))
                return f"{{% if {self._truthy(path)} %}}"
        else:
            condition = self._go_condition(source)
            if condition is not None:
                self.blocks.append(_Block(closer="if"))
                return f"{{% if {condition} %}}"
        self.blocks.append(_Block(closer="end", converted=False))
        return self._unsupported(token)

    def _go_condition(self, source: str) -> str | None:
        parts = _ARGUMENT.findall(source)
        if len(parts) == 1 and (path := self._go_path(parts[0])) is not None:
            return self._truthy(path)
        if len(parts) == 2 and parts[0] == "not" and (path := self._go_path(parts[1])) is not None:
            return _falsy(path)
        if len(parts) >= 3 and parts[0] == "and":
            paths = [self._go_path(part) for part in parts[1:]]
            if all(paths):
                return " and ".join(self._truthy(str(path)) for path in paths)
        if len(parts) == 3 and parts[0] in ("eq", "ne"):
            sides = [part if _LITERAL_ARGUMENT.match(part) else self._go_path(part) for part in parts[1:]]
            if all(sides):
                return f"{sides[0]} {'==' if parts[0] == 'eq' else '!='} {sides[1]}"
        return None

    def _open_go_range(self, token: str, source: str) -> str:
        index_name: str | None = None
        element_name: str | None = None
        if ":=" in source:
            declared, _, source = source.partition(":=")
            names = [name.strip() for name in declared.split(",")]
            if not all(re.fullmatch(r"\$\w+", name) for name in names) or len(names) > 2:
                self.blocks.append(_Block(closer="end", converted=False))
                return self._unsupported(token)
            index_name, element_name = (names[0], names[1]) if len(names) == 2 else (None, names[0])
        path = self._go_path(source.strip())
        if path is None:
            self.blocks.append(_Block(closer="end", converted=False))
            return self._unsupported(token)
        opening = self._open_loop(path, closer="range", saved_go_variables=dict(self.go_variables))
        if element_name:
            self.go_variables[element_name] = self.frames[-1].expression
        if index_name:
            self.go_variables[index_name] = str(self.frames[-1].key)
        return opening

    def _go_path(self, source: str) -> str | None:
        source = source.strip()
        if source == ".":
            return self.frames[-1].expression
        if source == "$":
            return self.frames[0].expression
        if source.startswith("$."):
            return _join(self.frames[0].expression, source[2:])
        if source.startswith("$"):
            name, dot, rest = source.partition(".")
            known = self.go_variables.get(name)
            if known is None:
                return None
            return _join(known, rest) if dot else known
        if source.startswith("."):
            return _join(self.frames[-1].expression, source[1:])
        return None

    # Text around tags

    def _convert_plain_text(self, text: str) -> str:
        def replace_fixed(match: re.Match[str]) -> str:
            name = match.group(1)
            if name == "unsubscribe_url":
                return "{{ unsubscribe_url }}"
            if name == "tag_unsubscribe_url":
                self.tag_unsubscribe = True
                return "{{ unsubscribe_url }}"
            if name == "mailing_list_unsubscribe_url":
                self.list_unsubscribe = True
                return "{{ unsubscribe_url }}"
            if name == "unsubscribe_email":
                self.unsubscribe_email = True
                return match.group(0)
            self.recipient_variables.append(f"%{name}%")
            return self._raw_variable(f"variables.{name}")

        def replace_recipient(match: re.Match[str]) -> str:
            name = match.group(1)
            self.recipient_variables.append(match.group(0))
            return self._raw_variable(_join("variables", name, split=False) or match.group(0))

        return _RECIPIENT_VARIABLE.sub(replace_recipient, _FIXED_VARIABLE.sub(replace_fixed, text))

    def _raw_variable(self, path: str) -> str:
        # Mailgun pastes these values into the finished message as they are, without escaping them.
        return f"{{{{ {path} | raw }}}}" if self.is_html else f"{{{{ {path} }}}}"

    def _unsupported(self, token: str) -> str:
        self.unsupported.append(token)
        return _literal(token)


def _attribute_safe(path: str) -> str:
    # Handlebars also escapes = and `, so a value can't end an unquoted attribute and start another one.
    return f'{{{{ {path} | escape | replace: "=", "&#x3D;" | replace: "`", "&#x60;" | raw }}}}'


def _falsy(path: str) -> str:
    return f"{path} == nil or {path} == false or {path} == empty or {path} == 0"


def _join(base: str, source: str, *, split: bool = True) -> str | None:
    segments = _segments(source) if split else [source]
    if segments is None:
        return None
    path = base
    for segment in segments:
        if segment.isdigit():
            path += f"[{segment}]"
        elif _IDENTIFIER.match(segment):
            path += f".{segment}"
        elif '"' not in segment and "\\" not in segment and not _ENTITY.search(segment) and "%20" not in segment:
            path += f'["{segment}"]'
        else:
            return None
    return path


def _segments(source: str) -> list[str] | None:
    """Splits `a.b`, `a/b` and `a.[b c].[0]`. None when the text isn't a plain path, such as a helper with arguments."""
    segments: list[str] = []
    for match in re.finditer(r"\[([^\]]*)\]|([^./\[\]\s()=|]+)|([./])|(.)", source):
        literal, word, separator, other = match.groups()
        if other is not None:
            return None
        if separator is None:
            segments.append(literal if literal is not None else word)
    if not segments or any(
        segment.startswith("$") or segment in ("true", "false", "null", "undefined") for segment in segments
    ):
        return None
    return segments


def _string_literal(argument: str) -> str:
    if argument[0] in "\"'":
        return argument
    return f'"{argument}"'


def _literal(tag: str) -> str:
    # A raw block ends at the first `endraw` and needs a close of its own, so these print their openings another way.
    if "endraw" in tag or tag in ("{{", "{%"):
        return _OPENING.sub(lambda opening: f'{{{{ "{opening.group(0)}" }}}}', tag)
    return f"{{% raw %}}{tag}{{% endraw %}}"
