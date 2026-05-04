"""
SDK Doctor health assessment.

Ports the outdatedness detection logic from frontend/src/scenes/onboarding/sdks/sdkDoctorLogic.tsx
so the backend can return a pre-digested health report for MCP / agent consumption.

Keep constants and thresholds in sync with the frontend's DEVICE_CONTEXT_CONFIG,
SIGNIFICANT_TRAFFIC_THRESHOLD_*, GRACE_PERIOD_DAYS, SINGLE_VERSION_GRACE_PERIOD_DAYS,
and SDK_FRESHNESS_GRACE_PERIOD_DAYS.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from json import (
    dumps as json_dumps,
    loads as json_loads,
)
from math import ceil
from re import (
    Pattern,
    compile as re_compile,
)
from typing import Any, Literal, Optional
from urllib.parse import quote

import humanize
from redis.exceptions import RedisError

from posthog.cache_utils import cache_for
from posthog.redis import get_client

from products.growth.backend.constants import SDK_TYPES, github_sdk_versions_key

# --- SDK classification ----------------------------------------------------

MOBILE_SDKS: frozenset[str] = frozenset(
    {
        "posthog-ios",
        "posthog-android",
        "posthog-flutter",
        "posthog-react-native",
    }
)

DESKTOP_SDKS: frozenset[str] = frozenset(
    {
        "web",
        "posthog-node",
        "posthog-python",
        "posthog-php",
        "posthog-ruby",
        "posthog-go",
        "posthog-dotnet",
        "posthog-elixir",
    }
)

# Human-readable names per SDK (mirrors SDK_TYPE_READABLE_NAME in sdkConstants.ts)
SDK_READABLE_NAME: dict[str, str] = {
    "web": "Web",
    "posthog-ios": "iOS",
    "posthog-android": "Android",
    "posthog-node": "Node.js",
    "posthog-python": "Python",
    "posthog-php": "PHP",
    "posthog-ruby": "Ruby",
    "posthog-go": "Go",
    "posthog-flutter": "Flutter",
    "posthog-react-native": "React Native",
    "posthog-dotnet": ".NET",
    "posthog-elixir": "Elixir",
}

# --- Thresholds (mirrored from sdkDoctorLogic.tsx) -------------------------

# Age-based outdatedness thresholds in weeks (desktop=4mo, mobile=6mo)
AGE_THRESHOLD_DESKTOP_WEEKS = 16
AGE_THRESHOLD_MOBILE_WEEKS = 24

# Grace period (days) — versions newer than this are NEVER flagged as outdated
GRACE_PERIOD_DAYS_WEB = 14
GRACE_PERIOD_DAYS_OTHER = 7

# For the single-version case (one lib_version in use), only flag after 30 days
SINGLE_VERSION_GRACE_PERIOD_DAYS = 30

# Traffic percentage thresholds for "significant outdated traffic" alerts
# Web SDK ships very frequently, so uses 20% (vs 10% for others)
SIGNIFICANT_TRAFFIC_THRESHOLD_WEB = 0.2
SIGNIFICANT_TRAFFIC_THRESHOLD_DEFAULT = 0.1

# Minor-version outdatedness: flag if 3+ minors behind OR >180 days old
MINOR_VERSIONS_BEHIND_THRESHOLD = 3
MINOR_AGE_THRESHOLD_DAYS = 180

# --- Types ------------------------------------------------------------------

Severity = Literal["none", "warning", "danger"]
OverallHealth = Literal["healthy", "needs_attention"]
DiffKind = Literal["major", "minor", "patch", "extra"]


@dataclass
class SemanticVersion:
    major: int
    minor: Optional[int] = None
    patch: Optional[int] = None
    extra: Optional[str] = None

    def to_string(self) -> str:
        parts = str(self.major)
        if self.minor is not None:
            parts += f".{self.minor}"
            if self.patch is not None:
                parts += f".{self.patch}"
        if self.extra:
            parts += f"-{self.extra}"
        return parts


@dataclass
class SemanticVersionDiff:
    kind: DiffKind
    diff: int


@dataclass
class UsageEntry:
    """Single (version, event_count, release_date) tuple for an SDK."""

    lib_version: str
    count: int
    max_timestamp: str
    release_date: Optional[str] = None
    is_latest: bool = False


@dataclass
class ReleaseAssessment:
    """Per-version outdatedness assessment (corresponds to AugmentedTeamSdkVersionsInfoRelease)."""

    version: str
    count: int
    max_timestamp: str
    release_date: Optional[str]
    days_since_release: Optional[int]
    released_ago: Optional[str]
    is_outdated: bool
    is_old: bool
    needs_updating: bool
    is_current_or_newer: bool
    status_reason: str
    sql_query: str
    activity_page_url: str


@dataclass
class OutdatedTrafficAlert:
    version: str
    threshold_percent: float


@dataclass
class SdkAssessment:
    """Per-SDK health assessment (corresponds to AugmentedTeamSdkVersionsInfo entry)."""

    lib: str
    readable_name: str
    latest_version: str
    needs_updating: bool
    is_outdated: bool
    is_old: bool
    severity: Severity
    reason: str
    banners: list[str] = field(default_factory=list)
    releases: list[ReleaseAssessment] = field(default_factory=list)
    outdated_traffic_alerts: list[OutdatedTrafficAlert] = field(default_factory=list)


@dataclass
class SdkHealthReport:
    """Top-level report returned to agents / frontend."""

    overall_health: OverallHealth
    needs_updating_count: int
    team_sdk_count: int
    health: Literal["success", "warning", "danger"]
    sdks: list[SdkAssessment] = field(default_factory=list)


# --- Semver parsing / diffing (mirrors frontend/src/lib/utils/semver.ts) ---

_SEMVER_RE: Pattern[str] = re_compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def parse_version(version: str) -> SemanticVersion:
    """Parse a semver-like string. Raises ValueError on invalid input.

    Mirrors frontend/src/lib/utils/semver.ts: JavaScript's `split('-', 2)` returns at most
    the first two splits and discards the rest, so "1.2.3-beta-2" becomes `extra="beta"`.
    We achieve parity by splitting on every '-' and taking only the second segment.
    """
    parts = version.split("-")
    core = parts[0]
    extra = parts[1] if len(parts) > 1 else None

    match = _SEMVER_RE.match(core)
    if not match:
        raise ValueError(f"Invalid semver string: {version}")

    major_str, minor_str, patch_str = match.groups()
    return SemanticVersion(
        major=int(major_str),
        minor=int(minor_str) if minor_str is not None else None,
        patch=int(patch_str) if patch_str is not None else None,
        extra=extra,
    )


def try_parse_version(version: str) -> Optional[SemanticVersion]:
    try:
        return parse_version(version)
    except ValueError:
        return None


def diff_versions(a: SemanticVersion, b: SemanticVersion) -> Optional[SemanticVersionDiff]:
    """Return the first-differing component as a kind+diff, or None if equal."""
    if a.major != b.major:
        return SemanticVersionDiff(kind="major", diff=a.major - b.major)
    if a.minor != b.minor:
        return SemanticVersionDiff(kind="minor", diff=(a.minor or 0) - (b.minor or 0))
    if a.patch != b.patch:
        return SemanticVersionDiff(kind="patch", diff=(a.patch or 0) - (b.patch or 0))
    if a.extra != b.extra:
        if a.extra and b.extra:
            # Simple string comparison to match frontend behavior (localeCompare-ish)
            return SemanticVersionDiff(kind="extra", diff=(1 if a.extra > b.extra else -1))
        if a.extra:
            return SemanticVersionDiff(kind="extra", diff=-1)
        if b.extra:
            return SemanticVersionDiff(kind="extra", diff=1)
    return None


# --- Age / device helpers --------------------------------------------------


def _calculate_version_age_days(release_date_iso: str, now: Optional[datetime] = None) -> int:
    """Days between release_date and now. Matches frontend's Math.floor((now - release) / day)."""
    release = datetime.fromisoformat(release_date_iso.replace("Z", "+00:00"))
    if release.tzinfo is None:
        release = release.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    seconds = (current - release).total_seconds()
    return int(seconds // 86400)


def _decode_redis_json(raw: bytes | str) -> dict:
    return json_loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def _load_github_sdk_data() -> dict[str, dict]:
    """Load latest SDK versions from Redis for all known SDK types."""
    redis_client = get_client()
    keys = [github_sdk_versions_key(sdk_type) for sdk_type in SDK_TYPES]
    values = redis_client.mget(keys)

    data: dict[str, dict] = {}
    for sdk_type, raw in zip(SDK_TYPES, values):
        if not raw:
            continue
        parsed = _decode_redis_json(raw)
        if "latestVersion" in parsed:
            data[sdk_type] = parsed
    return data


SDK_FRESHNESS_GRACE_PERIOD_DAYS = 7


@cache_for(timedelta(seconds=60))
def sdks_within_freshness_grace_period() -> set[str]:
    """Return SDK names whose latest published version is younger than the grace period."""
    try:
        github_data = _load_github_sdk_data()
    except (RedisError, ValueError, TypeError):
        return set()

    fresh: set[str] = set()
    for sdk_type, data in github_data.items():
        try:
            release_date = (data.get("releaseDates") or {}).get(data["latestVersion"])
            if release_date and _calculate_version_age_days(release_date) < SDK_FRESHNESS_GRACE_PERIOD_DAYS:
                fresh.add(sdk_type)
        except (ValueError, TypeError, AttributeError):
            continue
    return fresh


def _device_context(sdk_type: str) -> Literal["mobile", "desktop", "mixed"]:
    if sdk_type in MOBILE_SDKS:
        return "mobile"
    if sdk_type in DESKTOP_SDKS:
        return "desktop"
    return "mixed"


def _traffic_threshold(sdk_type: str) -> float:
    if sdk_type == "web":
        return SIGNIFICANT_TRAFFIC_THRESHOLD_WEB
    return SIGNIFICANT_TRAFFIC_THRESHOLD_DEFAULT


def _released_ago(release_date_iso: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """Mirror of `dayjs(release_date).fromNow()` used in the frontend (e.g. "5 months ago")."""
    if not release_date_iso:
        return None
    try:
        release = datetime.fromisoformat(release_date_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if release.tzinfo is None:
        release = release.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return humanize.naturaltime(current - release)


# --- UI-parity string/URL builders -----------------------------------------
#
# These mirror the copy and link construction in
# frontend/src/scenes/onboarding/sdks/SdkDoctorComponents.tsx and
# frontend/src/scenes/onboarding/sdks/SdkDoctorScene.tsx.
# Keep these in sync when UI copy or the Activity/SQL URL shape changes.


def _build_status_reason(is_outdated: bool, is_current_or_newer: bool, released_ago: Optional[str]) -> str:
    """
    Per-version tooltip text mirroring the three badge states in SdkDoctorComponents.tsx:149-196.

    - Outdated (danger): "Released {ago}. Upgrade recommended." or "Upgrade recommended"
    - Current (success): "You have the latest available. Click 'Releases ↗' above to check for any since."
    - Recent  (warning): "Released {ago}. Upgrading is a good idea, but it's not urgent yet." (or without prefix)
    """
    if is_outdated:
        return f"Released {released_ago}. Upgrade recommended." if released_ago else "Upgrade recommended"
    if is_current_or_newer:
        return "You have the latest available. Click 'Releases ↗' above to check for any since."
    if released_ago:
        return f"Released {released_ago}. Upgrading is a good idea, but it's not urgent yet."
    return "Upgrading is a good idea, but it's not urgent yet"


# Strict allowlist for values interpolated into SQL and URLs — matches the shape of
# SDK identifiers and semver strings only, rejects everything else (quotes, whitespace,
# control chars, SQL/HTML metacharacters). `lib` and `lib_version` originate from event
# properties sent by instrumented apps, so treat them as untrusted input.
_SAFE_INTERPOLATION_RE: Pattern[str] = re_compile(r"^[A-Za-z0-9._+\-]+$")


def _is_safe_for_interpolation(value: str) -> bool:
    return bool(value) and bool(_SAFE_INTERPOLATION_RE.match(value))


def _build_sql_query(sdk_type: str, version: str) -> str:
    """
    Matches queryForSdkVersion() in SdkDoctorComponents.tsx.

    Returns an empty string when either `sdk_type` or `version` fails validation —
    the skill instructs agents to surface the unexpected empty value rather than retry
    or patch in their own values, which closes the injection path via execute-sql.
    """
    if not _is_safe_for_interpolation(sdk_type) or not _is_safe_for_interpolation(version):
        return ""
    # Plain string interpolation (NOT parameterized) is intentional: the allowlist above
    # is the single security boundary for this surface. A well-meaning "fix" to use
    # psycopg.sql.SQL or similar would produce the wrong string for ClickHouse/HogQL, and
    # `posthog:execute-sql` parameterizes on its end anyway. The MCP agent receives the
    # raw SQL as a string to display or pipe to execute-sql — not as a prepared statement.
    return (
        "SELECT * FROM events WHERE timestamp >= NOW() - INTERVAL 7 DAY "
        f"AND properties.$lib = '{sdk_type}' AND properties.$lib_version = '{version}' "
        "ORDER BY timestamp DESC LIMIT 50"
    )


def _build_activity_page_url(project_id: Optional[int], sdk_type: str, version: str) -> str:
    """
    Matches activityPageUrlForSdkVersion() in SdkDoctorComponents.tsx.

    Returns a relative path (no host) including /project/<id>/ prefix so MCP agents
    can combine it with the user's known PostHog host (e.g. us.posthog.com).

    Returns an empty string when either `sdk_type` or `version` fails validation —
    consistent with _build_sql_query, keeps the pair either both-populated or
    both-empty so the skill's "if empty, surface it" guidance applies uniformly.
    """
    if not _is_safe_for_interpolation(sdk_type) or not _is_safe_for_interpolation(version):
        return ""
    query: dict[str, Any] = {
        "kind": "DataTableNode",
        "columns": [
            "*",
            "event",
            "person_display_name -- Person",
            "coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen",
            "properties.$lib",
            "timestamp",
        ],
        "hiddenColumns": [],
        "pinnedColumns": [],
        "source": {
            "kind": "EventsQuery",
            "select": [
                "*",
                "timestamp",
                "properties.$lib",
                "properties.$lib_version",
                "event",
                "person_display_name -- Person",
                "coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen",
            ],
            "orderBy": ["timestamp DESC"],
            "after": "-7d",
            "properties": [
                {"key": "$lib", "value": [sdk_type], "operator": "exact", "type": "event"},
                {"key": "$lib_version", "value": [version], "operator": "exact", "type": "event"},
            ],
        },
        "context": {"type": "team_columns"},
        "allowSorting": True,
        "embedded": False,
        "expandable": True,
        "full": True,
        "propertiesViaUrl": True,
        "showActions": True,
        "showColumnConfigurator": True,
        "showCount": False,
        "showDateRange": True,
        "showElapsedTime": False,
        "showEventFilter": True,
        "showEventsFilter": False,
        "showExport": True,
        "showHogQLEditor": True,
        "showOpenEditorButton": True,
        "showPersistentColumnConfigurator": True,
        "showPropertyFilter": True,
        "showRecordingColumn": False,
        "showReload": True,
        "showResultsTable": True,
        "showSavedFilters": False,
        "showSavedQueries": True,
        "showSearch": True,
        "showSourceQueryOptions": True,
        "showTableViews": False,
        "showTestAccountFilters": True,
        "showTimings": False,
    }
    # `separators=(",",":")` is load-bearing: the frontend emits URLs via `JSON.stringify`
    # (no whitespace between separators). Python's default `json.dumps` uses `(', ', ': ')`
    # which would encode spaces as %20 and diverge byte-for-byte from the frontend's URL.
    # `kea-router` parses either form, but byte-identical URLs are what lets us claim true
    # UI parity. `safe="!*'()"` matches JS's `encodeURIComponent`, which does not encode
    # these four characters but DOES encode everything else (including space, `/`, `?`, `#`).
    encoded_q = quote(json_dumps(query, separators=(",", ":")), safe="!*'()")
    prefix = f"/project/{project_id}" if project_id is not None else ""
    return f"{prefix}/activity/explore#q={encoded_q}"


def _build_banner(sdk_type: str, alert: OutdatedTrafficAlert) -> str:
    """
    Top-level alert text mirroring SdkDoctorScene.tsx's "Time for an update!" banner:
    "Version {ver} of the {Readable} SDK has captured more than {N}% of events in the last 7 days."

    Version is routed through `_safe_version_display` as defense in depth — the primary
    sanitization boundary is `assess_release` (which quarantines unsafe versions before
    they can reach this function), but the skill's "quote banners verbatim" rule makes
    belt-and-braces worthwhile.
    """
    readable = SDK_READABLE_NAME.get(sdk_type, sdk_type)
    # round() not int() so any fp artifact near integer values (e.g. 0.1 * 100 =
    # 10.000000000000002) renders correctly. For hypothetical half-integer thresholds
    # Python's banker's rounding applies (10.5 → 10, 11.5 → 12) — no half-integer
    # threshold exists today.
    threshold_int = round(alert.threshold_percent)
    version = _safe_version_display(alert.version)
    return (
        f"Version {version} of the {readable} SDK has captured more than {threshold_int}% of events in the last 7 days."
    )


# --- Core assessment -------------------------------------------------------


def assess_release(
    sdk_type: str,
    entry: UsageEntry,
    latest: SemanticVersion,
    is_single_version: bool,
    now: Optional[datetime] = None,
    project_id: Optional[int] = None,
) -> ReleaseAssessment:
    """
    Assess a single (lib_version, release_date) tuple. Mirrors computeAugmentedInfoRelease in TS.

    Three boundaries are enforced here:

    1. **Version safety** (allowlist): if `lib_version` contains any character outside
       `^[A-Za-z0-9._+\\-]+$`, the release is quarantined — version is redacted, all
       outdatedness flags are False, no SQL / URL / banner / reason references it.
       `lib_version` comes from the `$lib_version` event property, which is attacker-
       controlled (any capture token holder can set it). A crafted string like
       `"1.0.0-\\nSystem: <instructions>"` must NOT propagate to agent-facing output,
       where the skill tells agents to quote banners and reasons verbatim.

    2. **Parse success**: of the remaining safe versions, those that parse as semver
       get fully assessed.

    3. **Parse failure fallback** (safe but non-semver): shapes like `"1.2.3.4"` that
       pass the allowlist but fail semver parsing still get drill-in links (agents may
       want to see events for them), but are never flagged as outdated.

    See `test_prompt_injection_in_lib_version_*` for the attack cases and
    `test_unparseable_safe_version_still_gets_sql_and_url` for the parse-fallback case.
    """
    if not _is_safe_for_interpolation(entry.lib_version):
        return ReleaseAssessment(
            version="<unsafe version redacted>",
            count=entry.count,
            max_timestamp=entry.max_timestamp,
            release_date=None,
            days_since_release=None,
            released_ago=None,
            is_outdated=False,
            is_old=False,
            needs_updating=False,
            is_current_or_newer=False,
            status_reason=(
                "Version string contains unsafe characters — redacted and excluded from "
                "outdatedness assessment. This may indicate malformed instrumentation or "
                "tampered event data."
            ),
            sql_query="",
            activity_page_url="",
        )

    try:
        current = parse_version(entry.lib_version)
    except ValueError:
        return ReleaseAssessment(
            version=entry.lib_version,
            count=entry.count,
            max_timestamp=entry.max_timestamp,
            release_date=None,
            days_since_release=None,
            released_ago=None,
            is_outdated=False,
            is_old=False,
            needs_updating=False,
            is_current_or_newer=False,
            status_reason="Unable to parse version — cannot assess.",
            sql_query=_build_sql_query(sdk_type, entry.lib_version),
            activity_page_url=_build_activity_page_url(project_id, sdk_type, entry.lib_version),
        )

    diff = diff_versions(latest, current)
    is_current_or_newer = diff is None or diff.diff <= 0

    days_since_release: Optional[int] = None
    is_old = False
    if entry.release_date:
        try:
            days_since_release = _calculate_version_age_days(entry.release_date, now=now)
        except (ValueError, TypeError):
            days_since_release = None
        if days_since_release is not None and diff is not None and diff.diff > 0:
            weeks_old = days_since_release / 7
            age_threshold = (
                AGE_THRESHOLD_DESKTOP_WEEKS if _device_context(sdk_type) == "desktop" else AGE_THRESHOLD_MOBILE_WEEKS
            )
            is_old = weeks_old > age_threshold

    grace_period_days = GRACE_PERIOD_DAYS_WEB if sdk_type == "web" else GRACE_PERIOD_DAYS_OTHER
    is_recent_release = days_since_release is not None and days_since_release < grace_period_days

    is_outdated = False

    if is_single_version and diff is not None and diff.kind != "patch" and days_since_release is not None:
        is_outdated = days_since_release > SINGLE_VERSION_GRACE_PERIOD_DAYS
    elif is_recent_release:
        is_outdated = False
    elif diff is not None and diff.diff > 0:
        if diff.kind == "major":
            is_outdated = True
        elif diff.kind == "minor":
            is_minor_outdated_by_count = diff.diff >= MINOR_VERSIONS_BEHIND_THRESHOLD
            is_minor_outdated_by_age = days_since_release is not None and days_since_release > MINOR_AGE_THRESHOLD_DAYS
            is_outdated = is_minor_outdated_by_count or is_minor_outdated_by_age
        # patch-level differences are never outdated — leave is_outdated = False

    released_ago = _released_ago(entry.release_date, now=now)

    return ReleaseAssessment(
        version=entry.lib_version,
        count=entry.count,
        max_timestamp=entry.max_timestamp,
        release_date=entry.release_date,
        days_since_release=days_since_release,
        released_ago=released_ago,
        is_outdated=is_outdated,
        is_old=is_old,
        needs_updating=is_outdated or is_old,
        is_current_or_newer=is_current_or_newer,
        status_reason=_build_status_reason(is_outdated, is_current_or_newer, released_ago),
        sql_query=_build_sql_query(sdk_type, entry.lib_version),
        activity_page_url=_build_activity_page_url(project_id, sdk_type, entry.lib_version),
    )


def _safe_version_display(version: str) -> str:
    """Defense-in-depth: never echo a raw version into prose unless it passes the allowlist.

    The primary boundary is in `assess_release`, which quarantines unsafe versions to
    `<unsafe version redacted>` before they can reach this function. This fallback exists
    so a future refactor that builds reason/banner text from some other `version` source
    (e.g. direct from a UsageEntry) still fails closed rather than interpolating attacker-
    controlled `$lib_version` bytes into agent-facing copy.
    """
    return version if _is_safe_for_interpolation(version) else "<unsafe version redacted>"


def _build_reason(
    sdk_type: str,
    current_release: ReleaseAssessment,
    latest_version: str,
    outdated_traffic_alerts: list[OutdatedTrafficAlert],
) -> str:
    """Short human-readable explanation for agents / UI."""
    current_version = _safe_version_display(current_release.version)
    latest = _safe_version_display(latest_version)

    if not current_release.needs_updating and not outdated_traffic_alerts:
        return f"{sdk_type} is on {current_version} which matches or exceeds latest {latest}."

    pieces: list[str] = []
    if current_release.is_outdated:
        age = (
            f"{current_release.days_since_release} days old"
            if current_release.days_since_release is not None
            else "age unknown"
        )
        pieces.append(f"Latest in-use version {current_version} is behind {latest} ({age}).")
    elif current_release.is_old:
        pieces.append(
            f"In-use version {current_version} is old ({current_release.days_since_release} days since release)."
        )

    if outdated_traffic_alerts:
        versions = ", ".join(_safe_version_display(a.version) for a in outdated_traffic_alerts)
        threshold = outdated_traffic_alerts[0].threshold_percent
        pieces.append(f"Outdated versions handling >= {threshold:.0f}% of traffic: {versions}.")

    return " ".join(pieces) if pieces else f"{sdk_type} may need attention."


def assess_sdk(
    sdk_type: str,
    latest_version_str: str,
    usage: list[UsageEntry],
    now: Optional[datetime] = None,
    project_id: Optional[int] = None,
) -> Optional[SdkAssessment]:
    """Assess a single SDK's health across all versions in use."""
    if not usage:
        return None

    try:
        latest = parse_version(latest_version_str)
    except ValueError:
        return None

    is_single_version = len(usage) == 1
    releases = [
        assess_release(sdk_type, entry, latest, is_single_version, now=now, project_id=project_id) for entry in usage
    ]

    total_events = sum(r.count for r in releases)

    # Traffic alerts: skip for mobile (users don't auto-update apps)
    outdated_traffic_alerts: list[OutdatedTrafficAlert] = []
    is_mobile = sdk_type in MOBILE_SDKS
    if not is_mobile and total_events > 0:
        threshold = _traffic_threshold(sdk_type)
        threshold_pct = threshold * 100
        outdated_traffic_alerts = [
            OutdatedTrafficAlert(version=r.version, threshold_percent=threshold_pct)
            for r in releases
            if r.is_outdated and r.count / total_events >= threshold
        ]

    has_significant_outdated_traffic = len(outdated_traffic_alerts) > 0
    # First release is the "most recent" one in the usage list (matches frontend assumption)
    primary = releases[0]
    is_outdated = primary.is_outdated or has_significant_outdated_traffic
    is_old = primary.is_old
    needs_updating = is_outdated or is_old

    severity: Severity = "none"
    if needs_updating:
        severity = "warning"

    reason = _build_reason(sdk_type, primary, latest_version_str, outdated_traffic_alerts)
    banners = [_build_banner(sdk_type, a) for a in outdated_traffic_alerts]

    return SdkAssessment(
        lib=sdk_type,
        readable_name=SDK_READABLE_NAME.get(sdk_type, sdk_type),
        latest_version=latest_version_str,
        needs_updating=needs_updating,
        is_outdated=is_outdated,
        is_old=is_old,
        severity=severity,
        reason=reason,
        banners=banners,
        releases=releases,
        outdated_traffic_alerts=outdated_traffic_alerts,
    )


def compute_sdk_health(
    combined_data: dict[str, dict[str, Any]],
    now: Optional[datetime] = None,
    project_id: Optional[int] = None,
) -> SdkHealthReport:
    """
    Top-level entry point. Takes the combined data structure returned by the existing
    /api/sdk_doctor/ view:

        {
          "web": {
            "latest_version": "1.150.0",
            "usage": [
              {"lib_version": "1.150.0", "count": 5234, "max_timestamp": "...",
               "is_latest": true, "release_date": "..."},
              ...
            ]
          },
          ...
        }

    Returns a structured health report that agents can consume directly.
    """
    assessments: list[SdkAssessment] = []
    for sdk_type, data in combined_data.items():
        usage_raw = data.get("usage") or []
        latest_version_str = data.get("latest_version")
        if not latest_version_str or not usage_raw:
            continue

        usage = [
            UsageEntry(
                lib_version=entry["lib_version"],
                count=int(entry.get("count", 0)),
                max_timestamp=entry.get("max_timestamp", ""),
                release_date=entry.get("release_date"),
                is_latest=bool(entry.get("is_latest", False)),
            )
            for entry in usage_raw
        ]

        assessment = assess_sdk(sdk_type, latest_version_str, usage, now=now, project_id=project_id)
        if assessment is not None:
            assessments.append(assessment)

    team_sdk_count = len(assessments)
    needs_updating_count = sum(1 for a in assessments if a.needs_updating)

    # Matches frontend `needsAttention` rule: at least half of SDKs outdated
    needs_attention = team_sdk_count > 0 and needs_updating_count >= ceil(team_sdk_count / 2)

    if needs_attention:
        health: Literal["success", "warning", "danger"] = "danger"
        overall_health: OverallHealth = "needs_attention"
    elif needs_updating_count >= 1:
        health = "warning"
        overall_health = "needs_attention"
    else:
        health = "success"
        overall_health = "healthy"

    # When needs_attention is true, escalate severity of updating SDKs to danger to mirror the UI's
    # behavior of surfacing a red banner when the bulk of the team's SDKs are outdated.
    if needs_attention:
        for a in assessments:
            if a.needs_updating:
                a.severity = "danger"

    return SdkHealthReport(
        overall_health=overall_health,
        needs_updating_count=needs_updating_count,
        team_sdk_count=team_sdk_count,
        health=health,
        sdks=assessments,
    )
