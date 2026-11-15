import operator
import functools
import dataclasses
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Case, Count, Q, Value, When
from django.utils import timezone

from posthog.dataclasses import frozen

from products.error_tracking.backend.facade.contracts import MissingSymbolsReason
from products.error_tracking.backend.models import ErrorTrackingStackFrame

from .base import Recommendation

# Don't fire the recommendation unless we have a meaningful sample.
# Tiny teams with a couple of errors shouldn't get a noisy card.
MIN_SAMPLE_FRAMES = 10

# Flag a platform when more than this fraction of its recent frames that need symbols are missing them.
UNRESOLVED_THRESHOLD = 0.30

LOOKBACK_HOURS = 24

PLATFORM_LABELS: dict[str, tuple[str, str]] = {
    "javascript": ("JavaScript", "source maps"),
    "java": ("Android", "mapping files"),
    "native": ("iOS and native", "debug symbols"),
}

# Name this in READ_REPLICA_OPT_IN to run the frame counts on the read replica.
READ_REPLICA_OPT_IN_KEY = "error_tracking_source_maps"


def _resolve_failure_starts_with(*prefixes: str) -> Q:
    condition = Q()
    for prefix in prefixes:
        condition |= Q(contents__resolve_failure__startswith=prefix)
    return condition


@frozen
class _MissingSymbolsRule:
    reason: MissingSymbolsReason
    prefixes: tuple[str, ...]
    condition: Q = dataclasses.field(default_factory=Q)

    @property
    def query(self) -> Q:
        return _resolve_failure_starts_with(*self.prefixes) & self.condition


# Each prefix matches the error text cymbal stores in `contents.resolve_failure` (the `Display`
# strings in rust/cymbal/src/core/error.rs), so a reworded error there silently drops out of this match.
# A JavaScript frame with no chunk ID still counts when we found no source map for it, because the
# CLI would inject a chunk ID into that file and upload its map. This also counts third-party
# scripts that will never have a source map, because a single frame cannot tell them apart.
MISSING_SYMBOLS_RULES: tuple[_MissingSymbolsRule, ...] = (
    # Cymbal looks up the chunk before it checks the column. A frame with no column has no position
    # to map, so an upload only passes it through unresolved.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.CHUNK_NOT_UPLOADED,
        prefixes=("No sourcemap uploaded for chunk id: ",),
        condition=Q(contents__has_key="column"),
    ),
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.NO_SOURCE_MAP_LINKED, prefixes=("Could not find sourcemap for source url: ",)
    ),
    # These 4xx codes are the server's final answer. A 400 or 407 is not: cymbal's egress proxy
    # answers 407 for localhost, and 400s come from third-party scripts.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.FILE_NOT_REACHABLE,
        prefixes=tuple(f"HTTP error {status} while fetching: " for status in (401, 403, 404, 410)),
    ),
    # A map that does not parse is most often a server that answers a missing `.map` with its HTML page.
    _MissingSymbolsRule(reason=MissingSymbolsReason.INVALID_SOURCE_MAP, prefixes=("Invalid source map: ",)),
    # The fetch limit is lower than the upload limit, so an upload resolves a file that is too big to fetch.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.TOO_LARGE_TO_FETCH,
        prefixes=("Network error while fetching: Response from ",),
    ),
    # A frame with no column has nothing to look up, `InternalBytecode.js` is the Hermes engine's own
    # code, and an http(s) source is a bundle from the Metro dev server.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.BUNDLE_NOT_INJECTED,
        prefixes=("No chunk id sent with frame",),
        condition=Q(contents__has_key="column")
        & ~Q(contents__source__endswith="InternalBytecode.js")
        & ~Q(contents__source__startswith="http://")
        & ~Q(contents__source__startswith="https://"),
    ),
    # Android framework classes live on the device, not in the app, so no uploaded mapping covers them.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.MAPPING_NOT_UPLOADED,
        prefixes=("No proguard map uploaded for id: ",),
        condition=~Q(
            contents__module__regex=r"^(android|java|javax|dalvik|libcore|sun|com\.android|org\.json|org\.xml|org\.w3c|org\.apache\.http)\."
        ),
    ),
    # System libraries miss debug symbols too, but nobody can upload those, and they are not in_app.
    # An Xcode `.debug.dylib` image is a dev build.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.DSYM_NOT_UPLOADED,
        prefixes=("No dSYM uploaded for debug_id: ",),
        condition=Q(contents__in_app=True)
        & (Q(contents__module__isnull=True) | ~Q(contents__module__endswith=".debug.dylib")),
    ),
    # A native frame with a line number is already readable, because the SDK resolved it on the client.
    _MissingSymbolsRule(
        reason=MissingSymbolsReason.DEBUG_SYMBOLS_NOT_UPLOADED,
        prefixes=("No debug symbols uploaded for debug_id: ",),
        condition=Q(contents__in_app=True) & ~Q(contents__has_key="line"),
    ),
)

MISSING_SYMBOLS = Q(resolved=False) & functools.reduce(operator.or_, (rule.query for rule in MISSING_SYMBOLS_RULES))

# Frames whose code needs symbols to be readable: the ones resolved with a symbol set, plus the ones
# missing it. Python frames and unminified JavaScript resolve without symbols, so they stay out. A
# resolved frame that kept a failure text resolved without symbols, even when it links to the failed set.
# A JavaScript frame that cymbal resolved through the URL fallback has no symbol set link, because
# cymbal stores that set under the URL and looks it up under the chunk ID. It has a column from the
# source map. A Node.js frame that cymbal passed through keeps its line but has no column, and a
# frame without location information has neither.
NEEDS_SYMBOLS = (
    Q(resolved=True)
    & ~Q(contents__has_key="resolve_failure")
    & (Q(symbol_set__isnull=False) | Q(contents__lang="javascript", contents__has_key="column"))
) | MISSING_SYMBOLS

# Each platform is scored on its own, so good coverage on one platform cannot hide missing symbols on another.
PLATFORM = Case(
    When(contents__lang="javascript", then=Value("javascript")),
    When(contents__lang="java", then=Value("java")),
    default=Value("native"),
)


def frames_database() -> str:
    if READ_REPLICA_OPT_IN_KEY in settings.READ_REPLICA_OPT_IN and "replica" in settings.DATABASES:
        return "replica"
    return "default"


class SourceMapsRecommendation(Recommendation):
    type = "source_maps"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        since = timezone.now() - timedelta(hours=LOOKBACK_HOURS)
        counts_by_team: dict[int, dict[str, dict[str, int]]] = {
            team_id: {platform: {"total": 0, "unresolved": 0} for platform in PLATFORM_LABELS} for team_id in team_ids
        }

        # The rules read `contents`, so Postgres reads every frame of the window from the heap. No
        # covering index helps here: recent frames sit on pages that vacuum has not marked
        # all-visible yet, so an index-only scan fetches the heap for them anyway.
        rows = (
            ErrorTrackingStackFrame.objects.using(frames_database())
            .filter(NEEDS_SYMBOLS, team_id__in=team_ids, created_at__gte=since)
            .annotate(platform=PLATFORM)
            .values("team_id", "platform")
            .annotate(total=Count("id"), unresolved=Count("id", filter=Q(resolved=False)))
        )
        for row in rows:
            counts_by_team[row["team_id"]][row["platform"]] = {"total": row["total"], "unresolved": row["unresolved"]}

        return {team_id: self._build_meta(counts_by_team[team_id]) for team_id in team_ids}

    @staticmethod
    def _build_meta(counts_by_platform: dict[str, dict[str, int]]) -> dict[str, Any]:
        platforms = {
            platform: {
                "total_frames": counts["total"],
                "unresolved_frames": counts["unresolved"],
                "unresolved_pct": counts["unresolved"] / counts["total"] if counts["total"] else 0.0,
            }
            for platform, counts in counts_by_platform.items()
        }
        # The top-level counts are the worst platform with a meaningful sample, so `is_completed` and
        # every surface that shows one percentage report the platform that needs attention. With no
        # such platform, they fall back to the platform with the most frames.
        sampled = [platform for platform, stats in platforms.items() if stats["total_frames"] >= MIN_SAMPLE_FRAMES]
        with_frames = [platform for platform, stats in platforms.items() if stats["total_frames"]]
        worst = (
            max(sampled, key=lambda p: (platforms[p]["unresolved_pct"], platforms[p]["total_frames"]))
            if sampled
            else max(with_frames, key=lambda p: platforms[p]["total_frames"])
            if with_frames
            else None
        )
        top = platforms[worst] if worst else {"total_frames": 0, "unresolved_frames": 0, "unresolved_pct": 0.0}

        return {
            **top,
            "platform": worst,
            "platforms": platforms,
            "threshold_pct": UNRESOLVED_THRESHOLD,
            "min_sample_frames": MIN_SAMPLE_FRAMES,
            "lookback_hours": LOOKBACK_HOURS,
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        total = meta.get("total_frames") or 0
        if total < MIN_SAMPLE_FRAMES:
            return True
        unresolved_pct = meta.get("unresolved_pct") or 0.0
        threshold = meta.get("threshold_pct") or UNRESOLVED_THRESHOLD
        return unresolved_pct <= threshold
