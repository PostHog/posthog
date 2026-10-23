import re
import hashlib
from collections.abc import Iterable

from posthog.dataclasses import frozen

from products.error_tracking.backend.facade.contracts import (
    SentryMigrationCategory,
    SentryMigrationFit,
    SentryMigrationItem,
    SentryMigrationRateLimit,
)
from products.error_tracking.backend.logic.sentry_migration.client import SentryProjectConfig, SentryRateLimit

# Keep in sync with BUCKET_OPTIONS in frontend/scenes/ErrorTrackingConfigurationScene/rate_limit/rateLimitConfigLogic.ts.
SUPPORTED_BUCKET_MINUTES = (15, 30, 60)
# ErrorTrackingSettings.project_rate_limit_value is a 32-bit integer column.
MAX_RATE_LIMIT_VALUE = 2**31 - 1

# Characters with a meaning in RE2, Rust regex and JavaScript. Escaping only these keeps every
# generated pattern valid in all three engines: ClickHouse, cymbal and the Python HogVM.
_REGEX_METACHARACTERS = frozenset(".^$*+?()[]{}|\\")
# Inside a character class Rust regex also reads `&&`, `--` and `~~` as set operations.
_CLASS_METACHARACTERS = frozenset("\\[]^-&~")

# A Sentry pattern that starts with a literal exception type, such as "TypeError: Failed to fetch*".
_TYPE_PREFIX = re.compile(r"^([A-Za-z_$][\w$.]*): (.+)$", re.DOTALL)
_CONTAINS_GLOB = re.compile(r"^\*([^*?{}\[\]\\]+)\*$")

# Error values Sentry attributes to browser extensions (relay-filter/src/browser_extensions.rs).
_EXTENSION_ERROR_VALUES = (
    r"top\.GLOBALS",
    r"originalCreateNotification",
    r"canvas\.contentDocument",
    r"MyApp_RemoveAllHighlights",
    r"http://tt\.epicplay\.com",
    r"Can't\sfind\svariable:\sZiteReader",
    r"jigsaw\sis\snot\sdefined",
    r"ComboSearch\sis\snot\sdefined",
    r"http://loading\.retry\.widdit\.com/",
    r"atomicFindClose",
    r"fb_xd_fragment",
    r"bmi_SafeAddOnload",
    r"EBCallBackMessageReceived",
    r"_gCrWeb",
    r"conduitPage",
    r"null\sis\snot\san\sobject\s\(evaluating\s'elt\.parentNode'\)",
    r"plugin\.setSuspendState\sis\snot\sa\sfunction",
    r"Extension\scontext\sinvalidated",
    r"webkit-masked-url:",
    r"can't\saccess\sdead\sobject",
    r"Cannot\sredefine\sproperty:\s(?:solana|ethereum|googletag)",
    r"undefined\sis\snot\san\sobject\s\(evaluating\s'a\..'\)",
    r"Permission\sdenied\sto\saccess\sproperty\s",
    r"Can't\sfind\svariable:\sgmo",
)

# User agents Sentry treats as crawlers, and the ones it lets through (relay-filter/src/web_crawlers.rs).
_WEB_CRAWLER_USER_AGENTS = (
    r"Mediapartners-Google",
    r"AdsBot-Google",
    r"Googlebot",
    r"FeedFetcher-Google",
    r"Storebot-Google",
    r"BingBot",
    r"BingPreview",
    r"Baiduspider",
    r"Slurp",
    r"Sogou",
    r"facebook",
    r"meta-",
    r"ia_archiver",
    r"bots?(?:[/\s\);]|$)",
    r"spider(?:[/\s\);]|$)",
    r"Slack",
    r"Calypso\sAppCrawler",
    r"pingdom",
    r"lyticsbot",
    r"AWS\sSecurity\sScanner",
    r"HubSpot\sCrawler",
    r"Bytespider",
    r"Better\sUptime",
    r"Cloudflare-Healthchecks",
    r"GTmetrix",
    r"BrightEdgeOnCrawl",
    r"ELB-HealthChecker",
    r"naver\.me/spd",
    r"ClaudeBot",
    r"CCBot",
    r"OAI-SearchBot",
    r"GPTBot",
    r"PerplexityBot",
    r"Applebot",
    r"DuckDuckBot",
    r"Lightpanda",
)
_ALLOWED_WEB_CRAWLER_USER_AGENTS = (r"Slackbot\s1\.\d+", r"SentryUptimeBot", r"ChatGPT-User")

_LOCALHOST_URL = (
    r"(?i)^(?:file:|[a-z][a-z0-9+.-]*://(?:localhost|127\.0\.0\.1|\[::1\]|[^/?#:]+\.localhost)(?::\d+)?(?:[/?#]|$))"
)
_REACT_HYDRATION_ERROR = (
    r"(?i)(?:reactjs\.org/docs/error-decoder\.html\?invariant=|react\.dev/errors/)(?:418|419|421|422|423|425)(?:\D|$)"
)


@frozen
class _BrowserFamily:
    label: str
    # The $browser values posthog-js reports for this family.
    browsers: tuple[str, ...]


_BROWSER_FAMILIES: dict[str, _BrowserFamily] = {
    "ie": _BrowserFamily(label="Internet Explorer", browsers=("Internet Explorer",)),
    "edge": _BrowserFamily(label="Edge", browsers=("Microsoft Edge",)),
    "safari": _BrowserFamily(label="Safari", browsers=("Safari", "Mobile Safari")),
    "firefox": _BrowserFamily(label="Firefox", browsers=("Firefox", "Firefox iOS")),
    "chrome": _BrowserFamily(label="Chrome", browsers=("Chrome", "Chrome iOS")),
    "opera": _BrowserFamily(label="Opera", browsers=("Opera",)),
    "opera_mini": _BrowserFamily(label="Opera Mini", browsers=("Opera Mini",)),
    "android": _BrowserFamily(label="Android browser", browsers=("Android Mobile",)),
}

# Families with no versions left to release. A range that reaches the last version covers the whole
# family, so the rule needs no version condition.
_FINAL_VERSION_BOUNDS = {"ie": 12}


@frozen
class _VersionRange:
    family: str
    # Inclusive lower bound. None means every version below `below`.
    at_least: int | None
    below: int


# Sentry's legacy browser subfilters (relay-filter/src/legacy_browsers.rs). "default" uses a
# separate minimum version table, which these ranges reproduce.
_LEGACY_BROWSER_RANGES: dict[str, tuple[_VersionRange, ...]] = {
    "default": (
        _VersionRange(family="ie", at_least=None, below=10),
        _VersionRange(family="safari", at_least=None, below=6),
        _VersionRange(family="opera", at_least=None, below=15),
        _VersionRange(family="android", at_least=None, below=4),
        _VersionRange(family="opera_mini", at_least=None, below=8),
    ),
    "ie": (_VersionRange(family="ie", at_least=None, below=12),),
    "edge": (_VersionRange(family="edge", at_least=None, below=111),),
    "safari": (_VersionRange(family="safari", at_least=None, below=16),),
    "firefox": (_VersionRange(family="firefox", at_least=None, below=111),),
    "chrome": (_VersionRange(family="chrome", at_least=None, below=111),),
    "opera": (_VersionRange(family="opera", at_least=None, below=100),),
    "android": (_VersionRange(family="android", at_least=None, below=4),),
    "opera_mini": (_VersionRange(family="opera_mini", at_least=None, below=35),),
    "ie_pre_9": (_VersionRange(family="ie", at_least=None, below=9),),
    "ie9": (_VersionRange(family="ie", at_least=9, below=10),),
    "ie10": (_VersionRange(family="ie", at_least=10, below=11),),
    "ie11": (_VersionRange(family="ie", at_least=11, below=12),),
    "safari_pre_6": (_VersionRange(family="safari", at_least=None, below=6),),
    "opera_pre_15": (_VersionRange(family="opera", at_least=None, below=15),),
    "opera_mini_pre_8": (_VersionRange(family="opera_mini", at_least=None, below=8),),
    "android_pre_4": (_VersionRange(family="android", at_least=None, below=4),),
    "edge_pre_79": (_VersionRange(family="edge", at_least=None, below=79),),
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
        elif char == "[" and (class_end := _class_end(glob, index)) is not None:
            parts.append(_char_class(glob[index + 1 : class_end]))
            index = class_end + 1
            continue
        elif char == "{" and not in_alternatives and "}" in glob[index + 1 :]:
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


def _class_end(glob: str, start: int) -> int | None:
    """Index of the `]` that closes the class opened at `start`, or None when the class never closes."""
    body_start = start + 1
    if glob[body_start : body_start + 1] == "!":
        body_start += 1
    # A `]` right after the opening bracket is a literal member, as in `[]a]`.
    close = glob.find("]", body_start + 1)
    return close if close != -1 else None


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


def _item_id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _format_window(seconds: int) -> str:
    for unit_seconds, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
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
        project_rate_limit: SentryMigrationRateLimit | None,
    ) -> None:
        self._existing_filters = list(existing_suppression_filters)
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
        items.extend(self._legacy_browser_items(config.legacy_browsers))
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
                id=f"rate_limit:{rate_limit.key_id}",
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
            id=f"rate_limit:{rate_limit.key_id}",
            category=SentryMigrationCategory.RATE_LIMIT,
            sentry_setting=f'Rate limit on client key "{rate_limit.key_label}"',
            sentry_value=sentry_value,
            fit=SentryMigrationFit.GOOD if exact else SentryMigrationFit.PARTIAL,
            note=" ".join(notes) or None,
            suppression_rule_filters=None,
            rate_limit=converted,
            already_in_posthog=converted == self._project_rate_limit,
        )

    def _error_message_item(self, glob: str) -> SentryMigrationItem:
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

    def _browser_extensions_item(self) -> SentryMigrationItem:
        return self._suppression_item(
            item_id="inbound_filter:browser-extensions",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="Errors caused by browser extensions",
            sentry_value="On",
            fit=SentryMigrationFit.PARTIAL,
            note=(
                "Sentry also checked which script threw the error. PostHog doesn't keep the extension URL of a "
                "stack frame, so this rule only matches the error messages Sentry links to extensions."
            ),
            filters=_group(
                "AND", [_leaf("$exception_values", "regex", f"(?i)(?:{'|'.join(_EXTENSION_ERROR_VALUES)})")]
            ),
        )

    def _localhost_item(self) -> SentryMigrationItem:
        return self._suppression_item(
            item_id="inbound_filter:localhost",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="Errors from localhost",
            sentry_value="On",
            fit=SentryMigrationFit.PARTIAL,
            note=(
                "Sentry also checked the user's IP address. PostHog checks the page URL ($current_url), "
                "which only browser SDKs send."
            ),
            filters=_group("AND", [_leaf("$current_url", "regex", _LOCALHOST_URL)]),
        )

    def _web_crawlers_item(self) -> SentryMigrationItem:
        return self._suppression_item(
            item_id="inbound_filter:web-crawlers",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="Errors from web crawlers",
            sentry_value="On",
            fit=SentryMigrationFit.PARTIAL,
            note=(
                "The PostHog web SDK already drops events from most crawlers. This rule also checks the user "
                "agent ($raw_user_agent) against Sentry's crawler list, for SDKs that send it."
            ),
            filters=_group(
                "AND",
                [
                    _leaf("$raw_user_agent", "regex", f"(?i)(?:{'|'.join(_WEB_CRAWLER_USER_AGENTS)})"),
                    _leaf("$raw_user_agent", "not_regex", f"(?i)(?:{'|'.join(_ALLOWED_WEB_CRAWLER_USER_AGENTS)})"),
                ],
            ),
        )

    def _legacy_browser_items(self, subfilters: tuple[str, ...]) -> list[SentryMigrationItem]:
        ranges_by_family: dict[str, list[_VersionRange]] = {}
        for subfilter in subfilters:
            for version_range in _LEGACY_BROWSER_RANGES.get(subfilter, ()):
                ranges_by_family.setdefault(version_range.family, []).append(version_range)

        items: list[SentryMigrationItem] = []
        for family_key, family in _BROWSER_FAMILIES.items():
            ranges = ranges_by_family.get(family_key)
            if not ranges:
                continue
            for version_range in _merge_ranges(ranges):
                items.append(self._legacy_browser_item(family_key, family, version_range))
        return items

    def _legacy_browser_item(
        self, family_key: str, family: _BrowserFamily, version_range: _VersionRange
    ) -> SentryMigrationItem:
        values = [_leaf("$browser", "exact", list(family.browsers))]
        final_bound = _FINAL_VERSION_BOUNDS.get(family_key)
        covers_all_versions = (
            version_range.at_least is None and final_bound is not None and version_range.below >= final_bound
        )
        if not covers_all_versions:
            if version_range.at_least is not None:
                values.append(_leaf("$browser_version", "gte", version_range.at_least))
            values.append(_leaf("$browser_version", "lt", version_range.below))

        if covers_all_versions:
            sentry_value = f"{family.label}, all versions"
        elif version_range.at_least is not None and version_range.at_least == version_range.below - 1:
            sentry_value = f"{family.label} {version_range.at_least}"
        elif version_range.at_least is not None:
            sentry_value = f"{family.label} {version_range.at_least} to {version_range.below - 1}"
        else:
            sentry_value = f"{family.label} {version_range.below - 1} and older"

        range_suffix = f"{version_range.at_least}-{version_range.below}"
        return self._suppression_item(
            item_id=f"inbound_filter:legacy-browsers:{family_key}:{range_suffix}",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="Errors from legacy browsers",
            sentry_value=sentry_value,
            fit=SentryMigrationFit.PARTIAL,
            note=(
                "Sentry parsed the user agent itself. PostHog uses the browser and version the web SDK "
                "reports ($browser and $browser_version)."
            ),
            filters=_group("AND", values),
        )

    def _react_hydration_item(self) -> SentryMigrationItem:
        return self._suppression_item(
            item_id="inbound_filter:react-hydration-errors",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="React hydration errors",
            sentry_value="On",
            fit=SentryMigrationFit.GOOD,
            note=None,
            filters=_group("AND", [_leaf("$exception_values", "regex", _REACT_HYDRATION_ERROR)]),
        )

    def _chunk_load_item(self) -> SentryMigrationItem:
        return self._suppression_item(
            item_id="inbound_filter:chunk-load-error",
            category=SentryMigrationCategory.INBOUND_FILTER,
            sentry_setting="ChunkLoadError errors",
            sentry_value="On",
            fit=SentryMigrationFit.GOOD,
            note=None,
            filters=_group(
                "OR",
                [
                    _leaf("$exception_types", "exact", ["ChunkLoadError"]),
                    _leaf("$exception_values", "icontains", "ChunkLoadError:"),
                ],
            ),
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
            already_in_posthog=False,
        )


def _merge_ranges(ranges: list[_VersionRange]) -> list[_VersionRange]:
    """Merge overlapping or touching version ranges of one browser family, lowest first."""
    ordered = sorted(ranges, key=lambda version_range: (version_range.at_least or 0, version_range.below))
    merged: list[_VersionRange] = []
    for version_range in ordered:
        if merged and (version_range.at_least or 0) <= merged[-1].below:
            previous = merged[-1]
            merged[-1] = _VersionRange(
                family=previous.family,
                at_least=previous.at_least,
                below=max(previous.below, version_range.below),
            )
        else:
            merged.append(version_range)
    return merged
