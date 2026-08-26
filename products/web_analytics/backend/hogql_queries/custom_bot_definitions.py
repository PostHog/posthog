"""
Project-defined bot definitions.

BOT_DEFINITIONS only covers bots that declare themselves in the user agent, and it only covers the
ones we know about. A project adds its own patterns in project settings when a scraper matters to
them but is missing from that list — an internal load test, a partner integration, a niche crawler.

The definitions are stored on `team.modifiers` and reach HogQL through
`HogQLQueryModifiers.customBotDefinitions`, so they extend `$virt_is_bot`, `$virt_bot_name`,
`$virt_bot_operator`, `$virt_traffic_type` and `$virt_traffic_category` everywhere HogQL runs,
not only in web analytics.

The patterns end up inside a ClickHouse `multiMatchAnyIndex` call, which compiles them with
hyperscan. Hyperscan supports less than PCRE, and a pattern it rejects fails every query that
reads one of those fields for the project. Two guards keep that from happening:

- `validate_definition` runs on save and rejects what we can catch in Python.
- `assert_patterns_compile` asks ClickHouse itself whether the patterns compile, because Python's
  `re` accepting a pattern does not mean hyperscan will.

`to_bot_definitions` drops anything that still fails validation, so a definition written straight
to the API before a rule tightened cannot break every query for the project.
"""

import re
from typing import TYPE_CHECKING

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS, BotDefinition

if TYPE_CHECKING:
    from posthog.schema import CustomBotDefinition

# Bounds the size of the pattern array added to every query that reads a classification field.
MAX_CUSTOM_BOT_DEFINITIONS = 50
MAX_PATTERN_LENGTH = 200
MAX_NAME_LENGTH = 100

# Category used when a project does not pick one.
CUSTOM_CATEGORY = "custom"

# Traffic type reported for each category. Kept explicit rather than derived from BOT_DEFINITIONS
# because http_client is split across two traffic types there.
# test_custom_bot_definitions.py fails if BOT_DEFINITIONS gains a category that is missing here.
TRAFFIC_TYPE_BY_CATEGORY: dict[str, str] = {
    "ai_crawler": "AI Agent",
    "ai_search": "AI Agent",
    "ai_assistant": "AI Agent",
    "search_crawler": "Bot",
    "seo_crawler": "Bot",
    "social_crawler": "Bot",
    "monitoring": "Bot",
    "http_client": "Automation",
    "headless_browser": "Automation",
    CUSTOM_CATEGORY: "Bot",
}

# Hyperscan rejects these PCRE constructs. Listing them gives the person a specific error on save
# instead of a broken project.
_UNSUPPORTED_CONSTRUCTS: list[tuple[str, str]] = [
    (r"\(\?=", "lookahead"),
    (r"\(\?!", "lookahead"),
    (r"\(\?<=", "lookbehind"),
    (r"\(\?<!", "lookbehind"),
    (r"\(\?>", "atomic group"),
    (r"\(\?\(", "conditional group"),
    (r"\(\?R", "recursion"),
    (r"\\[1-9]", "backreference"),
    (r"\\[zZGKCRX]", "unsupported escape"),
]

_REGEX_METACHARACTERS = re.compile(r"([.^$*+?()\[\]{}|\\])")


def _escape_literal(value: str) -> str:
    return _REGEX_METACHARACTERS.sub(r"\\\1", value)


def compile_pattern(pattern: str, matcher: str) -> str:
    """Turn a project's pattern into the regex handed to multiMatchAnyIndex."""
    if matcher == "regex":
        return pattern
    # Substring matching is case-insensitive so people do not have to think about how an SDK cases
    # its user agent.
    return f"(?i){_escape_literal(pattern)}"


def validate_pattern(pattern: str, matcher: str) -> None:
    """Raise ValueError when a pattern cannot be used, with a message meant for the person saving it."""
    if not pattern or not pattern.strip():
        raise ValueError("Pattern cannot be empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Pattern cannot be longer than {MAX_PATTERN_LENGTH} characters.")
    if matcher not in ("contains", "regex"):
        raise ValueError(f"Unknown matcher '{matcher}'.")
    if matcher != "regex":
        return

    for construct, label in _UNSUPPORTED_CONSTRUCTS:
        if re.search(construct, pattern):
            raise ValueError(f"Pattern uses a {label}, which is not supported here.")
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Pattern is not a valid regular expression: {error}.") from error


def validate_definition(definition: "CustomBotDefinition") -> None:
    """Raise ValueError when a definition cannot be used."""
    if not definition.name or not definition.name.strip():
        raise ValueError("Bot name cannot be empty.")
    if len(definition.name) > MAX_NAME_LENGTH:
        raise ValueError(f"Bot name cannot be longer than {MAX_NAME_LENGTH} characters.")
    if definition.category and definition.category not in TRAFFIC_TYPE_BY_CATEGORY:
        raise ValueError(f"Unknown category '{definition.category}'.")
    validate_pattern(definition.pattern, definition.matcher.value)


# ClickHouse codes that mean "this pattern is the problem": BAD_ARGUMENTS and
# CANNOT_COMPILE_REGEXP for a pattern hyperscan won't accept, HYPERSCAN_CANNOT_SCAN_TEXT for one
# it accepts but considers too slow to run. Any other code is an infrastructure problem.
_BAD_PATTERN_CH_CODES = {36, 427, 447}
_TOO_SLOW_CH_CODE = 447

# ClickHouse reports the underlying hyperscan reason as: Pattern 'x' failed with error 'reason'.
_CH_PATTERN_REASON = re.compile(r"failed with error '([^']+)'")


def assert_patterns_compile(patterns: list[str]) -> None:
    """Raise ValueError when ClickHouse cannot compile the patterns.

    Python's `re` is more permissive than hyperscan, so this asks the engine that actually runs
    them. A pattern that gets through here and then fails at query time would break every query
    reading $virt_is_bot for the project.
    """
    if not patterns:
        return

    from clickhouse_driver.errors import ServerException  # noqa: PLC0415 — keeps the heavy dep off the import path

    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415 — keeps the heavy dep off the import path

    try:
        sync_execute("SELECT multiMatchAnyIndex(%(probe)s, %(patterns)s)", {"probe": "", "patterns": patterns})
    except ServerException as error:
        if error.code not in _BAD_PATTERN_CH_CODES:
            # ClickHouse is unreachable or unhappy for an unrelated reason; don't block the save.
            return
        if error.code == _TOO_SLOW_CH_CODE:
            raise ValueError("One of these patterns is too slow to run. Try a more specific one.") from error
        reason = _CH_PATTERN_REASON.search(str(error.message or ""))
        raise ValueError(
            f"One of these patterns is not supported: {reason.group(1)}"
            if reason
            else "One of these patterns is not supported. Try a simpler expression."
        ) from error
    except Exception:
        return


def to_bot_definitions(
    definitions: list["CustomBotDefinition"] | None,
) -> list[tuple[str, BotDefinition]]:
    """Compile a project's definitions into (pattern, BotDefinition) pairs, dropping unusable ones.

    Dropping rather than raising keeps a definition that slipped past validation — saved before a
    rule tightened, or written straight to the API — from breaking every query for the project.
    """
    if not definitions:
        return []

    compiled: list[tuple[str, BotDefinition]] = []
    for definition in definitions[:MAX_CUSTOM_BOT_DEFINITIONS]:
        try:
            validate_definition(definition)
        except ValueError:
            continue
        category = definition.category or CUSTOM_CATEGORY
        compiled.append(
            (
                compile_pattern(definition.pattern, definition.matcher.value),
                BotDefinition(
                    name=definition.name,
                    category=category,
                    traffic_type=TRAFFIC_TYPE_BY_CATEGORY.get(category, "Bot"),
                    # A project's own label is the only operator we have for a bot we don't know.
                    operator=definition.name,
                ),
            )
        )
    return compiled


def categories() -> list[str]:
    """Categories a project can pick from, in the order the settings editor shows them."""
    known = list(dict.fromkeys(bot.category for bot in BOT_DEFINITIONS.values()))
    return [CUSTOM_CATEGORY, *sorted(known)]
