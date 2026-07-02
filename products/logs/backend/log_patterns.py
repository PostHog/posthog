import os
import re
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from products.logs.backend.vendor.drain3 import Drain, LogMasker, MaskingInstruction

_ERROR_SEVERITIES = {"error", "fatal"}

# Masking collapses high-cardinality variable tokens into named placeholders before
# clustering, so templates stay readable ("<ip>", "<num>") instead of fragmenting into
# one cluster per distinct value. Order matters — Drain applies these in sequence, so
# more-specific patterns (uuid, ip, hex) run before the catch-all number mask.
_MASKING_INSTRUCTIONS = [
    MaskingInstruction(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "uuid"),
    MaskingInstruction(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "ip"),
    MaskingInstruction(r"\b0x[0-9a-fA-F]+\b", "hex"),
    MaskingInstruction(r"\b[0-9a-fA-F]{16,}\b", "hex"),
    MaskingInstruction(r"\b\d+\b", "num"),
]

_WHITESPACE_RE = re.compile(r"\s+")


_T = TypeVar("_T", int, float)


def _env(name: str, default: _T, cast: Callable[[str], _T]) -> _T:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class LogSample:
    body: str
    severity_text: str
    service_name: str
    timestamp: dt.datetime


@dataclass
class MinedPattern:
    pattern: str
    count: int
    volume_share_pct: float
    error_count: int
    first_seen: dt.datetime
    last_seen: dt.datetime
    examples: list[str]
    services: list[str]


@dataclass
class _Accumulator:
    template: str
    first_seen: dt.datetime
    last_seen: dt.datetime
    count: int = 0
    error_count: int = 0
    examples: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)


def _prepare_body(body: str, truncate: int) -> str:
    # Collapse newlines / whitespace runs so multi-line bodies (stack traces) mine as a
    # single line, then bound length to keep Drain's parse tree and memory in check.
    return _WHITESPACE_RE.sub(" ", body).strip()[:truncate]


def _build_miner(sim_th: float, depth: int, max_clusters: int) -> tuple[LogMasker, Drain]:
    masker = LogMasker(list(_MASKING_INSTRUCTIONS), "<", ">")
    drain = Drain(
        sim_th=sim_th,
        depth=depth,
        max_clusters=max_clusters,
        param_str="<*>",
        parametrize_numeric_tokens=True,
    )
    return masker, drain


def mine_patterns(
    samples: list[LogSample],
    *,
    max_patterns: int | None = None,
    max_examples: int | None = None,
    max_services: int | None = None,
) -> list[MinedPattern]:
    """Cluster log bodies into templates via Drain3, aggregated per cluster.

    Pure function — no ClickHouse or Django. The caller (query runner) is responsible
    for sampling and for the `scanned_count` / `sampled` metadata.

    Tuning is split deliberately: the output-shape caps (`max_patterns`, `max_examples`,
    `max_services`) are exposed as kwargs so callers and tests can override them per call,
    while the mining params (`LOGS_PATTERNS_BODY_TRUNCATE`, `_SIM_TH`, `_DEPTH`,
    `_MAX_CLUSTERS`) are env-only so ops can retune clustering without a deploy. Each kwarg
    falls back to its `LOGS_PATTERNS_*` env var, then a default.
    """
    if not samples:
        return []

    max_patterns = max_patterns if max_patterns is not None else _env("LOGS_PATTERNS_MAX_PATTERNS", 200, int)
    max_examples = max_examples if max_examples is not None else _env("LOGS_PATTERNS_MAX_EXAMPLES", 3, int)
    max_services = max_services if max_services is not None else _env("LOGS_PATTERNS_MAX_SERVICES", 4, int)
    truncate = _env("LOGS_PATTERNS_BODY_TRUNCATE", 512, int)
    sim_th = _env("LOGS_PATTERNS_SIM_TH", 0.4, float)
    depth = _env("LOGS_PATTERNS_DEPTH", 4, int)
    max_clusters = _env("LOGS_PATTERNS_MAX_CLUSTERS", 1000, int)

    masker, drain = _build_miner(sim_th, depth, max_clusters)
    accumulators: dict[int, _Accumulator] = {}

    for sample in samples:
        prepared = _prepare_body(sample.body, truncate)
        cluster, _change_type = drain.add_log_message(masker.mask(prepared))
        cluster_id = cluster.cluster_id

        acc = accumulators.get(cluster_id)
        if acc is None:
            acc = _Accumulator(
                template=cluster.get_template(),
                first_seen=sample.timestamp,
                last_seen=sample.timestamp,
            )
            accumulators[cluster_id] = acc
        else:
            # Keep the most-evolved template — Drain refines it as more rows merge in.
            acc.template = cluster.get_template()
            if sample.timestamp < acc.first_seen:
                acc.first_seen = sample.timestamp
            if sample.timestamp > acc.last_seen:
                acc.last_seen = sample.timestamp

        acc.count += 1
        if sample.severity_text.lower() in _ERROR_SEVERITIES:
            acc.error_count += 1
        if len(acc.examples) < max_examples and prepared not in acc.examples:
            acc.examples.append(prepared)
        if sample.service_name not in acc.services and len(acc.services) < max_services:
            acc.services.append(sample.service_name)

    total = len(samples)
    patterns = [
        MinedPattern(
            pattern=acc.template,
            count=acc.count,
            volume_share_pct=round(acc.count / total * 100, 2),
            error_count=acc.error_count,
            first_seen=acc.first_seen,
            last_seen=acc.last_seen,
            examples=acc.examples,
            services=acc.services,
        )
        for acc in accumulators.values()
    ]
    # Most frequent first; tie-break on template for deterministic ordering.
    patterns.sort(key=lambda p: (-p.count, p.pattern))
    return patterns[:max_patterns]
