"""Reads one command out of a GitHub comment body.

The parser is deliberately strict. A command is a line that starts with the mention, so prose
that only talks about the bot ("thanks @posthog, review looks good") never fires. Commands come
only from top-level paragraphs, as the CommonMark reference implementation parses them, so text
that GitHub shows as a quote, code, a list item or an HTML block never fires. That matters most
for the bot's own replies and for agents that echo a comment back, because both repeat the
command text they answer.
"""

import re
import unicodedata

from markdown_it import MarkdownIt
from markdown_it.token import Token

from posthog.dataclasses import frozen

MENTION = "@posthog"
# A line with the bare mention asks for help, so the parser owns this verb.
HELP_VERB = "help"
MAX_ARGUMENT_LENGTH = 200
# A command comment is short, and the CommonMark parse of the largest comment GitHub allows costs
# most of a second inside the webhook request.
MAX_BODY_LENGTH = 10_000

# The "commonmark" preset parses raw HTML, so HTML blocks become their own tokens. GitHub renders
# tables, and a table cell is shown as table content, not as a paragraph.
_MARKDOWN = MarkdownIt("commonmark").enable("table")
_CONTAINER_OPEN = frozenset({"blockquote_open", "bullet_list_open", "ordered_list_open", "list_item_open"})
_CONTAINER_CLOSE = frozenset({"blockquote_close", "bullet_list_close", "ordered_list_close", "list_item_close"})
# A code span becomes a placeholder, so the text before a mention keeps it off the line start.
_CODE_SPAN_PLACEHOLDER = "x"
# GitHub shows the text inside these inline HTML tags as code, like a backtick span.
_HTML_CODE_OPEN_RE = re.compile(r"^<(code|kbd|samp|var|tt)(?=[\s>/])", re.IGNORECASE)
# Paragraph lines carry no leading indentation, so the mention must be the first character.
# The mention must stand alone: `@posthog-bot` and `@posthogx` are other accounts.
_COMMAND_LINE_RE = re.compile(
    rf"^{re.escape(MENTION)}(?![\w-])[ \t]+(?P<verb>[A-Za-z][\w-]{{0,31}})(?P<rest>.*)$",
    re.IGNORECASE,
)
_BARE_MENTION_RE = re.compile(rf"^{re.escape(MENTION)}(?![\w-])\s*$", re.IGNORECASE)


@frozen
class ParsedCommand:
    verb: str
    argument: str


@frozen
class AmbiguousCommand:
    """The comment holds more than one command line, so no single intent can be read from it."""

    count: int


ParseResult = ParsedCommand | AmbiguousCommand | None


def parse_command(body: str) -> ParseResult:
    """Return the one command in ``body``, ``AmbiguousCommand`` for several, or ``None`` for none.

    A line with the bare mention and no verb is read as ``help``.
    """
    # Nearly every comment has no mention, so the CommonMark parse runs only for the few that might
    # hold a command, which keeps the webhook request cheap.
    if MENTION not in body.casefold() or len(body) > MAX_BODY_LENGTH:
        return None
    commands: list[ParsedCommand] = []
    for line in _live_lines(body):
        if _BARE_MENTION_RE.match(line):
            commands.append(ParsedCommand(verb=HELP_VERB, argument=""))
            continue
        match = _COMMAND_LINE_RE.match(line)
        if match is None:
            continue
        commands.append(
            ParsedCommand(verb=match.group("verb").lower(), argument=sanitize_argument(match.group("rest")))
        )
    if len(commands) > 1:
        return AmbiguousCommand(count=len(commands))
    return commands[0] if commands else None


def sanitize_argument(raw: str) -> str:
    """Make the free text after the verb safe to store, log and hand to a product.

    Drops control and format characters, which removes bidirectional overrides and zero-width
    characters that can make text read differently than it runs. Collapses whitespace and caps
    the length, so an argument stays one short line.
    """
    kept = "".join(char for char in raw if unicodedata.category(char)[0] != "C" or char in " \t")
    collapsed = " ".join(kept.split())
    return collapsed[:MAX_ARGUMENT_LENGTH]


def _paragraph_lines(inline: Token) -> list[str]:
    lines = [""]
    # The closing tag of an open inline HTML code element. An unclosed one runs to the paragraph end.
    html_code_close_tag: str | None = None
    for child in inline.children or []:
        if html_code_close_tag is not None:
            if child.type == "html_inline" and child.content.replace(" ", "").lower() == html_code_close_tag:
                html_code_close_tag = None
            continue
        if child.type == "html_inline":
            html_code_match = _HTML_CODE_OPEN_RE.match(child.content)
            if html_code_match is not None:
                html_code_close_tag = f"</{html_code_match.group(1).lower()}>"
                lines[-1] += _CODE_SPAN_PLACEHOLDER
        elif child.type == "text":
            lines[-1] += child.content
        elif child.type in ("softbreak", "hardbreak"):
            lines.append("")
        elif child.type == "code_inline":
            lines[-1] += _CODE_SPAN_PLACEHOLDER
    return lines


def _live_lines(body: str) -> list[str]:
    """Lines of the top-level paragraphs, the only text a person types as their own words.

    GitHub shows everything else as code, a quote, a list item or an HTML block.
    """
    lines: list[str] = []
    container_depth = 0
    in_live_paragraph = False
    for token in _MARKDOWN.parse(body):
        if token.type in _CONTAINER_OPEN:
            container_depth += 1
        elif token.type in _CONTAINER_CLOSE:
            container_depth -= 1
        elif token.type == "paragraph_open":
            in_live_paragraph = container_depth == 0
        elif token.type == "paragraph_close":
            in_live_paragraph = False
        elif token.type == "inline" and in_live_paragraph:
            lines.extend(_paragraph_lines(token))
    return lines
