"""Per-project, per-source cap on signal emission.

`emit_signal` checks this gate before any Temporal workflow or LLM call, so one project and source
cannot push an unbounded burst of signals through grouping. Each `(team_id, source_product,
source_type)` has two token buckets: an hourly one and a rolling-day one. A signal must get a token
from both.

Enforcement sits behind `SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG`. With the flag off the gate
still charges the buckets and reports would-drops, but lets every signal through. A would-drop
does not take a token, the same as a real drop, so the dark-launch numbers match what enforcement
would do. The gate fails open when Redis cannot answer, like `quota.py` and `daily_limit.py`.

The caps come from the `SIGNALS_SOURCE_RATE_LIMIT_CAPS_FLAG` payload, read at most once a minute.
A missing or unreadable payload gives `DEFAULT_CAPS`; an invalid entry is skipped and logged. The
payload shape, every key optional:

    {
      "enabled": true,
      "default": {"per_hour": 500, "per_day": 2500},
      "sources": {"linear": {"per_hour": 1500, "per_day": 3000},
                  "error_tracking:issue_created": {"per_hour": 500, "per_day": 2500}},
      "projects": {"US:2": {"default": {...}, "sources": {...}}}
    }

A cap resolves from the most specific match: the project's `product:type`, the project's product, the
project's default, then the same three without the project. Project keys carry the region because
team ids repeat between US and EU. `"enabled": false` turns the gate off: no charge, no would-drops.
"""

import math
import time
import threading
from enum import StrEnum
from typing import Any, TypeGuard

from django.conf import settings

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.token_bucket import BucketUnavailable, Budget, consume, refund

from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG = "signals-source-rate-limit-enforcement"
SIGNALS_SOURCE_RATE_LIMIT_CAPS_FLAG = "signals-source-rate-limit-caps"
# Not a person: the caps flag must serve its payload to this id.
SIGNALS_SOURCE_RATE_LIMIT_CAPS_DISTINCT_ID = "signals_source_rate_limit"
CAPS_CACHE_SECONDS = 60
MAX_CAP = 1_000_000


@frozen
class SourceCap:
    per_hour: int
    # A rolling day rather than a calendar day, which is acceptable for an abuse cap.
    per_day: int

    def hourly_budget(self) -> Budget:
        return Budget(burst=self.per_hour, per_hour=self.per_hour)

    def daily_budget(self) -> Budget:
        return Budget(burst=self.per_day, per_hour=math.ceil(self.per_day / 24))


@frozen
class SourceCaps:
    enabled: bool
    default: SourceCap
    sources: dict[str, SourceCap]
    projects: dict[str, "ProjectCaps"]

    def resolve(self, team_id: int, source_product: str, source_type: str) -> SourceCap:
        keys = (f"{source_product}:{source_type}", source_product)
        project = self.projects.get(_project_key(team_id))
        if project is not None:
            for key in keys:
                if key in project.sources:
                    return project.sources[key]
            if project.default is not None:
                return project.default
        for key in keys:
            if key in self.sources:
                return self.sources[key]
        return self.default


@frozen
class ProjectCaps:
    default: SourceCap | None
    sources: dict[str, SourceCap]


# Sized from 90 days of `signal_emission_started` per project and source type: each cap sits above the
# largest legitimate hour and day seen for that source, so only runaway volume hits it. The exception is
# `error_tracking:issue_created`, which takes the default on purpose: its normal tail (p99.9 about 95 an
# hour, 450 a day) is far below the default, and the projects above it sent up to 17,000 a day.
DEFAULT_CAPS = SourceCaps(
    enabled=True,
    default=SourceCap(per_hour=500, per_day=2500),
    sources={
        # Issue trackers send a whole backlog in one burst when a source is first connected.
        "linear": SourceCap(per_hour=1500, per_day=3000),
        "github": SourceCap(per_hour=1500, per_day=3000),
        "jira": SourceCap(per_hour=1500, per_day=3000),
        "shortcut": SourceCap(per_hour=1500, per_day=3000),
        "replay_vision": SourceCap(per_hour=1500, per_day=5000),
        "llm_analytics:evaluation": SourceCap(per_hour=2000, per_day=5000),
    },
    projects={},
)

_caps_lock = threading.Lock()
_caps_cache: tuple[float, SourceCaps] | None = None

SOURCE_RATE_LIMITED = Counter(
    "signals_source_rate_limited_total",
    "Signals over their per-project, per-source rate cap, by whether the gate dropped them",
    labelnames=["source_product", "window", "enforced"],
)
SOURCE_RATE_CHECK_FAILED_OPEN = Counter(
    "signals_source_rate_check_failed_open_total",
    "Signals source rate checks that could not reach Redis and let the signal through",
)


class SourceRateWindow(StrEnum):
    HOUR = "hour"
    DAY = "day"


def _project_key(team_id: int) -> str:
    return f"{settings.CLOUD_DEPLOYMENT or 'DEV'}:{team_id}"


def _parse_cap(raw: Any, where: str) -> SourceCap | None:
    if not isinstance(raw, dict):
        logger.warning("signals_source_rate_caps_invalid_entry", where=where)
        return None
    per_hour, per_day = raw.get("per_hour"), raw.get("per_day")
    if not (_valid_cap_value(per_hour) and _valid_cap_value(per_day)):
        logger.warning("signals_source_rate_caps_invalid_entry", where=where)
        return None
    return SourceCap(per_hour=per_hour, per_day=per_day)


def _valid_cap_value(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_CAP


def _parse_sources(raw: Any, where: str) -> dict[str, SourceCap]:
    if not isinstance(raw, dict):
        return {}
    parsed = {key: _parse_cap(value, f"{where}.{key}") for key, value in raw.items() if isinstance(key, str)}
    return {key: cap for key, cap in parsed.items() if cap is not None}


def parse_caps(payload: dict | None) -> SourceCaps:
    """Overlay the flag payload on `DEFAULT_CAPS`. Payload sources add to the default sources, key by key."""
    if payload is None:
        return DEFAULT_CAPS
    default = _parse_cap(payload["default"], "default") if "default" in payload else None
    projects: dict[str, ProjectCaps] = {}
    raw_projects = payload.get("projects")
    for key, value in raw_projects.items() if isinstance(raw_projects, dict) else []:
        if not isinstance(value, dict):
            continue
        project_default = _parse_cap(value["default"], f"projects.{key}.default") if "default" in value else None
        projects[str(key)] = ProjectCaps(
            default=project_default, sources=_parse_sources(value.get("sources"), f"projects.{key}.sources")
        )
    return SourceCaps(
        enabled=payload.get("enabled") is not False,
        default=default or DEFAULT_CAPS.default,
        sources={**DEFAULT_CAPS.sources, **_parse_sources(payload.get("sources"), "sources")},
        projects=projects,
    )


def current_caps() -> SourceCaps:
    """The caps in force, from a payload read at most once every `CAPS_CACHE_SECONDS`."""
    global _caps_cache
    now = time.monotonic()
    with _caps_lock:
        if _caps_cache is not None and now - _caps_cache[0] < CAPS_CACHE_SECONDS:
            return _caps_cache[1]
    caps = parse_caps(
        read_flag_payload(SIGNALS_SOURCE_RATE_LIMIT_CAPS_FLAG, SIGNALS_SOURCE_RATE_LIMIT_CAPS_DISTINCT_ID)
    )
    with _caps_lock:
        _caps_cache = (now, caps)
    return caps


def _bucket_key(team_id: int, source_product: str, source_type: str, window: SourceRateWindow) -> str:
    return f"signals:source_rate:{team_id}:{source_product}:{source_type}:{window}"


def source_rate_limit_exceeded(team_id: int, source_product: str, source_type: str) -> SourceRateWindow | None:
    """Charge one signal to the source's buckets. Return the window that is out of tokens, or None.

    The hourly bucket goes first. When the daily bucket then refuses, the hourly token goes back,
    because the signal does not enter the pipeline under enforcement. Blocking Redis I/O; wrap in
    `asyncio.to_thread` from async code.
    """
    caps = current_caps()
    if not caps.enabled:
        return None
    cap = caps.resolve(team_id, source_product, source_type)
    hourly_budget = cap.hourly_budget()
    hourly_key = _bucket_key(team_id, source_product, source_type, SourceRateWindow.HOUR)
    hourly = consume(hourly_key, hourly_budget)
    if isinstance(hourly, BucketUnavailable):
        _record_fail_open(team_id, source_product, source_type, hourly)
        return None
    if not hourly.allowed:
        return SourceRateWindow.HOUR

    daily = consume(_bucket_key(team_id, source_product, source_type, SourceRateWindow.DAY), cap.daily_budget())
    if isinstance(daily, BucketUnavailable):
        _record_fail_open(team_id, source_product, source_type, daily)
        return None
    if not daily.allowed:
        refund(hourly_key, hourly_budget)
        return SourceRateWindow.DAY
    return None


def _record_fail_open(team_id: int, source_product: str, source_type: str, unavailable: BucketUnavailable) -> None:
    logger.warning(
        "signals_source_rate_check_failed_open",
        team_id=team_id,
        source_product=source_product,
        source_type=source_type,
        error=unavailable.error,
    )
    SOURCE_RATE_CHECK_FAILED_OPEN.inc()


def source_rate_limit_enforcement_enabled(organization_id: str) -> bool:
    """Whether the gate drops signals for this org, rather than only reporting would-drops.

    Org-keyed like `self-driving-quota-enforcement`. A flag-read error means no enforcement, so a
    flag outage cannot stop the fleet's signals. Blocking network I/O; wrap in `asyncio.to_thread`.
    """
    try:
        return (
            posthoganalytics.feature_enabled(
                SIGNALS_SOURCE_RATE_LIMIT_ENFORCEMENT_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
            )
            is True
        )
    except Exception:
        logger.warning("signals_source_rate_limit_flag_check_failed", exc_info=True)
        return False


def record_source_rate_limited(source_product: str, window: SourceRateWindow, *, enforced: bool) -> None:
    SOURCE_RATE_LIMITED.labels(source_product=source_product, window=window, enforced=str(enforced).lower()).inc()
