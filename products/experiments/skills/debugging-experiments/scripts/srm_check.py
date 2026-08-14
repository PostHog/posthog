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
`flag_matching_utils.rs` (calculate_hash). Run `--selftest` first — it checks all three
parts a wrong verdict would come from, and exits non-zero on any mismatch:

    hash pipeline    replayed against the repo's golden vectors
    variant hash key the `{flag_key}.` prefix and the `variant` salt
    variant walk     stored order and the strict `<` bound

Stdlib only (hashlib, csv, argparse) — no PostHog install required. distinct_ids are
often emails; run this customer-side and paste back only the aggregate lines it prints.

    ./srm_check.py --selftest
    ./srm_check.py --flag-key my-flag --variants-file variants.json --csv exposures.csv

Prefer --variants-file: save the flag's `filters.multivariate.variants` array to a file and pass
the path. Variant keys are only charset-validated in the PostHog UI, not by the API, so a key
reaching you through a ticket can contain shell metacharacters or quotes — keep it out of the
command line entirely rather than trying to quote it. --variants is the convenience form for keys
you have already eyeballed.

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
import json
import sys

# 0xfffffffffffffff == 15 hex digits == LONG_SCALE in flag_matching_utils.rs
__LONG_SCALE__ = 0xFFFFFFFFFFFFFFF


def hash_of(hash_key: str) -> float:
    """The pipeline half of calculate_hash() in flag_matching_utils.rs: first 15 hex
    chars of sha1(hash_key), divided by LONG_SCALE. Deterministic, in [0, 1)."""
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


def selftest() -> int:
    ok = True

    print("hash pipeline (golden vectors from flag_matching_utils.rs):")
    for ident, expected in _GOLDEN:
        got = calculate_hash("holdout-", ident, "")
        match = abs(got - expected) < 1e-12
        ok = ok and match
        print(f"  {ident:20s} {got!r} {'ok' if match else f'MISMATCH (want {expected!r})'}")

    print("variant hash key (`{flag_key}.` prefix + `variant` salt):")
    for flag_key, ident, expected in _GOLDEN_VARIANT_KEYS:
        got = variant_hash_key(flag_key, ident)
        match = got == expected
        ok = ok and match
        print(f"  {got!r} {'ok' if match else f'MISMATCH (want {expected!r})'}")

    print("variant walk (stored order, strict < bound):")
    for h, variants, expected in _WALK_CASES:
        got = pick_variant(h, variants)
        match = got == expected
        ok = ok and match
        order = ",".join(f"{name}={pct:g}" for name, pct in variants)
        print(f"  h={h:<7g} [{order}] -> {got!r} {'ok' if match else f'MISMATCH (want {expected!r})'}")

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
        print(f"=> {pct:.2f}% agreement: assignment matches the hash for all but {total - agree} of the")
        print("   users recorded, so assignment is not what is skewing the split.")
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
    p.add_argument(
        "--variants-file",
        help="path to the flag's filters.multivariate.variants JSON (preferred: keeps untrusted "
        "variant keys off the command line)",
    )
    p.add_argument("--variants", help="stored-order variants, e.g. control=50,test=50")
    p.add_argument("--csv", help="CSV export from the decisive-test query")
    p.add_argument("--id-col", default="distinct_id", help="identifier column (default: distinct_id)")
    p.add_argument("--variant-col", default="recorded_variant", help="recorded-variant column")
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
    return run(args.flag_key, variants, args.csv, args.id_col, args.variant_col)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
