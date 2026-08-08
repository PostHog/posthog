#!/usr/bin/env python3
"""Localize a confirmed experiment SRM to assignment-side vs capture-side.

Recomputes each user's variant from PostHog's deterministic flag hash and compares it
to the recorded `$feature_flag_response`. See "The decisive test" in `pulling-the-data.md`
for the full diagnostic. Read that first — this script only produces the agreement number;
you still have to route on it.

    ~100% agreement  => assignment was correct for everyone recorded => CAPTURE-side.
    well under 100%  => something overrode assignment at serve time  => ASSIGNMENT-side.

Algorithm is byte-exact with the PostHog implementation in
`rust/feature-flags/src/flags/flag_matching.rs` (get_matching_variant) and
`flag_matching_utils.rs` (calculate_hash). Run `--selftest` first: it replays the repo's
golden hash vectors so you know the reimplementation matches this build before you trust
a verdict.

Stdlib only (hashlib, csv, argparse) — no PostHog install required. distinct_ids are
often emails; run this customer-side and paste back only the aggregate lines it prints.

    ./srm_check.py --selftest
    ./srm_check.py --flag-key my-flag --variants control=50,test=50 --csv exposures.csv

The CSV is the export query from the decisive test: a header row plus
`distinct_id,recorded_variant` (override names with --id-col / --variant-col). The id column must
hold the identifier production hashed: the group key for a group-aggregated flag, or `$device_id`
(coalesced to distinct_id when empty) for a device-ID-bucketed flag
(`bucketing_identifier == "device_id"`) — otherwise the distinct_id. Feeding the wrong identifier
fabricates disagreements and misreads a capture-side SRM as assignment-side.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys

# 0xfffffffffffffff == 15 hex digits == LONG_SCALE in flag_matching_utils.rs
__LONG_SCALE__ = 0xFFFFFFFFFFFFFFF


def calculate_hash(prefix: str, identifier: str, salt: str = "") -> float:
    """Deterministic hash in [0, 1). Mirrors calculate_hash() in flag_matching_utils.rs:
    first 15 hex chars of sha1(prefix + identifier + salt), divided by LONG_SCALE."""
    hash_key = f"{prefix}{identifier}{salt}"
    return int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16) / __LONG_SCALE__


def variant_for(flag_key: str, identifier: str, variants: list[tuple[str, float]]) -> str | None:
    """Recompute the assigned variant. Mirrors get_matching_variant(): hash with the
    `variant` salt, then walk the variants in stored order by cumulative percentage.
    `variants` must be in the flag's stored order — a wrong order inverts the result."""
    h = calculate_hash(f"{flag_key}.", identifier, "variant")
    cumulative = 0.0
    for name, pct in variants:
        cumulative += pct / 100.0
        if h < cumulative:
            return name
    return None


def parse_variants(spec: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for part in spec.split(","):
        name, _, pct = part.partition("=")
        if not name or not pct:
            raise ValueError(f"bad --variants entry {part!r}; expected name=pct")
        out.append((name.strip(), float(pct)))
    return out


# Golden vectors from rust/feature-flags/src/flags/flag_matching_utils.rs
# (test_calculate_hash: prefix="holdout-", salt=""). If these fail, the local
# hashing does not match PostHog and any verdict below would be meaningless.
_GOLDEN = [
    ("some_distinct_id", 0.7270002403585725),
    ("test-identifier", 0.4493881716040236),
    ("example_id", 0.9402003475831224),
    ("example_id2", 0.6292740389966519),
]


def selftest() -> int:
    ok = True
    for ident, expected in _GOLDEN:
        got = calculate_hash("holdout-", ident, "")
        match = abs(got - expected) < 1e-12
        ok = ok and match
        print(f"  {ident:20s} {got!r} {'ok' if match else f'MISMATCH (want {expected!r})'}")
    # Sanity-check the variant walk splits ~evenly on synthetic ids.
    counts: dict[str | None, int] = {}
    variants = [("control", 50.0), ("test", 50.0)]
    for i in range(4000):
        v = variant_for("selftest-flag", f"user_{i}", variants)
        counts[v] = counts.get(v, 0) + 1
    print(f"  variant walk (50/50 over 4000 ids): {counts}")
    print("SELFTEST PASS" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def run(flag_key: str, variants: list[tuple[str, float]], csv_path: str,
        id_col: str, variant_col: str) -> int:
    total = agree = 0
    recorded_counts: dict[str, int] = {}
    predicted_counts: dict[str | None, int] = {}
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for col in (id_col, variant_col):
            if col not in (reader.fieldnames or []):
                print(f"error: column {col!r} not in CSV header {reader.fieldnames}", file=sys.stderr)
                return 2
        for row in reader:
            identifier = row[id_col]
            recorded = row[variant_col]
            predicted = variant_for(flag_key, identifier, variants)
            total += 1
            recorded_counts[recorded] = recorded_counts.get(recorded, 0) + 1
            predicted_counts[predicted] = predicted_counts.get(predicted, 0) + 1
            if predicted == recorded:
                agree += 1

    if total == 0:
        print("error: no rows in CSV", file=sys.stderr)
        return 2

    pct = 100.0 * agree / total
    print(f"rows:                {total}")
    print(f"agreement:           {agree}/{total} ({pct:.2f}%)")
    print(f"recorded variants:   {dict(sorted(recorded_counts.items()))}")
    print(f"predicted variants:  {dict(sorted(predicted_counts.items(), key=lambda x: str(x[0])))}")
    print()
    if pct >= 99.0:
        print("=> ~100% agreement: assignment matches the hash for everyone recorded.")
        print("   The skew is CAPTURE-side. Work the capture-side causes")
        print("   (uneven-split exclusion, capture-by-surface, flag-read-before-load, wrong SDK method).")
    else:
        print("=> agreement well under 100%: something overrode assignment at serve time.")
        print("   The skew is ASSIGNMENT-side. Work the assignment-side causes")
        print("   (bootstrap inheritance, mid-run rehash, forced variant, stale local eval).")
        print("   If disagreement clusters on one $lib/surface, start there.")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true", help="replay golden hash vectors and exit")
    p.add_argument("--flag-key", help="feature flag key")
    p.add_argument("--variants", help="stored-order variants, e.g. control=50,test=50")
    p.add_argument("--csv", help="CSV export from the decisive-test query")
    p.add_argument("--id-col", default="distinct_id", help="identifier column (default: distinct_id)")
    p.add_argument("--variant-col", default="recorded_variant", help="recorded-variant column")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    if not (args.flag_key and args.variants and args.csv):
        p.error("--flag-key, --variants and --csv are required (or use --selftest)")
    return run(args.flag_key, parse_variants(args.variants), args.csv, args.id_col, args.variant_col)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
