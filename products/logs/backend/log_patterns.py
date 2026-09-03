import os
import re
import json
import datetime as dt
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from products.logs.backend.vendor.drain3 import Drain, LogMasker, MaskingInstruction

ERROR_SEVERITIES = {"error", "fatal"}

# Masking collapses high-cardinality variable tokens into named placeholders before
# clustering, so templates stay readable ("<ip>", "<num>") instead of fragmenting into
# one cluster per distinct value. Order matters — Drain applies these in sequence, so
# more-specific patterns (uuid, ip, hex) run before the catch-all number mask.
# Suffixes that make a dotted token a hostname. Deliberately a fixed list rather than
# "any trailing alphabetic label": dotted module paths, logger names, and source files
# ("products.logs.backend", "django_structlog.celery.receivers", "Handler.cpp") are
# otherwise indistinguishable from an FQDN, and masking those eats real literal content.
_HOST_SUFFIXES = (
    "ai",
    "app",
    "bot",
    "cloud",
    "co",
    "com",
    "de",
    "dev",
    "eu",
    "fr",
    "gg",
    "internal",
    "io",
    "jp",
    "local",
    "me",
    "net",
    "nl",
    "org",
    "sh",
    "so",
    "tv",
    "uk",
    "us",
    "xyz",
)
_HOST_LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
# The repeat is bounded to hold down backtracking, not to enforce a DNS limit. Under an
# unbounded repeat, a dotted run that ends in a non-suffix ("a.a.a.<...>.invalid") makes the
# engine retry the whole suffix alternation at every label boundary, from every start position
# the run offers, so the cost grows with the square of the run's length. Every sampled row is
# masked, and only LOGS_PATTERNS_BODY_TRUNCATE bounds how long a run can get, so a body built
# out of single-character labels turns into real CPU. A dotted run with more labels than this
# masks its tail and keeps its head literal, which no real hostname is long enough to reach.
_HOST_MAX_LABELS_BEFORE_SUFFIX = 8
_HOST_PATTERN = rf"\b(?:{_HOST_LABEL}\.){{1,{_HOST_MAX_LABELS_BEFORE_SUFFIX}}}(?:{'|'.join(_HOST_SUFFIXES)})\b"

_MASKING_INSTRUCTIONS = [
    # Timestamp must precede the number catch-all: \b never matches between a digit and
    # a letter, so "12T08" and "397557Z" in ISO-8601 bodies would survive \b\d+\b intact.
    MaskingInstruction(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "timestamp"),
    # klog / glog headers ("I0812 15:41:23.951822") carry no year and no separators, so the
    # ISO pattern misses them and the date survives as a literal. The severity letter stays
    # outside the mask, since it is content rather than a variable. The form gets its own
    # placeholder: folded into <timestamp>, every ISO pivot would also accept a bare
    # "NNNN HH:MM:SS" pair, such as a count followed by a time of day.
    MaskingInstruction(r"(?<=\b[IWEF])\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?", "klogtime"),
    MaskingInstruction(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "uuid"),
    # A dotted quad after "<letter>/" is a version, not an address ("Chrome/139.0.0.0"), and
    # a \b-bounded match claims it as an <ip>. The guard keys on the letter so an address in
    # a URL, which follows "//" or ":", still masks. The "." guards keep the mask off the
    # tail and head of a longer dotted run such as "1.2.3.4.5", and only a "." that carries
    # on the run blocks the match, so a sentence-final address still masks.
    MaskingInstruction(r"(?<![A-Za-z]/)(?<![\w.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\w)(?!\.\d)", "ip"),
    # Dotted version numbers ("Chrome/139.0.0.0", "HTTP/1.1") otherwise split into one <num>
    # per part, which buries the literal content of a user-agent or protocol template. The
    # "/" is required: it separates a version from a plain decimal such as "duration=1.5".
    # The part count is unbounded so a longer release such as "build/1.2.3.4.5" collapses
    # whole, instead of leaving a "<version>.<num>" tail on a template of its own.
    # Runs after ip so an address in a URL is already masked and cannot look like a version.
    MaskingInstruction(r"(?<=/)\d+(?:\.\d+)+", "version"),
    # Host runs after ip (a dotted quad has no alphabetic suffix, so it stays an <ip>) and
    # before hex, which would otherwise claim a long hex-looking label.
    MaskingInstruction(_HOST_PATTERN, "host"),
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
    "<timestamp>": r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
    "<klogtime>": r"\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?",
    "<uuid>": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "<ip>": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
    "<version>": r"\d+(?:\.\d+)+",
    # Reuses the masking pattern so the pivot cannot claim dotted code paths the mask
    # deliberately left literal. \b is RE2-safe; only lookaround is not.
    "<host>": _HOST_PATTERN,
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
    # Set on the examples the miner keeps, when `body` covers only a prefix of the raw line.
    # compile_match_regex drops its end anchor for those.
    truncated: bool = False


@dataclass(frozen=True)
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
    # RE2-safe regex over raw bodies, self-validated against the raw bodies of the sampled
    # example rows (not the prepared `examples` — raw lines are what the predicate executes
    # against in ClickHouse); None when the template lacks literal content or validation
    # failed. See compile_match_regex.
    match_regex: str | None
    # Longest literal run in the template — plain-text fallback when match_regex is None.
    match_literal: str | None


@dataclass(frozen=False)
class _Accumulator:
    template: str
    first_seen: dt.datetime
    last_seen: dt.datetime
    count: int = 0
    # Cluster-level, because `examples` is deduped and capped: a truncated sample can be
    # dropped before it lands there, and the end anchor must still come off.
    truncated: bool = False
    examples: list[LogSample] = field(default_factory=list)
    # Raw bodies for the same sampled rows as `examples` — the validation corpus for the
    # match predicates, which execute against raw lines in ClickHouse. Prepared bodies can't
    # play that role once JSON reduction exists: an extracted message is a *substring* of its
    # raw line, so a predicate can match every prepared example yet zero raw rows.
    raw_examples: list[str] = field(default_factory=list)
    # True only while every raw example above was mined from the message field of a JSON body,
    # which is what licenses the unanchored predicate. One prose row merging into the cluster
    # turns it off. See compile_match_regex.
    raw_examples_from_json: bool = True
    services: list[str] = field(default_factory=list)
    bucket_counts: list[int] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _PreparedBody:
    text: str
    truncated: bool
    # True when `text` is a message field lifted out of a JSON body, so it is a substring of the
    # raw line rather than the whole of it. Recorded here because the miner already parsed the
    # body to find out — compile_match_regex needs the same answer, and re-deriving it there
    # would parse every retained example a second time.
    from_json: bool


# Keys checked (in order) for the human-readable message inside a JSON body. Matches Loki's
# pattern-ingester default list plus "event" (structlog's convention); Datadog's JSON
# preprocessing remaps the same core keys (message/msg/log) to the log body.
_JSON_MESSAGE_KEYS = ("message", "msg", "log", "msg_", "_msg", "content", "event")

# Raw example bodies (the predicate validation corpus) are kept at a multiple of the mining
# truncation cap: long enough that predicates over truncated templates still validate against
# realistic raw lines, bounded so a pathological row can't blow up memory.
_RAW_EXAMPLE_CAP_MULTIPLIER = 4


def _prepare_json_body(body: str) -> str | None:
    """Return the message-like field of a JSON log body, or None when there is no such field.

    Drain tokenizes on spaces, so a raw JSON blob is punctuation-glued junk: values sit fused
    to keys and braces where the masking regexes can't isolate them, and every value is
    high-cardinality. The industry norm (Loki's pattern ingester, Datadog's JSON preprocessing,
    Elastic's categorization) is to mine only the message-like field.

    A body carrying no such field falls through to prose mining rather than being rewritten
    into a canonical shape. Mining a rewritten body produces a template describing text that
    appears nowhere in the raw row, so compile_match_regex and extract_match_literal must both
    withhold a predicate, and the pattern cannot be pivoted to the logs behind it. An extracted
    message is exempt because it is a literal substring of the raw row, which is what the
    unanchored variant in compile_match_regex matches against.
    """
    # Shippers (Fluentd, Vector, Docker's json-file driver) sometimes deliver a BOM or
    # leading whitespace before the object — that must not demote the body to prose mining.
    body = body.lstrip("﻿ \t\r\n")
    if not body.startswith("{"):
        return None
    try:
        parsed = json.loads(body)
    # ValueError rather than JSONDecodeError, which subclasses it. A log producer controls the
    # body, and an integer literal past sys.get_int_max_str_digits() raises a plain ValueError
    # from the number parser, which would otherwise fail the whole patterns request with a 500.
    except (ValueError, RecursionError):
        return None
    if not isinstance(parsed, dict):
        return None

    for key in _JSON_MESSAGE_KEYS:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return None


def _prepare_body(body: str, truncate: int) -> _PreparedBody:
    # A JSON body carrying a message field is reduced to it (see _prepare_json_body); every
    # other body, JSON or prose, passes through unchanged.
    # Then collapse newlines / whitespace runs so multi-line bodies (stack traces) mine as a
    # single line, and bound length to keep Drain's parse tree and memory in check.
    message = _prepare_json_body(body)
    from_json = message is not None
    collapsed = _WHITESPACE_RE.sub(" ", body if message is None else message).strip()
    if len(collapsed) <= truncate:
        return _PreparedBody(collapsed, truncated=False, from_json=from_json)
    # Cut back to the last space inside the cap. Drain splits on whitespace, so a mid-word
    # cut hands it a fragment ("(Macinto") that it treats as a literal token, and one long
    # statement then fragments into a cluster per distinct cut point. A body with no space
    # inside the cap has no boundary to cut at, so it still cuts hard.
    head = collapsed[:truncate]
    boundary = head.rfind(" ")
    return _PreparedBody(head[:boundary] if boundary > 0 else head, truncated=True, from_json=from_json)


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


def _literal_runs(template: str) -> list[str]:
    # Stripped, non-empty literal fragments between the template's placeholders.
    return [stripped for literal in _PLACEHOLDER_RE.split(template) if (stripped := literal.strip())]


def extract_match_literal(template: str, raw_examples: list[str]) -> str | None:
    """Longest literal run in a template — the plain-text fallback predicate when the
    compiled regex fails validation. None when the template has no usable literal content,
    or when the literal doesn't actually appear in the pattern's raw lines (an icontains
    filter is executed against raw bodies, so a JSON-escaped or shape-token literal that
    validated against prepared text would silently match nothing)."""
    longest = ""
    for literal in _literal_runs(template):
        if len(literal) > len(longest):
            longest = literal
    if len(longest) < _MIN_LITERAL_CHARS:
        return None
    needle = longest.lower()
    if not raw_examples or not all(needle in raw.lower() for raw in raw_examples):
        return None
    return longest


def pattern_fingerprint(template: str) -> str:
    """Cross-run identity key for a mined template.

    Drain templates are not stable across independent mining runs — sampling and row-order
    differences can widen a placeholder ("User <*> not found" vs "User <num> not found"), so
    matching on the raw template string would false-split the same message across windows.
    Keying on the sorted set of literal runs between placeholders survives that wobble:
    placeholder kind and position drop out, literal content remains. A placeholder inserted
    *inside* a literal run splits it and changes the fingerprint — that is content-level
    divergence, not wobble, so the two templates are correctly treated as different patterns.
    """
    literals = sorted(set(_literal_runs(template)))
    return "\x00".join(literals) if literals else template


def compile_match_regex(
    template: str,
    examples: list[LogSample],
    raw_examples: list[str],
    *,
    truncated: bool | None = None,
    mined_from_json: bool = False,
) -> str | None:
    """Compile a mined template into an RE2-safe regex over raw log bodies, self-validated
    against the raw bodies of the pattern's own sampled rows.

    Returns None rather than an unvalidated predicate: Drain refines templates as rows merge,
    so an early-stored example can diverge from the final template — and a filter that
    silently matches the wrong logs is worse than no filter. Validation runs against *raw*
    bodies because that is what the predicate executes against in ClickHouse. The anchored
    form is tried first (start-anchored; end anchor dropped when the cluster held a truncated
    body). An unanchored fallback applies only when `mined_from_json` holds, where the mined
    message is a substring of its raw row so only the unanchored form can match — prose keeps
    the strict anchoring guarantee, since an unanchored prose predicate would silently match
    mid-line occurrences the anchored form was designed to exclude. A template whose content
    never appears verbatim in the raw lines (canonicalized JSON shapes, messages with
    JSON-escaped characters) fails validation and is withheld.

    Pass `truncated` and `mined_from_json` from the cluster. Falling back to the retained
    examples under-reports truncation, because dedup and the example cap can both drop the
    truncated body, and the miner already knows which rows it extracted a message from, so
    re-deriving that here would parse every retained raw example a second time.
    """
    if not examples or not raw_examples:
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
    core = "".join(parts)

    if truncated is None:
        truncated = any(example.truncated for example in examples)
    anchored = r"^\s*" + core + ("" if truncated else r"\s*$")
    try:
        anchored_re = re.compile(anchored)
        core_re = re.compile(core)
    except re.error:
        return None
    if all(anchored_re.search(raw) for raw in raw_examples):
        return anchored
    # The unanchored form is only honest when every raw example is JSON, because the template is
    # then a substring of each row by construction. A cluster mixing JSON and prose rows would
    # otherwise get an unanchored predicate on the strength of one JSON row, and that predicate
    # matches a prose line wherever the text appears, not just where the statement starts. When a
    # mixed cluster cannot anchor, withholding is the correct outcome.
    if mined_from_json and all(core_re.search(raw) for raw in raw_examples):
        return core
    return None


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
        cluster, _change_type = drain.add_log_message(masker.mask(prepared.text))
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
        acc.truncated = acc.truncated or prepared.truncated
        severity = sample.severity_text.lower()
        acc.severity_counts[severity] = acc.severity_counts.get(severity, 0) + 1
        if len(acc.examples) < max_examples and all(e.body != prepared.text for e in acc.examples):
            acc.examples.append(
                LogSample(
                    body=prepared.text,
                    severity_text=sample.severity_text,
                    service_name=sample.service_name,
                    timestamp=sample.timestamp,
                    truncated=prepared.truncated,
                )
            )
            # A predicate needing content beyond the cap fails validation and is withheld,
            # which is fail-safe.
            acc.raw_examples.append(sample.body[: truncate * _RAW_EXAMPLE_CAP_MULTIPLIER])
            acc.raw_examples_from_json = acc.raw_examples_from_json and prepared.from_json
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
            error_count=sum(acc.severity_counts.get(s, 0) for s in ERROR_SEVERITIES),
            first_seen=acc.first_seen,
            last_seen=acc.last_seen,
            examples=acc.examples,
            services=acc.services,
            bucket_counts=acc.bucket_counts,
            severity_counts=acc.severity_counts,
            match_regex=compile_match_regex(
                acc.template,
                acc.examples,
                acc.raw_examples,
                truncated=acc.truncated,
                mined_from_json=acc.raw_examples_from_json,
            ),
            match_literal=extract_match_literal(acc.template, acc.raw_examples),
        )
        for acc in accumulators.values()
    ]
    # Most frequent first; tie-break on template for deterministic ordering.
    patterns.sort(key=lambda p: (-p.count, p.pattern))
    return patterns[:max_patterns]
