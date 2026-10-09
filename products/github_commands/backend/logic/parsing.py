"""Reads one command out of a GitHub comment body.

The parser is deliberately strict. A command is a line that starts with the mention, so prose
that only talks about the bot ("thanks @posthog, review looks good") never fires. Text that
quotes or shows a command does not fire either: quoted replies, code blocks, inline code and
HTML comments are removed before the search. That matters most for the bot's own replies and
for agents that echo a comment back, because both repeat the command text they answer.
"""

import re
import unicodedata

from posthog.dataclasses import frozen

MENTION = "@posthog"
# A line with the bare mention asks for help, so the parser owns this verb.
HELP_VERB = "help"
MAX_ARGUMENT_LENGTH = 200

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# A code span can cross a line break, but not a blank line, which ends the paragraph.
_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\n[ \t]*\n).)*?\1", re.DOTALL)
# The mention must stand alone: `@posthog-bot` and `@posthogx` are other accounts.
_COMMAND_LINE_RE = re.compile(
    rf"^\s{{0,3}}{re.escape(MENTION)}(?![\w-])[ \t]+(?P<verb>[A-Za-z][\w-]{{0,31}})(?P<rest>.*)$",
    re.IGNORECASE,
)
_BARE_MENTION_RE = re.compile(rf"^\s{{0,3}}{re.escape(MENTION)}(?![\w-])\s*$", re.IGNORECASE)


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
    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            # Only a run of the same character, at least as long as the opening one, closes a block.
            elif marker.startswith(fence):
                fence = None
            continue
        if fence is not None or line.lstrip().startswith(">"):
            continue
        lines.append(line)
    return _INLINE_CODE_RE.sub("", "\n".join(lines)).split("\n")
