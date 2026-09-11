"""
Project-defined bot definitions.

BOT_DEFINITIONS only covers bots that declare themselves in the user agent, and it only covers the
ones we know about. A project adds its own rules in project settings when a scraper matters to
them but is missing from that list — an internal load test, a partner integration, a niche crawler.

A rule holds one or more conditions, each on one event property, combined with AND or OR. The user
agent says who a caller claims to be, so it is the default property, but a bot that sends a browser
user agent is only identifiable by where it comes from (`$ip`), what it calls with (`$lib`), or a
combination of properties no real browser produces (an 800x600 screen), which is why the property
is selectable and conditions can be combined.

The definitions are stored on `team.modifiers` and reach HogQL through
`HogQLQueryModifiers.customBotDefinitions`, so they extend `$virt_is_bot`, `$virt_bot_name`,
`$virt_bot_operator`, `$virt_traffic_type` and `$virt_traffic_category` everywhere HogQL runs,
not only in web analytics.

Substring and regex rules end up inside a ClickHouse `multiMatchAllIndices` call, which compiles them
with hyperscan. Hyperscan supports less than PCRE, and a pattern it rejects fails every query that
reads one of those fields for the project. Two guards keep that from happening:

- `validate_rule` runs on save and rejects what we can catch in Python.
- `assert_patterns_compile` asks ClickHouse itself whether the patterns compile, because Python's
  `re` accepting a pattern does not mean hyperscan will.

`compile_definitions` drops anything that still fails validation, so a definition written straight
to the API before a rule tightened cannot break every query for the project.
"""

import re
from ipaddress import ip_network
from typing import TYPE_CHECKING, Literal, Union

import structlog

from posthog.dataclasses import frozen

from products.web_analytics.backend.hogql_queries.bot_definitions import BotDefinition
from products.web_analytics.backend.hogql_queries.bot_ip_definitions import ipv6_prefix_groups

if TYPE_CHECKING:
    from posthog.schema import CustomBotRule

logger = structlog.get_logger(__name__)

# Bounds the work added to every query that reads a classification field. The per-list and
# per-rule caps multiply, so the aggregate cap is what actually limits a query: modifiers can
# also arrive in a client-supplied query, and each condition is a hyperscan call per row.
MAX_CUSTOM_BOT_DEFINITIONS = 50
MAX_CONDITIONS_PER_RULE = 10
MAX_TOTAL_CONDITIONS = 100
MAX_PATTERN_LENGTH = 200
MAX_NAME_LENGTH = 100
# Ids are stored on team.modifiers, which is read on every query for the team.
MAX_ID_LENGTH = 100

USER_AGENT_FIELD = "$raw_user_agent"
IP_FIELD = "$ip"

# Event properties a rule can match on, labelled the way the taxonomy already labels them.
# Deliberately short: each property used adds a read to every query that selects a classification
# field, so the list stays to properties that say who is calling rather than what they found. A
# property is read only when a project has a rule on it, so a project with no such rule pays nothing.
CUSTOM_BOT_FIELDS: dict[str, str] = {
    USER_AGENT_FIELD: "Raw user agent",
    IP_FIELD: "IP address",
    "$lib": "Library",
    "$host": "Host",
    "$pathname": "Path name",
    "$current_url": "Current URL",
    "$browser": "Browser",
    "$os": "OS",
    "$browser_language": "Browser language",
    "$screen_width": "Screen width",
    "$screen_height": "Screen height",
    "$geoip_country_code": "Country code",
    "$referrer": "Referrer",
    "$referring_domain": "Referring domain",
}

# Fields stored as numbers. multiMatchAllIndices needs a String, so a rule on one of these matches
# against toString(value): a screen width of 800 matches the pattern "800". The other fields are
# already strings, so they skip the cast and their query expressions stay byte-identical.
NUMERIC_FIELDS: frozenset[str] = frozenset({"$screen_width", "$screen_height"})

CIDR_MATCHER = "cidr"
PATTERN_MATCHERS = ("contains", "regex", "exact")

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


@frozen
class PatternGroup:
    """Rules on one property, matched by a single multiMatchAllIndices pass over their patterns.

    `patterns[i]` names `definitions[i]`, so the 1-based match index reads straight off
    `definitions`.
    """

    key: str
    patterns: list[str]
    definitions: list[BotDefinition]


@frozen
class CidrGroup:
    """Rules matched against the client IP by network range.

    `networks[i]` is the (prefix length, IPv6 network address) of `definitions[i]`. IPv4 ranges are
    already mapped into IPv6 space, matching how the built-in IP ranges are compared.
    """

    key: str
    networks: list[tuple[int, str]]
    definitions: list[BotDefinition]


@frozen
class PatternCondition:
    key: str
    pattern: str


@frozen
class CidrCondition:
    key: str
    prefixlen: int
    network: str


@frozen
class CompositeGroup:
    """One rule with several conditions, matched when they combine true under `combiner`.

    Unlike the single-condition groups, a composite rule cannot share a hyperscan pass with other
    rules — its conditions read different properties — so each one is its own group.
    """

    combiner: Literal["AND", "OR"]
    conditions: list[Union[PatternCondition, CidrCondition]]
    definition: BotDefinition


CustomBotGroup = Union[PatternGroup, CidrGroup, CompositeGroup]


def _escape_literal(value: str) -> str:
    return _REGEX_METACHARACTERS.sub(r"\\\1", value)


def compile_pattern(pattern: str, matcher: str) -> str:
    """Turn a substring, equality, or regex condition into the regex handed to hyperscan."""
    if matcher == "regex":
        return pattern
    # Equality compiles to an anchored literal so it can share the hyperscan pass with the other
    # matchers. Case-sensitive: it exists for values like a screen width or a country code, where
    # the exact bytes are the point.
    if matcher == "exact":
        return f"^{_escape_literal(pattern)}$"
    # Substring matching is case-insensitive so people do not have to think about how an SDK cases
    # its user agent.
    return f"(?i){_escape_literal(pattern)}"


def compile_cidr(pattern: str) -> tuple[int, str]:
    """Turn an IP rule into the (prefix length, network address) pair the IP matcher compares.

    Normalized with strict=False first, matching what validation accepts — otherwise a range
    written with host bits set, like 192.0.2.7/24, would save and then fail to compile.
    """
    network = ip_network(pattern.strip(), strict=False)
    prefixlen, addresses = ipv6_prefix_groups((str(network),))[0]
    return prefixlen, addresses[0]


def validate_pattern(pattern: str, matcher: str, key: str) -> None:
    """Raise ValueError when a pattern cannot be used, with a message meant for the person saving it."""
    if not pattern or not pattern.strip():
        raise ValueError("Pattern cannot be empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Pattern cannot be longer than {MAX_PATTERN_LENGTH} characters.")

    if matcher == CIDR_MATCHER:
        if key != IP_FIELD:
            raise ValueError(f"IP ranges only work with the {CUSTOM_BOT_FIELDS[IP_FIELD]} property.")
        stripped = pattern.strip()
        # A zone identifier ("fe80::1%eth0") parses in Python but ClickHouse toIPv6 rejects it, and
        # a scoped link-local address can never be an event $ip. Reject it here so it cannot save and
        # then break every query that reads a bot field for the project.
        if "%" in stripped:
            raise ValueError(f"'{pattern}' is not a valid IP address or range: a zone identifier is not supported.")
        try:
            # strict=False so "12.34.56.78/24" is read as its network rather than rejected for
            # having host bits set.
            ip_network(stripped, strict=False)
        except ValueError as error:
            raise ValueError(f"'{pattern}' is not a valid IP address or range: {error}.") from error
        return

    if matcher not in PATTERN_MATCHERS:
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


def validate_rule(rule: "CustomBotRule") -> None:
    """Raise ValueError when a rule cannot be used."""
    if not rule.name or not rule.name.strip():
        raise ValueError("Bot name cannot be empty.")
    if len(rule.name) > MAX_NAME_LENGTH:
        raise ValueError(f"Bot name cannot be longer than {MAX_NAME_LENGTH} characters.")
    if rule.category and rule.category not in TRAFFIC_TYPE_BY_CATEGORY:
        raise ValueError(f"Unknown category '{rule.category}'.")
    if len(rule.id) > MAX_ID_LENGTH:
        raise ValueError(f"Rule id cannot be longer than {MAX_ID_LENGTH} characters.")
    if not rule.items:
        raise ValueError("A rule needs at least one condition.")
    if len(rule.items) > MAX_CONDITIONS_PER_RULE:
        raise ValueError(f"A rule can have at most {MAX_CONDITIONS_PER_RULE} conditions.")
    # A shared id collapses entries in the editor's id-keyed drag-and-drop context.
    seen_ids = {rule.id}
    for item in rule.items:
        if len(item.id) > MAX_ID_LENGTH:
            raise ValueError(f"Condition id cannot be longer than {MAX_ID_LENGTH} characters.")
        if item.id in seen_ids:
            raise ValueError("Condition ids must be unique within a rule and differ from the rule id.")
        seen_ids.add(item.id)
        if item.key not in CUSTOM_BOT_FIELDS:
            raise ValueError(f"Cannot match on property '{item.key}'.")
        validate_pattern(item.pattern, item.matcher.value, item.key)


def validate_rule_set(rules: list["CustomBotRule"]) -> None:
    """Raise ValueError when the rules together exceed the aggregate condition budget."""
    total = sum(len(rule.items) for rule in rules)
    if total > MAX_TOTAL_CONDITIONS:
        raise ValueError(f"You can have at most {MAX_TOTAL_CONDITIONS} conditions across all rules.")


def parse_rules(raw: list, strict: bool = False, warn_on_drop: bool = True) -> list["CustomBotRule"]:
    """Parse stored or submitted rules.

    By default an entry that does not parse — including one saved by a pre-combiner release — is
    dropped: one bad entry must not take a project's whole bot list out of every query. `strict`
    raises instead, for the save paths, where dropping would lose a rule silently.

    `warn_on_drop=False` is for the per-query path, where one permanently bad stored entry would
    otherwise log in proportion to the team's query volume.
    """
    from pydantic import ValidationError  # noqa: PLC0415 — keeps pydantic models off the django.setup import path

    from posthog.schema import CustomBotRule  # noqa: PLC0415 — same

    rules: list[CustomBotRule] = []
    for entry in raw:
        if isinstance(entry, CustomBotRule):
            rules.append(entry)
            continue
        try:
            if not isinstance(entry, dict):
                raise ValueError("Each rule must be an object.")
            rules.append(CustomBotRule(**entry))
        except (ValidationError, ValueError, TypeError) as error:
            if strict:
                raise ValueError(f"Invalid bot rule: {error}") from error
            if warn_on_drop:
                # A dropped rule stops classifying with no other trace, so make the drop visible
                # the same way the bypassed compile probe is.
                logger.warning(
                    "custom_bot_rule_dropped",
                    entry_id=str(entry.get("id", ""))[:MAX_ID_LENGTH] if isinstance(entry, dict) else "",
                    name=str(entry.get("name", ""))[:MAX_NAME_LENGTH] if isinstance(entry, dict) else "",
                    error=str(error),
                )
    return rules


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
        # Probe with the same function the query uses, so a pattern the probe accepts compiles there too.
        sync_execute("SELECT multiMatchAllIndices(%(probe)s, %(patterns)s)", {"probe": "", "patterns": patterns})
    except ServerException as error:
        if error.code not in _BAD_PATTERN_CH_CODES:
            # ClickHouse is unreachable or unhappy for an unrelated reason; don't block the save,
            # but record the skip so a bypassed probe is visible instead of silent.
            logger.warning("custom_bot_patterns_probe_skipped", code=error.code, error=str(error))
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
        # A failure inside the probe itself (driver misuse, a changed signature) would otherwise
        # disable this guard silently. Keep failing open, but make the bypass visible.
        logger.exception("custom_bot_patterns_probe_error")
        return


def _to_bot_definition(rule: "CustomBotRule") -> BotDefinition:
    category = rule.category or CUSTOM_CATEGORY
    return BotDefinition(
        name=rule.name,
        category=category,
        traffic_type=TRAFFIC_TYPE_BY_CATEGORY.get(category, "Bot"),
        # A project's own label is the only operator we have for a bot we don't know.
        operator=rule.name,
    )


def _compile_composite(rule: "CustomBotRule") -> CompositeGroup:
    conditions: list[Union[PatternCondition, CidrCondition]] = []
    for item in rule.items:
        if item.matcher.value == CIDR_MATCHER:
            prefixlen, network = compile_cidr(item.pattern)
            conditions.append(CidrCondition(key=item.key, prefixlen=prefixlen, network=network))
        else:
            conditions.append(PatternCondition(key=item.key, pattern=compile_pattern(item.pattern, item.matcher.value)))
    combiner: Literal["AND", "OR"] = "OR" if rule.combiner.value == "OR" else "AND"
    return CompositeGroup(combiner=combiner, conditions=conditions, definition=_to_bot_definition(rule))


def compile_definitions(rules: list["CustomBotRule"] | None) -> list[CustomBotGroup]:
    """Compile a project's rules into the groups the HogQL builder emits.

    Contiguous one-condition rules that match the same property the same way share a group — one
    hyperscan pass over that property at query time. A rule with several conditions becomes its
    own group. The groups come back in list order, which is the order they are checked at query
    time, so the editor's drag-to-reorder is the precedence.

    Unusable rules are dropped rather than raised on: one saved before a rule tightened, or
    written straight to the API, must not break every query for the project.
    """
    if not rules:
        return []

    # Contiguous one-condition rules on the same (property, kind) share a group — one hyperscan
    # pass. Any other rule in between (a composite, or a rule on another property) closes the run:
    # the editor promises list order is precedence, so a later rule must never slide into a group
    # positioned above something listed before it. Interleaved orderings therefore degrade to one
    # group per rule; a raised MAX_CUSTOM_BOT_DEFINITIONS should revisit this.
    open_bucket_key: tuple[str, str] | None = None
    open_bucket: list[CustomBotRule] = []
    order: list[Union[tuple[str, str, list[CustomBotRule]], CustomBotRule]] = []
    total_conditions = 0
    for rule in rules[:MAX_CUSTOM_BOT_DEFINITIONS]:
        try:
            validate_rule(rule)
        except ValueError:
            continue
        # The aggregate budget is enforced here as well as on save, because modifiers can arrive
        # in a client-supplied query that never went through a save path. Stop rather than skip:
        # dropping only the oversized rule would let a later rule jump the precedence order.
        total_conditions += len(rule.items)
        if total_conditions > MAX_TOTAL_CONDITIONS:
            break
        if len(rule.items) > 1:
            order.append(rule)
            open_bucket_key = None
            continue
        item = rule.items[0]
        kind = CIDR_MATCHER if item.matcher.value == CIDR_MATCHER else "pattern"
        bucket_key = (str(item.key), kind)
        if bucket_key != open_bucket_key:
            open_bucket_key = bucket_key
            open_bucket = []
            order.append((str(item.key), kind, open_bucket))
        open_bucket.append(rule)

    groups: list[CustomBotGroup] = []
    for entry in order:
        if not isinstance(entry, tuple):
            groups.append(_compile_composite(entry))
            continue
        key, kind, bucket = entry
        if kind == CIDR_MATCHER:
            groups.append(
                CidrGroup(
                    key=key,
                    networks=[compile_cidr(rule.items[0].pattern) for rule in bucket],
                    definitions=[_to_bot_definition(rule) for rule in bucket],
                )
            )
        else:
            groups.append(
                PatternGroup(
                    key=key,
                    patterns=[compile_pattern(rule.items[0].pattern, rule.items[0].matcher.value) for rule in bucket],
                    definitions=[_to_bot_definition(rule) for rule in bucket],
                )
            )
    return groups


def compiled_patterns(rules: list["CustomBotRule"] | None) -> list[str]:
    """Every regex a project's rules put in front of hyperscan, for the save-time check."""
    patterns: list[str] = []
    for group in compile_definitions(rules):
        if isinstance(group, PatternGroup):
            patterns.extend(group.patterns)
        elif isinstance(group, CompositeGroup):
            patterns.extend(
                condition.pattern for condition in group.conditions if isinstance(condition, PatternCondition)
            )
    return patterns
