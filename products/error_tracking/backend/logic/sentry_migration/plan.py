import re
import hashlib
from collections.abc import Iterable

from products.error_tracking.backend.facade.contracts import (
    SentryMigrationBuiltInFilter,
    SentryMigrationCategory,
    SentryMigrationFit,
    SentryMigrationItem,
    SentryMigrationRateLimit,
)
from products.error_tracking.backend.logic.built_in_filter_definitions import BUILT_IN_FILTERS_BY_KEY
from products.error_tracking.backend.logic.sentry_migration.client import SentryProjectConfig, SentryRateLimit

# Keep in sync with BUCKET_OPTIONS in frontend/scenes/ErrorTrackingConfigurationScene/rate_limit/rateLimitConfigLogic.ts.
SUPPORTED_BUCKET_MINUTES = (15, 30, 60)
# ErrorTrackingSettings.project_rate_limit_value is a 32-bit integer column.
MAX_RATE_LIMIT_VALUE = 2**31 - 1
MAX_PATTERN_LENGTH = 1000

# Characters with a meaning in RE2, Rust regex and JavaScript. Escaping only these keeps every
# generated pattern valid in all three engines: ClickHouse, cymbal and the Python HogVM.
_REGEX_METACHARACTERS = frozenset(".^$*+?()[]{}|\\")
# Inside a character class Rust regex also reads `&&`, `--` and `~~` as set operations.
_CLASS_METACHARACTERS = frozenset("\\[]^-&~")

# A Sentry pattern that starts with a literal exception type, such as "TypeError: Failed to fetch*".
_TYPE_PREFIX = re.compile(r"^([A-Za-z_$][\w$.]*): (.+)$", re.DOTALL)
# icontains compiles to ILIKE, where % and _ are wildcards, so a literal with either needs the regex form.
_CONTAINS_GLOB = re.compile(r"^\*([^*?{}\[\]\\%_]+)\*$")

# Readable names for the legacy browser options in Sentry's API. The key names give the versions.
_LEGACY_BROWSER_LABELS = {
    "default": "Sentry's default list",
    "ie": "Internet Explorer",
    "edge": "Older versions of Edge",
    "safari": "Older versions of Safari",
    "firefox": "Older versions of Firefox",
    "chrome": "Older versions of Chrome",
    "opera": "Older versions of Opera",
    "opera_mini": "Older versions of Opera Mini",
    "android": "Older versions of the Android browser",
    "ie_pre_9": "Internet Explorer 8 and older",
    "ie9": "Internet Explorer 9",
    "ie10": "Internet Explorer 10",
    "ie11": "Internet Explorer 11",
    "safari_pre_6": "Safari 5 and older",
    "opera_pre_15": "Opera 14 and older",
    "opera_mini_pre_8": "Opera Mini 7 and older",
    "android_pre_4": "Android browser 3 and older",
    "edge_pre_79": "Edge 78 and older",
}


def _leaf(key: str, operator: str, value: str | list[str] | int) -> dict:
    return {"key": key, "type": "event", "operator": operator, "value": value}


def _group(operator: str, values: list[dict]) -> dict:
    return {"type": operator, "values": values}


def glob_to_regex(glob: str) -> str:
    """Translate a Sentry glob into an anchored, case-insensitive regex.

    Sentry globs support `*`, `?`, `[abc]`, `[a-z]` and `[!abc]` classes, `{a,b}` alternatives
    and backslash escapes, match across newlines, and ignore case.
    """
    parts: list[str] = []
    in_alternatives = False
    # A comparison with the last `}` and `]` replaces a scan of the rest of the glob at each `{` and `[`.
    # This keeps a glob full of unclosed delimiters linear instead of quadratic.
    last_brace = glob.rfind("}")
    last_bracket = glob.rfind("]")
    index = 0
    while index < len(glob):
        char = glob[index]
        if char == "\\" and index + 1 < len(glob):
            parts.append(_escape(glob[index + 1]))
            index += 2
            continue
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        elif char == "[" and (class_end := _class_end(glob, index, last_bracket)) is not None:
            parts.append(_char_class(glob[index + 1 : class_end]))
            index = class_end + 1
            continue
        elif char == "{" and not in_alternatives and index < last_brace:
            parts.append("(?:")
            in_alternatives = True
        elif char == "}" and in_alternatives:
            parts.append(")")
            in_alternatives = False
        elif char == "," and in_alternatives:
            parts.append("|")
        else:
            parts.append(_escape(char))
        index += 1
    return f"(?is)^{''.join(parts)}$"


def _escape(char: str) -> str:
    return f"\\{char}" if char in _REGEX_METACHARACTERS else char


def _class_end(glob: str, start: int, last_bracket: int) -> int | None:
    """Index of the `]` that closes the class opened at `start`, or None when the class never closes."""
    body_start = start + 1
    if glob[body_start : body_start + 1] == "!":
        body_start += 1
    # A `]` right after the opening bracket is a literal member, as in `[]a]`.
    if last_bracket <= body_start:
        return None
    return glob.find("]", body_start + 1)


def _char_class(body: str) -> str:
    negated = body.startswith("!")
    members = body[1:] if negated else body
    escaped = []
    for position, char in enumerate(members):
        is_range = char == "-" and 0 < position < len(members) - 1
        escaped.append(char if is_range or char not in _CLASS_METACHARACTERS else f"\\{char}")
    return f"[{'^' if negated else ''}{''.join(escaped)}]"


def _glob_leaf(key: str, glob: str) -> dict:
    contains = _CONTAINS_GLOB.match(glob)
    if contains:
        # icontains is the same match, and posthog-js can evaluate it before it sends the event.
        return _leaf(key, "icontains", contains.group(1))
    return _leaf(key, "regex", glob_to_regex(glob))


def _rate_limit_item_id(rate_limit: SentryRateLimit) -> str:
    # The limit is part of the id, so an import fails when Sentry changed the limit after the preview.
    return f"rate_limit:{rate_limit.key_id}:{rate_limit.count}:{rate_limit.window_seconds}"


def _item_id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _pattern_too_long_item(
    prefix: str, category: SentryMigrationCategory, sentry_setting: str, glob: str
) -> SentryMigrationItem:
    return SentryMigrationItem(
        id=_item_id(prefix, glob),
        category=category,
        sentry_setting=sentry_setting,
        sentry_value=f"{glob[:100]}…",
        fit=SentryMigrationFit.UNSUPPORTED,
        note=(
            f"PostHog can import patterns of up to {MAX_PATTERN_LENGTH:,} characters, and this one has "
            f"{len(glob):,}. Add a manual suppression rule with a shorter pattern."
        ),
        suppression_rule_filters=None,
        rate_limit=None,
        built_in_filter=None,
        already_in_posthog=False,
    )


def _format_window(seconds: int) -> str:
    for unit_seconds, unit in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        if seconds % unit_seconds == 0:
            amount = seconds // unit_seconds
            return f"{amount} {unit}" if amount == 1 else f"{amount} {unit}s"
    return f"{seconds} seconds"


class SentryMigrationPlanner:
    """Turns a Sentry project's configuration into the PostHog settings that do the same job."""

    def __init__(
        self,
        *,
        existing_suppression_filters: Iterable[dict],
        enabled_built_in_filters: Iterable[str],
        project_rate_limit: SentryMigrationRateLimit | None,
    ) -> None:
        self._existing_filters = list(existing_suppression_filters)
        self._enabled_built_in_filters = frozenset(enabled_built_in_filters)
        self._project_rate_limit = project_rate_limit

    def build(self, config: SentryProjectConfig) -> list[SentryMigrationItem]:
        items: list[SentryMigrationItem] = []
        items.extend(self._rate_limit_item(rate_limit, len(config.rate_limits)) for rate_limit in config.rate_limits)
        items.extend(self._error_message_item(glob) for glob in config.error_message_globs)
        items.extend(self._release_item(glob) for glob in config.release_globs)
        if config.browser_extensions:
            items.append(self._browser_extensions_item())
        if config.localhost:
            items.append(self._localhost_item())
        if config.web_crawlers:
            items.append(self._web_crawlers_item())
        if config.legacy_browsers:
            items.append(self._legacy_browsers_item(config.legacy_browsers))
        if config.react_hydration_errors:
            items.append(self._react_hydration_item())
        if config.chunk_load_errors:
            items.append(self._chunk_load_item())
        if config.blocked_ips:
            items.append(self._blocked_ips_item(config.blocked_ips))
        return items

    def _suppression_item(
        self,
        *,
        item_id: str,
        category: SentryMigrationCategory,
        sentry_setting: str,
        sentry_value: str,
        fit: SentryMigrationFit,
        note: str | None,
        filters: dict,
    ) -> SentryMigrationItem:
        return SentryMigrationItem(
            id=item_id,
            category=category,
            sentry_setting=sentry_setting,
            sentry_value=sentry_value,
            fit=fit,
            note=note,
            suppression_rule_filters=filters,
            rate_limit=None,
            built_in_filter=None,
            already_in_posthog=filters in self._existing_filters,
        )

    def _rate_limit_item(self, rate_limit: SentryRateLimit, key_count: int) -> SentryMigrationItem:
        bucket_minutes = min(
            SUPPORTED_BUCKET_MINUTES, key=lambda minutes: abs(minutes * 60 - rate_limit.window_seconds)
        )
        value = max(1, round(rate_limit.count * bucket_minutes * 60 / rate_limit.window_seconds))
        sentry_value = f"{rate_limit.count:,} events per {_format_window(rate_limit.window_seconds)}"
        if value > MAX_RATE_LIMIT_VALUE:
            return SentryMigrationItem(
                id=_rate_limit_item_id(rate_limit),
                category=SentryMigrationCategory.RATE_LIMIT,
                sentry_setting=f'Rate limit on client key "{rate_limit.key_label}"',
                sentry_value=sentry_value,
                fit=SentryMigrationFit.UNSUPPORTED,
                note=(
                    f"This becomes {value:,} exceptions per {_format_window(bucket_minutes * 60)}, which is more "
                    "than a PostHog rate limit can hold."
                ),
                suppression_rule_filters=None,
                rate_limit=None,
                built_in_filter=None,
                already_in_posthog=False,
            )
        converted = SentryMigrationRateLimit(value=value, bucket_size_minutes=bucket_minutes)

        notes: list[str] = []
        exact = bucket_minutes * 60 == rate_limit.window_seconds
        if not exact:
            notes.append(
                f"PostHog rate limits use 15, 30 or 60 minute windows, so this becomes "
                f"{value:,} exceptions per {_format_window(bucket_minutes * 60)}."
            )
        if key_count > 1:
            notes.append("PostHog has one rate limit per project, so you can import only one of these keys.")
        current = self._project_rate_limit
        if current is not None and current != converted:
            notes.append(
                f"Importing replaces the project's current rate limit of {current.value:,} exceptions per "
                f"{_format_window(current.bucket_size_minutes * 60)}."
            )

        return SentryMigrationItem(
            id=_rate_limit_item_id(rate_limit),
            category=SentryMigrationCategory.RATE_LIMIT,
            sentry_setting=f'Rate limit on client key "{rate_limit.key_label}"',
            sentry_value=sentry_value,
            fit=SentryMigrationFit.GOOD if exact else SentryMigrationFit.PARTIAL,
            note=" ".join(notes) or None,
            suppression_rule_filters=None,
            rate_limit=converted,
            built_in_filter=None,
            already_in_posthog=converted == self._project_rate_limit,
        )

    def _error_message_item(self, glob: str) -> SentryMigrationItem:
        if len(glob) > MAX_PATTERN_LENGTH:
            return _pattern_too_long_item(
                "error_message", SentryMigrationCategory.ERROR_MESSAGE, "Error message filter", glob
            )
        typed = _TYPE_PREFIX.match(glob)
        note: str | None = None
        if typed:
            exception_type, value_glob = typed.groups()
            values = [_leaf("$exception_types", "regex", f"(?i)^{''.join(map(_escape, exception_type))}$")]
            if value_glob != "*":
                values.append(_glob_leaf("$exception_values", value_glob))
            filters = _group("AND", values)
            # Cymbal deduplicates $exception_types and $exception_values separately, so the two lists
            # don't line up by position and a rule can't pair a type with its own message.
            fit = SentryMigrationFit.PARTIAL
            note = (
                "Sentry matched the type and the message of the same exception. PostHog checks them across the "
                "whole exception chain, so a chained error can match the type in one exception and the message "
                "in another."
            )
        else:
            # Sentry matches the pattern against "Type: message", so the type alone can match it too.
            filters = _group("OR", [_glob_leaf("$exception_values", glob), _glob_leaf("$exception_types", glob)])
            fit = SentryMigrationFit.GOOD
            if ": " in glob:
                fit = SentryMigrationFit.PARTIAL
                note = (
                    "Sentry matched this pattern against the exception type and message joined together. "
                    "PostHog matches it against the type and the message one at a time."
                )
        return self._suppression_item(
            item_id=_item_id("error_message", glob),
            category=SentryMigrationCategory.ERROR_MESSAGE,
            sentry_setting="Error message filter",
            sentry_value=glob,
            fit=fit,
            note=note,
            filters=filters,
        )

    def _release_item(self, glob: str) -> SentryMigrationItem:
        if len(glob) > MAX_PATTERN_LENGTH:
            return _pattern_too_long_item("release", SentryMigrationCategory.RELEASE, "Release filter", glob)
        package, separator, version_glob = glob.rpartition("@")
        notes = ["PostHog compares this with the release version it finds for each exception ($app_version)."]
        if separator and package not in ("", "*"):
            notes.append(f'PostHog doesn\'t store the package name "{package}", so the rule checks the version only.')
        return self._suppression_item(
            item_id=_item_id("release", glob),
            category=SentryMigrationCategory.RELEASE,
            sentry_setting="Release filter",
            sentry_value=glob,
            fit=SentryMigrationFit.PARTIAL if len(notes) > 1 else SentryMigrationFit.GOOD,
            note=" ".join(notes),
            filters=_group("AND", [_glob_leaf("$app_version", version_glob if separator else glob)]),
        )

    def _built_in_filter_item(
        self,
        *,
        item_id: str,
        sentry_setting: str,
        sentry_value: str,
        built_in_key: str,
        fit: SentryMigrationFit,
        compared_with_sentry: tuple[str, ...],
    ) -> SentryMigrationItem:
        definition = BUILT_IN_FILTERS_BY_KEY[built_in_key]
        return SentryMigrationItem(
            id=item_id,
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting=sentry_setting,
            sentry_value=sentry_value,
            fit=fit,
            note=None,
            suppression_rule_filters=None,
            rate_limit=None,
            built_in_filter=SentryMigrationBuiltInFilter(
                key=definition.key,
                name=definition.name,
                description=definition.description,
                compared_with_sentry=compared_with_sentry,
            ),
            already_in_posthog=built_in_key in self._enabled_built_in_filters,
        )

    def _browser_extensions_item(self) -> SentryMigrationItem:
        return SentryMigrationItem(
            id="inbound_filter:browser-extensions",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="Errors caused by browser extensions",
            sentry_value="On",
            fit=SentryMigrationFit.UNSUPPORTED,
            note=(
                "PostHog has no automatic rule for browser extension errors yet. "
                "Add a manual suppression rule for the extension errors you see."
            ),
            suppression_rule_filters=None,
            rate_limit=None,
            built_in_filter=None,
            already_in_posthog=False,
        )

    def _localhost_item(self) -> SentryMigrationItem:
        return self._built_in_filter_item(
            item_id="inbound_filter:localhost",
            sentry_setting="Errors from localhost",
            sentry_value="On",
            built_in_key="localhost",
            fit=SentryMigrationFit.PARTIAL,
            compared_with_sentry=("Checks the page URL, so it covers errors from browsers but not from servers",),
        )

    def _web_crawlers_item(self) -> SentryMigrationItem:
        return self._built_in_filter_item(
            item_id="inbound_filter:web-crawlers",
            sentry_setting="Errors from web crawlers",
            sentry_value="On",
            built_in_key="web_crawlers",
            fit=SentryMigrationFit.PARTIAL,
            compared_with_sentry=("Uses PostHog's own bot list, which PostHog keeps up to date",),
        )

    def _legacy_browsers_item(self, subfilters: tuple[str, ...]) -> SentryMigrationItem:
        known = [label for key, label in _LEGACY_BROWSER_LABELS.items() if key in subfilters]
        unknown = sorted(key for key in subfilters if key not in _LEGACY_BROWSER_LABELS)
        selection = ", ".join(known + unknown)
        return self._built_in_filter_item(
            item_id="inbound_filter:legacy-browsers",
            sentry_setting="Errors from legacy browsers",
            sentry_value=selection,
            built_in_key="legacy_browsers",
            fit=SentryMigrationFit.PARTIAL,
            compared_with_sentry=(f"Replaces your Sentry selection ({selection}) with these versions",),
        )

    def _react_hydration_item(self) -> SentryMigrationItem:
        return self._built_in_filter_item(
            item_id="inbound_filter:react-hydration-errors",
            sentry_setting="React hydration errors",
            sentry_value="On",
            built_in_key="react_hydration_errors",
            fit=SentryMigrationFit.GOOD,
            compared_with_sentry=(),
        )

    def _chunk_load_item(self) -> SentryMigrationItem:
        return self._built_in_filter_item(
            item_id="inbound_filter:chunk-load-error",
            sentry_setting="ChunkLoadError errors",
            sentry_value="On",
            built_in_key="chunk_load_errors",
            fit=SentryMigrationFit.PARTIAL,
            compared_with_sentry=("Also drops failed dynamic imports from Vite and other bundlers",),
        )

    def _blocked_ips_item(self, blocked_ips: tuple[str, ...]) -> SentryMigrationItem:
        return SentryMigrationItem(
            id="inbound_filter:blocked-ips",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="IP address filter",
            sentry_value=", ".join(blocked_ips),
            fit=SentryMigrationFit.UNSUPPORTED,
            note="PostHog suppression rules can't filter by IP address range, so you need to set this up another way.",
            suppression_rule_filters=None,
            rate_limit=None,
            built_in_filter=None,
            already_in_posthog=False,
        )
