"""Reads one command out of a GitHub comment body.

The parser is deliberately strict. A command is a line that starts with the mention, so prose
that only talks about the bot ("thanks @posthog, review looks good") never fires. Text that
quotes or shows a command does not fire either: quoted replies and the lines that continue them,
fenced code blocks (also inside list items), preformatted and blockquote HTML blocks, inline code
and HTML comments are removed before the search, and a tab-indented line never counts because
GitHub shows it as code. That matters most for the bot's own replies and for agents that echo a
comment back, because both repeat the command text they answer.
"""

import re
import unicodedata

from posthog.dataclasses import frozen

MENTION = "@posthog"
# A line with the bare mention asks for help, so the parser owns this verb.
HELP_VERB = "help"
MAX_ARGUMENT_LENGTH = 200

# Leading indentation is spaces only. Markdown counts a tab as four columns, so a line that starts
# with a tab is an indented code block.
# A fence can also open a list item, such as "- ```" or "1. ```".
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?(`{3,}|~{3,})")
# A closing fence carries no info string. "```python" inside a block does not close it. Inside a
# list item the closing fence is indented to the item's content, so its indentation is checked
# against the opener's column in `_live_lines`, not here.
_FENCE_CLOSE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*$")
# A fence indented four or more columns past its opener is content, not a closer.
_FENCE_CLOSE_EXTRA_INDENT = 3
# HTML blocks that GitHub shows as code or as a quote. Each one runs to the line that closes its
# tag, blank lines included.
_HTML_CODE_OR_QUOTE_OPEN_RE = re.compile(r"^ {0,3}<(pre|textarea|script|style|blockquote)(?=[\s>]|$)", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# A code span can cross a line break, but not a blank line, which ends the paragraph. The
# lookarounds make each backtick run match as a whole, so a long run cannot make the search
# backtrack once for every backtick in it.
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\1(?!`)", re.DOTALL)
# The mention must stand alone: `@posthog-bot` and `@posthogx` are other accounts.
_COMMAND_LINE_RE = re.compile(
    rf"^ {{0,3}}{re.escape(MENTION)}(?![\w-])[ \t]+(?P<verb>[A-Za-z][\w-]{{0,31}})(?P<rest>.*)$",
    re.IGNORECASE,
)
_BARE_MENTION_RE = re.compile(rf"^ {{0,3}}{re.escape(MENTION)}(?![\w-])\s*$", re.IGNORECASE)


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


def _live_lines(body: str) -> list[str]:
    """Lines a person typed as their own words: no quotes, code blocks, inline code or comments."""
    text = _HTML_COMMENT_RE.sub("", body.replace("\r\n", "\n").replace("\r", "\n"))
    lines: list[str] = []
    fence: str | None = None
    fence_column = 0
    html_block_close_tag: str | None = None
    in_quote = False
    for line in text.split("\n"):
        if fence is not None:
            close_match = _FENCE_CLOSE_RE.match(line)
            # Only a run of the same character, at least as long as the opening one, closes a block.
            if (
                close_match is not None
                and close_match.group(2).startswith(fence)
                and _columns(close_match.group(1)) <= fence_column + _FENCE_CLOSE_EXTRA_INDENT
            ):
                fence = None
            continue
        if html_block_close_tag is not None:
            if html_block_close_tag in line.lower():
                html_block_close_tag = None
            continue
        # A fence or an HTML block can start right after a quoted line, so check them first.
        fence_match = _FENCE_OPEN_RE.match(line)
        if fence_match is not None:
            fence = fence_match.group(1)
            fence_column = _columns(line[: fence_match.start(1)])
            in_quote = False
            continue
        html_block_match = _HTML_CODE_OR_QUOTE_OPEN_RE.match(line)
        if html_block_match is not None:
            close_tag = f"</{html_block_match.group(1).lower()}>"
            # The opening line can close the block itself.
            if close_tag not in line[html_block_match.end() :].lower():
                html_block_close_tag = close_tag
            in_quote = False
            continue
        if not line.strip():
            in_quote = False
        elif line.lstrip().startswith(">"):
            in_quote = True
        # Markdown continues a quoted paragraph on the next lines up to a blank line, even
        # without a ">", so GitHub shows those lines inside the quote.
        if in_quote:
            continue
        lines.append(line)
    # A placeholder keeps the text before a mention, so removing a code span cannot move a
    # mention to the start of its line.
    return _INLINE_CODE_RE.sub("x", "\n".join(lines)).split("\n")


def _columns(indent: str) -> int:
    # Markdown counts a tab as four columns.
    return sum(4 if char == "\t" else 1 for char in indent)
