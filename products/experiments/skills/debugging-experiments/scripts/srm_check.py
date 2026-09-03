#!/usr/bin/env python3
"""Localize a confirmed experiment SRM to assignment-side vs capture-side.

Recomputes each user's variant from PostHog's deterministic flag hash, then decomposes the
observed gap between the recorded split and the configured split into the two halves it can
come from. See "The decisive test" in `pulling-the-data.md` for the full diagnostic.

For each variant, over a sample of n identifiers, with `expected = n * configured_share`:

    recorded - expected  =  (predicted - expected)  +  (recorded - predicted)
      the observed gap        selection component       reassignment component
                              => CAPTURE-side           => ASSIGNMENT-side

That is an identity, not a heuristic. `predicted` is the hash-recomputed variant, so the middle
term measures how skewed the population that got recorded already was, and the right term
measures how much something moved users between arms after assignment. The script reports both
components, each with a significance test, and only names a side when one of them both dominates
the gap and is statistically distinguishable from zero. Otherwise it says so.

Algorithm is byte-exact with the PostHog implementation in
`rust/feature-flags/src/flags/flag_matching.rs` (get_matching_variant) and
`flag_matching_utils.rs` (calculate_hash). Run `--selftest` first — it checks every part a wrong
verdict would come from, and exits non-zero on any mismatch:

    hash pipeline    replayed against the repo's golden vectors
    variant hash key the `{flag_key}.` prefix and the `variant` salt
    variant walk     stored order and the strict `<` bound
    statistics       chi-squared tail against known critical values, Wilson interval
    verdict          synthetic pure-capture and pure-assignment samples route correctly

Stdlib only (hashlib, csv, math, argparse) — no PostHog install required. distinct_ids are
often emails; run this customer-side and paste back only the aggregate lines it prints.

    ./srm_check.py --selftest
    ./srm_check.py --flag-key my-flag --variants-file variants.json --csv exposures.csv

Prefer --variants-file: save the flag's `filters.multivariate.variants` array to a file and pass
the path. Variant keys are only charset-validated in the PostHog UI, not by the API, so a key
reaching you through a ticket can contain shell metacharacters or quotes — keep it out of the
command line entirely rather than trying to quote it. --variants is the convenience form for keys
you have already eyeballed.

The CSV is the export query from the decisive test: a header row plus
`distinct_id,recorded_variant,variants_seen` (override names with --id-col / --variant-col /
--variants-seen-col; `variants_seen` may be absent). The id column must hold the identifier
production hashed: the group key for a group-aggregated flag, or `$device_id` (coalesced to
distinct_id when empty) for a device-ID-bucketed flag (`bucketing_identifier == "device_id"`) —
otherwise the distinct_id. Feeding the wrong identifier fabricates disagreements; the selftested
chance-agreement guard below catches the worst case, but not a subtle one.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass

# 0xfffffffffffffff == 15 hex digits == LONG_SCALE in flag_matching_utils.rs
__LONG_SCALE__ = 0xFFFFFFFFFFFFFFF

# PostHog treats an SRM as real below this p (see the chi-squared section in pulling-the-data.md).
SRM_ALPHA = 0.001
# A component has to carry at least this much of the gap before it names a side on its own.
DOMINANT_SHARE = 2.0 / 3.0


def hash_of(hash_key: str) -> float:
    """The pipeline half of calculate_hash() in flag_matching_utils.rs: first 15 hex
    chars of sha1(hash_key), divided by LONG_SCALE. Deterministic, in [0, 1).

    SHA1 here is a compatibility requirement, not a security choice: it is the hash
    PostHog's flag matcher buckets users with, so this has to reproduce it bit for bit.
    Do not take semgrep's SHA256 autofix — it would still compute a number and still
    print a verdict, just a wrong one, which is the worst failure this script has."""
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 (reproduces flag bucketing, not a signature)
    return int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16) / __LONG_SCALE__


def calculate_hash(prefix: str, identifier: str, salt: str = "") -> float:
    """Mirrors calculate_hash() in flag_matching_utils.rs, which concatenates
    prefix + identifier + salt before hashing."""
    return hash_of(f"{prefix}{identifier}{salt}")


def variant_hash_key(flag_key: str, identifier: str) -> str:
    """The exact string get_hash() feeds to sha1 for the variant walk: the `{flag_key}.`
    prefix, the identifier, then the `variant` salt. The plain rollout gate hashes the
    same identifier with an *empty* salt, and mixing the two is the classic
    reimplementation bug — so --selftest pins this string."""
    return f"{flag_key}.{identifier}variant"


def pick_variant(h: float, variants: list[tuple[str, float]]) -> str | None:
    """Walk the variants in stored order accumulating rollout_percentage / 100; the first
    bound strictly above `h` wins. Mirrors the loop in get_matching_variant(). `variants`
    must be in the flag's stored order — a wrong order inverts the result."""
    cumulative = 0.0
    for name, pct in variants:
        cumulative += pct / 100.0
        if h < cumulative:
            return name
    return None


def variant_for(flag_key: str, identifier: str, variants: list[tuple[str, float]]) -> str | None:
    """Recompute the assigned variant, as get_matching_variant() would."""
    return pick_variant(hash_of(variant_hash_key(flag_key, identifier)), variants)


# --- statistics -------------------------------------------------------------------------------
# Hand-rolled because the sandbox has no numpy/scipy (same constraint as ks2.py in the signals
# skills). Every function here is pinned in --selftest against published critical values.


def _gamma_p_series(s: float, x: float) -> float:
    """Regularized lower incomplete gamma P(s, x) by series expansion; converges for x < s + 1."""
    term = 1.0 / s
    total = term
    for n in range(1, 1000):
        term *= x / (s + n)
        total += term
        if abs(term) < abs(total) * 1e-15:
            break
    return total * math.exp(-x + s * math.log(x) - math.lgamma(s))


def _gamma_q_cf(s: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(s, x) by Lentz continued fraction; for x >= s + 1."""
    tiny = 1e-300
    b = x + 1.0 - s
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h * math.exp(-x + s * math.log(x) - math.lgamma(s))


def chi2_sf(x: float, dof: int) -> float:
    """P(chi-squared with `dof` d.o.f. > x) — the p-value for a goodness-of-fit statistic."""
    if x <= 0 or dof < 1:
        return 1.0
    s, scaled = dof / 2.0, x / 2.0
    return 1.0 - _gamma_p_series(s, scaled) if scaled < s + 1.0 else _gamma_q_cf(s, scaled)


@dataclass(frozen=True)
class GoodnessOfFit:
    """A chi-squared goodness-of-fit outcome: the statistic, its degrees of freedom, and the p."""

    chi2: float
    dof: int
    p: float


@dataclass(frozen=True)
class ConfidenceInterval:
    """A two-sided interval on a proportion, as fractions in [0, 1]."""

    low: float
    high: float


def chi2_gof(observed: dict[str, float], expected: dict[str, float]) -> GoodnessOfFit:
    """Goodness-of-fit of `observed` against `expected`."""
    chi2 = sum((observed.get(key, 0) - exp) ** 2 / exp for key, exp in expected.items() if exp > 0)
    dof = max(len([e for e in expected.values() if e > 0]) - 1, 1)
    return GoodnessOfFit(chi2=chi2, dof=dof, p=chi2_sf(chi2, dof))


def wilson_interval(k: int, n: int, z: float = 1.96) -> ConfidenceInterval:
    """Wilson score interval for k successes in n trials. Beats the normal approximation at the
    extremes, which is exactly where an agreement rate sits."""
    if n <= 0:
        return ConfidenceInterval(low=0.0, high=1.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ConfidenceInterval(
        low=max((center - margin) / denom, 0.0),
        high=min((center + margin) / denom, 1.0),
    )


@dataclass(frozen=True)
class VariantGap:
    """The exact decomposition of one variant's deviation from the configured split."""

    variant: str
    expected: float
    predicted: int
    recorded: int

    @property
    def gap(self) -> float:
        """Observed minus configured — the SRM, as this sample sees it."""
        return self.recorded - self.expected

    @property
    def selection(self) -> float:
        """How far the population that got recorded was already skewed. Capture-side."""
        return self.predicted - self.expected

    @property
    def reassignment(self) -> float:
        """How many identifiers were recorded onto a different arm than the hash assigns."""
        return self.recorded - self.predicted


def decompose(
    recorded_counts: dict[str, int],
    predicted_counts: dict[str, int],
    variants: list[tuple[str, float]],
    total: int,
) -> list[VariantGap]:
    """Split each variant's gap into its selection and reassignment components."""
    share_total = sum(pct for _, pct in variants) or 100.0
    return [
        VariantGap(
            variant=name,
            expected=total * (pct / share_total),
            predicted=predicted_counts.get(name, 0),
            recorded=recorded_counts.get(name, 0),
        )
        for name, pct in variants
    ]


def chance_agreement(variants: list[tuple[str, float]]) -> float:
    """Agreement a recompute would reach by luck alone if it carried no signal — sum of squared
    variant shares. Hashing the wrong identifier (or a flag with experience continuity) lands
    here, so an agreement rate that can't beat it means the test is inapplicable, not that
    assignment is broken."""
    share_total = sum(pct for _, pct in variants) or 100.0
    return sum((pct / share_total) ** 2 for _, pct in variants)


def printable(value: str) -> str:
    """Escape anything non-printable in a variant key before it reaches the report.

    Variant keys are charset-validated in the PostHog UI but not by the API, and the recorded
    values come from the customer's own CSV, so neither is trustworthy. Printed verbatim, a key
    carrying a newline can forge a verdict line in a report an operator reads to pick a
    diagnosis, and one carrying an escape sequence can drive their terminal. Printable
    non-ASCII (a legitimately localized key) survives untouched."""
    return "".join(ch if ch.isprintable() else repr(ch)[1:-1] for ch in value)


def fmt_split(counts: dict[str, float], total: float) -> str:
    if total <= 0:
        return "(empty)"
    return "  ".join(
        f"{printable(name)}={counts.get(name, 0):g} ({100.0 * counts.get(name, 0) / total:.1f}%)" for name in counts
    )


# --- input ------------------------------------------------------------------------------------


def parse_variants(spec: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for part in spec.split(","):
        name, _, pct = part.partition("=")
        if not name or not pct:
            raise ValueError(f"bad --variants entry {part!r}; expected name=pct")
        try:
            out.append((name.strip(), float(pct)))
        except ValueError:
            raise ValueError(f"bad --variants entry {part!r}; {pct!r} is not a number") from None
    return out


def load_variants_file(path: str) -> list[tuple[str, float]]:
    """Read the flag's `filters.multivariate.variants` array straight from a file, preserving
    stored order. Keeps variant keys off the command line — they are charset-validated only in
    the UI, so a key arriving via the API can carry shell metacharacters or quotes.

    Accepts the raw array, or the object that contains it (`multivariate`, or a whole flag)."""
    with open(path) as fh:
        blob = json.load(fh)
    for step in ("filters", "multivariate", "variants"):
        if isinstance(blob, dict) and step in blob:
            blob = blob[step]
    if not isinstance(blob, list) or not blob:
        raise ValueError(f"{path}: expected a non-empty variants array, got {type(blob).__name__}")
    out: list[tuple[str, float]] = []
    for entry in blob:
        if not isinstance(entry, dict) or "key" not in entry:
            raise ValueError(f"{path}: each variant needs a 'key', got {entry!r}")
        out.append((str(entry["key"]), float(entry.get("rollout_percentage", 0))))
    return out


# --- verdict ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    label: str
    lines: list[str]


def judge(
    gaps: list[VariantGap],
    agree: int,
    total: int,
    variants: list[tuple[str, float]],
) -> Verdict:
    """Route on the decomposition, not on a bare agreement threshold.

    Order matters: the chance-agreement guard runs first, because a recompute that carries no
    signal at all (wrong identifier, experience continuity) otherwise reads as a huge
    assignment-side effect — the single most misleading failure this script can have."""
    expected = {g.variant: g.expected for g in gaps}
    recorded = {g.variant: float(g.recorded) for g in gaps}
    predicted = {g.variant: float(g.predicted) for g in gaps}

    recorded_fit = chi2_gof(recorded, expected)
    predicted_fit = chi2_gof(predicted, expected)
    agreement = wilson_interval(agree, total)
    chance = chance_agreement(variants)

    # The arm carrying the most gap is the one to decompose; its two shares sum to exactly 1.
    lead = max(gaps, key=lambda g: abs(g.gap))
    selection_share = lead.selection / lead.gap if lead.gap else 0.0
    reassignment_share = lead.reassignment / lead.gap if lead.gap else 0.0

    detail = [
        f"lead arm:            {printable(lead.variant)} (recorded {lead.recorded} vs expected {lead.expected:.1f},"
        f" gap {lead.gap:+.1f})",
        f"  selection:         {lead.selection:+.1f} ({100.0 * selection_share:.0f}% of the gap)"
        f"  chi2={predicted_fit.chi2:.2f} p={predicted_fit.p:.3g}",
        f"  reassignment:      {lead.reassignment:+.1f} ({100.0 * reassignment_share:.0f}% of the gap)"
        f"  disagreement 95% CI [{100.0 * (1 - agreement.high):.2f}%, {100.0 * (1 - agreement.low):.2f}%]",
    ]

    if agreement.low <= chance:
        return Verdict(
            "INAPPLICABLE",
            detail
            + [
                "",
                f"=> agreement {100.0 * agree / total:.2f}% is not distinguishable from the"
                f" {100.0 * chance:.1f}% a coin",
                "   flip would reach on this split, so the recompute carries no signal. Almost always the",
                "   wrong identifier (group key? $device_id?) or ensure_experience_continuity = true.",
                "   Fix the export or skip this test — do NOT read it as assignment-side.",
            ],
        )

    if recorded_fit.p > SRM_ALPHA:
        return Verdict(
            "NO SRM IN SAMPLE",
            detail
            + [
                "",
                f"=> the sample's own recorded split is consistent with the configured one"
                f" (p={recorded_fit.p:.3g}).",
                "   There is no gap here to localize. Either the sample is too small, the window is wrong,",
                "   or the configured split you passed is not the one that was running.",
            ],
        )

    if selection_share >= DOMINANT_SHARE and predicted_fit.p < SRM_ALPHA:
        return Verdict(
            "CAPTURE",
            detail
            + [
                "",
                f"=> the users who got recorded were already skewed before assignment is considered:"
                f" {100.0 * selection_share:.0f}% of",
                "   the gap is selection. The skew is CAPTURE-side. Work the capture-side causes",
                "   (uneven-split exclusion, capture-by-surface, flag-read-before-load, wrong SDK method).",
            ],
        )

    if reassignment_share >= DOMINANT_SHARE and agreement.high < 1.0:
        return Verdict(
            "ASSIGNMENT",
            detail
            + [
                "",
                "=> the recorded variant disagrees with the hash often enough, and directionally enough,"
                " to account for",
                f"   {100.0 * reassignment_share:.0f}% of the gap. The skew is ASSIGNMENT-side."
                " Work the assignment-side causes",
                "   (bootstrap inheritance, mid-run rehash, forced variant, stale local eval).",
                "   If disagreement clusters on one $lib/surface, start there.",
            ],
        )

    return Verdict(
        "MIXED",
        detail
        + [
            "",
            f"=> neither component carries the gap on its own"
            f" (selection {100.0 * selection_share:.0f}%,"
            f" reassignment {100.0 * reassignment_share:.0f}%).",
            "   Work the larger one first, but do not present either as the single cause. A larger sample",
            "   (drop the LIMIT on the export query) is the cheapest way to separate them.",
        ],
    )


# --- selftest ---------------------------------------------------------------------------------

# Golden vectors from rust/feature-flags/src/flags/flag_matching_utils.rs
# (test_calculate_hash: prefix="holdout-", salt=""). If these fail, the local
# hashing does not match PostHog and any verdict below would be meaningless.
# They cover the sha1 -> first-15-hex -> LONG_SCALE pipeline only.
_GOLDEN = [
    ("some_distinct_id", 0.7270002403585725),
    ("test-identifier", 0.4493881716040236),
    ("example_id", 0.9402003475831224),
    ("example_id2", 0.6292740389966519),
]

# The variant path has no golden vector upstream — the Rust tests assert set membership
# (test_get_matching_variant_with_cache) and a +/-5pp distribution, never a fixed value.
# So pin the two things a reimplementation actually gets wrong, which the vectors above
# cannot see: the `{flag_key}.` prefix and the `variant` salt. A distribution check can't
# stand in for these — a wrong-but-deterministic hash still splits 50/50.
_GOLDEN_VARIANT_KEYS = [
    ("my-flag", "user_1", "my-flag.user_1variant"),
    ("experiment-flag", "some_distinct_id", "experiment-flag.some_distinct_idvariant"),
]

# (hash, stored-order variants, expected) — covers the strict `<` bound, order
# sensitivity, and the sub-100% case that falls through to None.
_WALK_CASES: list[tuple[float, list[tuple[str, float]], str | None]] = [
    (0.0, [("control", 50.0), ("test", 50.0)], "control"),
    (0.4999, [("control", 50.0), ("test", 50.0)], "control"),
    (0.5, [("control", 50.0), ("test", 50.0)], "test"),
    (0.9999, [("control", 50.0), ("test", 50.0)], "test"),
    (0.5, [("test", 50.0), ("control", 50.0)], "control"),
    (0.25, [("a", 10.0), ("b", 30.0), ("c", 60.0)], "b"),
    (0.95, [("a", 10.0), ("b", 30.0), ("c", 60.0)], "c"),
    (0.95, [("a", 10.0), ("b", 30.0)], None),
]

# Published upper-tail critical values: chi2_sf(x, dof) must return alpha.
_CHI2_CASES = [
    (3.841459, 1, 0.05),
    (10.827566, 1, 0.001),
    (5.991465, 2, 0.05),
    (13.815511, 2, 0.001),
    (7.814728, 3, 0.05),
    (16.266236, 3, 0.001),
]

# The worked example in pulling-the-data.md: 832 vs 1123 pins down which split is running.
_SRM_EXAMPLE = [(0.5, 4.66e-11), (0.45, 0.0299), (0.43, 0.693)]

# Untrusted variant keys reach the report from the API and from the customer's CSV. Each case is a
# forge attempt: a newline injecting a fake verdict line, and an ANSI sequence driving the terminal.
_PRINTABLE_CASES = [
    ("control", "control"),
    ("test\n=> the skew is CAPTURE-side", "test\\n=> the skew is CAPTURE-side"),
    ("test\x1b[2J", "test\\x1b[2J"),
    ("control\ttab", "control\\ttab"),
    ("variante_esp\u00e1nol", "variante_esp\u00e1nol"),
]

_EVEN = [("control", 50.0), ("test", 50.0)]

# (label, recorded, predicted, variants, agree, total, expected verdict).
# Pure capture: assignment is perfect (agreement 100%, predicted == recorded) but one arm's
# users were never recorded, so the served population is itself skewed.
# Pure assignment: the population is a clean 50/50 draw, but 120 identifiers were recorded
# onto the other arm.
_VERDICT_CASES: list[tuple[str, dict[str, int], dict[str, int], list[tuple[str, float]], int, int, str]] = [
    ("pure capture", {"control": 500, "test": 300}, {"control": 500, "test": 300}, _EVEN, 800, 800, "CAPTURE"),
    ("pure assignment", {"control": 520, "test": 280}, {"control": 400, "test": 400}, _EVEN, 680, 800, "ASSIGNMENT"),
    # Greptile's case: 2% symmetric override noise beside a large capture skew. The old
    # `pct >= 99.0` cutoff called this ASSIGNMENT-side purely because 98% < 99%.
    ("capture + 2% noise", {"control": 502, "test": 298}, {"control": 500, "test": 300}, _EVEN, 784, 800, "CAPTURE"),
    # Balanced sample: nothing to localize.
    ("no srm", {"control": 400, "test": 400}, {"control": 400, "test": 400}, _EVEN, 800, 800, "NO SRM IN SAMPLE"),
    # Wrong identifier: the recompute is uncorrelated, so agreement sits at the 50% chance rate.
    ("wrong identifier", {"control": 500, "test": 300}, {"control": 400, "test": 400}, _EVEN, 400, 800, "INAPPLICABLE"),
]


def _check(ok: bool, label: str, got: object, want: object) -> bool:
    print(f"  {label:34s} {got!r} {'ok' if ok else f'MISMATCH (want {want!r})'}")
    return ok


def selftest() -> int:
    ok = True

    print("hash pipeline (golden vectors from flag_matching_utils.rs):")
    for ident, expected in _GOLDEN:
        got = calculate_hash("holdout-", ident, "")
        ok &= _check(abs(got - expected) < 1e-12, ident, got, expected)

    print("variant hash key (`{flag_key}.` prefix + `variant` salt):")
    for flag_key, ident, expected_key in _GOLDEN_VARIANT_KEYS:
        got_key = variant_hash_key(flag_key, ident)
        ok &= _check(got_key == expected_key, flag_key, got_key, expected_key)

    print("variant walk (stored order, strict < bound):")
    for h, walk_variants, expected_variant in _WALK_CASES:
        got_variant = pick_variant(h, walk_variants)
        order = ",".join(f"{name}={pct:g}" for name, pct in walk_variants)
        ok &= _check(got_variant == expected_variant, f"h={h:<7g} [{order}]", got_variant, expected_variant)

    print("chi-squared tail (published critical values):")
    for x, dof, alpha in _CHI2_CASES:
        got_p = chi2_sf(x, dof)
        ok &= _check(abs(got_p - alpha) < 1e-5, f"chi2_sf({x}, {dof})", round(got_p, 6), alpha)

    print("chi-squared vs the worked example in pulling-the-data.md (832 vs 1123):")
    for share, expected_p in _SRM_EXAMPLE:
        got_p = chi2_gof({"a": 832, "b": 1123}, {"a": 1955 * share, "b": 1955 * (1 - share)}).p
        rel = abs(got_p - expected_p) / expected_p
        ok &= _check(rel < 0.01, f"split {share:g}", f"{got_p:.3g}", f"{expected_p:.3g}")

    print("Wilson interval (the 99% agreement that used to flip the verdict):")
    ci = wilson_interval(792, 800)
    lo, hi = ci.low, ci.high
    bounds = (round(lo, 4), round(hi, 4))
    ok &= _check(abs(lo - 0.9804) < 1e-3 and abs(hi - 0.9949) < 1e-3, "792/800", bounds, (0.9804, 0.9949))
    ok &= _check(lo < 0.99 < hi, "  straddles the old cutoff", bounds, "0.99 inside")

    print("chance agreement (what a signal-free recompute reaches):")
    for spec, want_chance in ((_EVEN, 0.5), ([("a", 34.0), ("b", 33.0), ("c", 33.0)], 0.3334)):
        got_chance = chance_agreement(spec)
        ok &= _check(abs(got_chance - want_chance) < 1e-3, f"{len(spec)} arms", round(got_chance, 4), want_chance)

    print("printable (untrusted variant keys cannot forge output):")
    for raw, want_out in _PRINTABLE_CASES:
        got_out = printable(raw)
        ok &= _check(got_out == want_out, repr(raw)[:34], got_out, want_out)

    print("verdict routing (synthetic samples):")
    for label, recorded, predicted, spec, agree, total, want in _VERDICT_CASES:
        got_label = judge(decompose(recorded, predicted, spec, total), agree, total, spec).label
        ok &= _check(got_label == want, label, got_label, want)

    print("SELFTEST PASS" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


# --- main -------------------------------------------------------------------------------------


def run(
    flag_key: str,
    variants: list[tuple[str, float]],
    csv_path: str,
    id_col: str,
    variant_col: str,
    variants_seen_col: str,
    include_ambiguous: bool,
) -> int:
    total = agree = ambiguous = 0
    recorded_counts: dict[str, int] = {}
    predicted_counts: dict[str, int] = {}
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        for col in (id_col, variant_col):
            if col not in fields:
                print(f"error: column {col!r} not in CSV header {fields}", file=sys.stderr)
                return 2
        has_seen_col = variants_seen_col in fields
        for row in reader:
            # An identifier that recorded more than one variant has no single "recorded" value to
            # compare against, and collapsing it with argMin would hide the mid-run-rehash and
            # bootstrap signatures outright. Count it, report it, keep it out of the rate.
            if has_seen_col and not include_ambiguous:
                try:
                    if float(row[variants_seen_col] or 1) > 1:
                        ambiguous += 1
                        continue
                except ValueError:
                    pass
            predicted = variant_for(flag_key, row[id_col], variants)
            recorded = row[variant_col]
            total += 1
            recorded_counts[recorded] = recorded_counts.get(recorded, 0) + 1
            if predicted is not None:
                predicted_counts[predicted] = predicted_counts.get(predicted, 0) + 1
            if predicted == recorded:
                agree += 1

    if total == 0:
        print("error: no usable rows in CSV", file=sys.stderr)
        return 2

    gaps = decompose(recorded_counts, predicted_counts, variants, total)
    expected = {g.variant: g.expected for g in gaps}
    agreement = wilson_interval(agree, total)

    # A recorded value outside the configured keys can never agree with the hash, so it reads as
    # total disagreement. Name it, or the verdict below sends the reader hunting for a wrong
    # identifier when the real fault is the variant column (wrong property, or a stale key).
    unknown = {v: n for v, n in recorded_counts.items() if v not in {g.variant for g in gaps}}

    print(f"rows:                {total}")
    if ambiguous:
        print(f"ambiguous (skipped): {ambiguous} identifiers recorded >1 variant — see the note below")
    if not has_seen_col:
        print(f"note:                no {variants_seen_col!r} column; re-export with it to surface rehashes")
    if unknown:
        listed = ", ".join(f"{printable(v)} ({n})" for v, n in sorted(unknown.items(), key=lambda kv: -kv[1])[:5])
        print(f"unknown variants:    {sum(unknown.values())} rows recorded a value not in --variants: {listed}")
    print(
        f"agreement:           {agree}/{total} ({100.0 * agree / total:.2f}%)"
        f"  95% CI [{100.0 * agreement.low:.2f}%, {100.0 * agreement.high:.2f}%]"
    )
    print(f"configured split:    {fmt_split(expected, float(total))}")
    print(f"predicted split:     {fmt_split({k: float(v) for k, v in predicted_counts.items()}, float(total))}")
    print(f"recorded split:      {fmt_split({k: float(v) for k, v in recorded_counts.items()}, float(total))}")
    print()

    verdict = judge(gaps, agree, total, variants)
    for line in verdict.lines:
        print(line)
    if ambiguous:
        print()
        print(f"   Separately: {ambiguous} identifier(s) recorded more than one variant. Under 'first seen'")
        print("   handling that is itself assignment-side evidence (mid-run rehash, bootstrap inheritance).")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true", help="replay golden vectors and statistics, then exit")
    p.add_argument("--flag-key", help="feature flag key")
    p.add_argument(
        "--variants-file",
        help="path to the flag's filters.multivariate.variants JSON (preferred: keeps untrusted "
        "variant keys off the command line)",
    )
    p.add_argument("--variants", help="stored-order variants, e.g. control=50,test=50")
    p.add_argument("--csv", help="CSV export from the decisive-test query")
    p.add_argument("--id-col", default="distinct_id", help="identifier column (default: distinct_id)")
    p.add_argument("--variant-col", default="recorded_variant", help="recorded-variant column")
    p.add_argument("--variants-seen-col", default="variants_seen", help="per-identifier variant-count column")
    p.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="count identifiers that recorded >1 variant in the agreement rate (default: report separately)",
    )
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.variants_file and args.variants:
        p.error("pass --variants-file or --variants, not both")
    if not (args.flag_key and (args.variants_file or args.variants) and args.csv):
        p.error("--flag-key, --variants-file (or --variants) and --csv are required (or use --selftest)")
    try:
        variants = load_variants_file(args.variants_file) if args.variants_file else parse_variants(args.variants)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        p.error(str(e))
    return run(
        args.flag_key,
        variants,
        args.csv,
        args.id_col,
        args.variant_col,
        args.variants_seen_col,
        args.include_ambiguous,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
