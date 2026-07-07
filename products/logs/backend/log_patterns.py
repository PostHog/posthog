import os
import re
import datetime as dt
from bisect import bisect_right
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

# Raw-text regex fragment for each template placeholder, mirroring _MASKING_INSTRUCTIONS
# (what the mask consumed is what the fragment must match) plus Drain's `<*>` token
# wildcard. Fragments must stay RE2-safe — no lookaround, no backreferences — because the
# compiled predicate executes in ClickHouse's match().
_PLACEHOLDER_PATTERNS = {
    "<*>": r"\S+",
    "<num>": r"\d+",
    "<uuid>": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "<ip>": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
    "<hex>": r"(?:0x[0-9a-fA-F]+|[0-9a-fA-F]{16,})",
}
_PLACEHOLDER_RE = re.compile("|".join(re.escape(p) for p in _PLACEHOLDER_PATTERNS))

# Templates whose literal content is thinner than this compile to uselessly broad
# predicates (worst case "<*> <*> <*>" matches everything), so they get no regex.
_MIN_LITERAL_CHARS = 3


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
    # Sampled rows that produced this pattern; `body` is the prepared (whitespace-collapsed,
    # truncated) form the miner saw, not the raw log line.
    examples: list[LogSample]
    services: list[str]
    # Raw sample counts per caller-supplied time bucket (empty when no buckets given).
    bucket_counts: list[int]
    # Raw sample counts keyed by lowercased severity_text.
    severity_counts: dict[str, int]
    # RE2-safe regex over raw bodies, self-validated against `examples`; None when the
    # template lacks literal content or validation failed. See compile_match_regex.
    match_regex: str | None
    # Longest literal run in the template — plain-text fallback when match_regex is None.
    match_literal: str | None


@dataclass
class _Accumulator:
    template: str
    first_seen: dt.datetime
    last_seen: dt.datetime
    count: int = 0
    examples: list[LogSample] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    bucket_counts: list[int] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)


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


def _escape_literal(text: str) -> str:
    # Template literals carry single spaces (bodies are whitespace-collapsed before mining),
    # but the raw lines this regex will run against may have arbitrary whitespace runs.
    return r"\s+".join(re.escape(token) for token in text.split(" "))


def extract_match_literal(template: str) -> str | None:
    """Longest literal run in a template — the plain-text fallback predicate when the
    compiled regex fails validation. None when the template has no usable literal content."""
    longest = ""
    for literal in _PLACEHOLDER_RE.split(template):
        stripped = literal.strip()
        if len(stripped) > len(longest):
            longest = stripped
    return longest if len(longest) >= _MIN_LITERAL_CHARS else None


def compile_match_regex(template: str, examples: list[LogSample], truncate: int) -> str | None:
    """Compile a mined template into an RE2-safe regex over raw log bodies, self-validated
    against the pattern's own examples.

    Returns None rather than an unvalidated predicate: Drain refines templates as rows merge,
    so an early-stored example can diverge from the final template — and a filter that
    silently matches the wrong logs is worse than no filter. Anchored at the start (leading
    whitespace was stripped before mining); the end anchor is dropped when any example hit
    the mining truncation cap, since the template then only covers a prefix of the raw line.
    """
    if not examples:
        return None
    literals = _PLACEHOLDER_RE.split(template)
    if not any(len(literal.strip()) >= _MIN_LITERAL_CHARS for literal in literals):
        return None

    parts = []
    pos = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        parts.append(_escape_literal(template[pos : match.start()]))
        parts.append(_PLACEHOLDER_PATTERNS[match.group(0)])
        pos = match.end()
    parts.append(_escape_literal(template[pos:]))

    truncated = any(len(example.body) >= truncate for example in examples)
    candidate = r"^\s*" + "".join(parts) + ("" if truncated else r"\s*$")

    try:
        compiled = re.compile(candidate)
    except re.error:
        return None
    # Examples hold prepared bodies, which are valid instances of the raw form the regex
    # targets (collapsed runs still match \s+), so they double as the validation corpus.
    if not all(compiled.search(example.body) for example in examples):
        return None
    return candidate


def _bucket_index(buckets: list[tuple[dt.datetime, dt.datetime]], ts: dt.datetime) -> int | None:
    # Buckets are ordered, non-overlapping, half-open [start, end). bisect on starts finds
    # the only candidate; a timestamp can still fall in a gap between buckets (rows outside
    # the sampled time slices), which is a skip, not an error.
    idx = bisect_right(buckets, ts, key=lambda b: b[0]) - 1
    if idx < 0:
        return None
    start, end = buckets[idx]
    return idx if start <= ts < end else None


def mine_patterns(
    samples: list[LogSample],
    *,
    max_patterns: int | None = None,
    max_examples: int | None = None,
    max_services: int | None = None,
    buckets: list[tuple[dt.datetime, dt.datetime]] | None = None,
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
    max_examples = max_examples if max_examples is not None else _env("LOGS_PATTERNS_MAX_EXAMPLES", 10, int)
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
                bucket_counts=[0] * len(buckets) if buckets else [],
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
        severity = sample.severity_text.lower()
        acc.severity_counts[severity] = acc.severity_counts.get(severity, 0) + 1
        if len(acc.examples) < max_examples and all(e.body != prepared for e in acc.examples):
            acc.examples.append(
                LogSample(
                    body=prepared,
                    severity_text=sample.severity_text,
                    service_name=sample.service_name,
                    timestamp=sample.timestamp,
                )
            )
        if sample.service_name not in acc.services and len(acc.services) < max_services:
            acc.services.append(sample.service_name)
        if buckets:
            bucket_idx = _bucket_index(buckets, sample.timestamp)
            if bucket_idx is not None:
                acc.bucket_counts[bucket_idx] += 1

    total = len(samples)
    patterns = [
        MinedPattern(
            pattern=acc.template,
            count=acc.count,
            volume_share_pct=round(acc.count / total * 100, 2),
            error_count=sum(acc.severity_counts.get(s, 0) for s in _ERROR_SEVERITIES),
            first_seen=acc.first_seen,
            last_seen=acc.last_seen,
            examples=acc.examples,
            services=acc.services,
            bucket_counts=acc.bucket_counts,
            severity_counts=acc.severity_counts,
            match_regex=compile_match_regex(acc.template, acc.examples, truncate),
            match_literal=extract_match_literal(acc.template),
        )
        for acc in accumulators.values()
    ]
    # Most frequent first; tie-break on template for deterministic ordering.
    patterns.sort(key=lambda p: (-p.count, p.pattern))
    return patterns[:max_patterns]
