# ruff: noqa: T201
"""
Curse of dimensionality analysis for signal embeddings.

Computes all-pairs cosine distances and shows how truncating dimensions
affects the distance distribution and within/between-group separability.

Usage:
    # From posthog-cli export (JSONL, each line is a JSON array):
    posthog-cli exp query run "select product, document_type, document_id, timestamp, inserted_at, content, metadata, embedding from document_embeddings where model_name = 'text-embedding-3-small-1536' and product = 'signals' and not JSONExtractBool(metadata, 'deleted') limit 1000" > /tmp/signals_export.jsonl

    python products/signals/experiments/statistics/embedding_distances.py /tmp/signals_export.jsonl

    # Or from the cached 42-signal test set:
    python products/signals/experiments/statistics/embedding_distances.py --cached
"""

import json
import argparse
from pathlib import Path

import numpy as np

HARNESS_DIR = Path(__file__).resolve().parent.parent / "grouping"
OUTPUT_DIR = Path("/tmp/embedding_analysis")


def load_from_export(path: Path) -> tuple[list[str], np.ndarray, dict[str, list[str]]]:
    """Load from posthog-cli JSONL export.

    Each line is a JSON array:
    [0] product, [1] document_type, [2] document_id, [3] timestamp,
    [4] inserted_at, [5] content, [6] metadata (JSON string), [7] embedding (array)

    Returns (signal_ids, embedding_matrix, labels_dict) where labels_dict maps
    label_name -> list of label values per signal, for multiple grouping perspectives.
    """
    signal_ids: list[str] = []
    embeddings: list[list[float]] = []
    report_ids: list[str] = []
    source_products: list[str] = []
    source_types: list[str] = []
    source_product_types: list[str] = []
    skipped = 0

    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue

            if len(row) < 8:
                skipped += 1
                continue

            embedding = row[7]
            if not embedding or not isinstance(embedding, list) or len(embedding) == 0:
                skipped += 1
                continue

            metadata = json.loads(row[6]) if isinstance(row[6], str) else row[6]
            report_id = metadata.get("report_id", metadata.get("source_id", f"unknown_{line_num}"))
            sp = metadata.get("source_product", "unknown")
            st = metadata.get("source_type", "unknown")

            signal_ids.append(row[2])
            embeddings.append(embedding)
            report_ids.append(str(report_id))
            source_products.append(sp)
            source_types.append(st)
            source_product_types.append(f"{sp}/{st}")

    if skipped:
        print(f"  Skipped {skipped} rows (missing embedding or malformed)")

    labels = {
        "report_id": report_ids,
        "source_product": source_products,
        "source_type": source_types,
        "source_product_type": source_product_types,
    }
    return signal_ids, np.array(embeddings, dtype=np.float64), labels


def load_from_cache() -> tuple[list[str], np.ndarray, dict[str, list[str]]]:
    """Load from the 42-signal cached test set."""
    import hashlib

    signals_path = HARNESS_DIR / "data" / "test_signals.json"
    cache_path = HARNESS_DIR / "cache" / "embeddings.json"

    with open(signals_path) as f:
        signals = json.load(f)
    with open(cache_path) as f:
        cache = json.load(f)

    signal_ids: list[str] = []
    embeddings: list[list[float]] = []
    report_ids: list[str] = []
    source_products: list[str] = []
    source_types: list[str] = []
    source_product_types: list[str] = []

    for sig in signals:
        key = hashlib.sha256(sig["content"].encode()).hexdigest()
        if key not in cache:
            print(f"  WARNING: no cached embedding for signal {sig['signal_id'][:12]}")
            continue
        signal_ids.append(sig["signal_id"])
        embeddings.append(cache[key])
        report_ids.append(sig["original_report_id"])
        sp = sig.get("source_product", "unknown")
        st = sig.get("source_type", "unknown")
        source_products.append(sp)
        source_types.append(st)
        source_product_types.append(f"{sp}/{st}")

    labels = {
        "report_id": report_ids,
        "source_product": source_products,
        "source_type": source_types,
        "source_product_type": source_product_types,
    }
    return signal_ids, np.array(embeddings, dtype=np.float64), labels


def load_from_cache_split() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Load cached embeddings split into signals vs queries.

    Returns (signal_embeddings, query_embeddings, signal_report_ids).
    """
    import hashlib

    signals_path = HARNESS_DIR / "data" / "test_signals.json"
    cache_path = HARNESS_DIR / "cache" / "embeddings.json"

    with open(signals_path) as f:
        signals = json.load(f)
    with open(cache_path) as f:
        cache = json.load(f)

    signal_keys = set()
    signal_embs = []
    report_ids = []

    for sig in signals:
        key = hashlib.sha256(sig["content"].encode()).hexdigest()
        if key in cache:
            signal_keys.add(key)
            signal_embs.append(cache[key])
            report_ids.append(sig["original_report_id"])

    query_embs = [emb for key, emb in cache.items() if key not in signal_keys]

    return (
        np.array(signal_embs, dtype=np.float64),
        np.array(query_embs, dtype=np.float64),
        report_ids,
    )


def cosine_distance_cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine distances between every row of a and every row of b. Returns (len(a), len(b)) matrix."""
    a_norms = np.linalg.norm(a, axis=1, keepdims=True)
    a_norms = np.where(a_norms == 0, 1, a_norms)
    b_norms = np.linalg.norm(b, axis=1, keepdims=True)
    b_norms = np.where(b_norms == 0, 1, b_norms)
    sim = (a / a_norms) @ (b / b_norms).T
    np.clip(sim, -1, 1, out=sim)
    return 1 - sim


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = embeddings / norms
    sim = normed @ normed.T
    np.clip(sim, -1, 1, out=sim)
    return 1 - sim


def truncate_and_renormalize(embeddings: np.ndarray, dims: int) -> np.ndarray:
    truncated = embeddings[:, :dims]
    norms = np.linalg.norm(truncated, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return truncated / norms


def analyze_distribution(distances: np.ndarray, label: str) -> dict:
    percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    pvals = np.percentile(distances, percentiles)
    stats = {
        "label": label,
        "count": len(distances),
        "mean": float(np.mean(distances)),
        "std": float(np.std(distances)),
        "min": float(np.min(distances)),
        "max": float(np.max(distances)),
        "iqr": float(pvals[5] - pvals[3]),  # p75 - p25
        "spread_ratio": float(np.std(distances) / np.mean(distances)) if np.mean(distances) > 0 else 0,
    }
    for p, v in zip(percentiles, pvals):
        stats[f"p{p}"] = float(v)
    return stats


def analyze_within_vs_between(dist_matrix: np.ndarray, report_ids: list[str], label: str) -> dict:
    n = len(report_ids)
    within = []
    between = []

    for i in range(n):
        for j in range(i + 1, n):
            d = dist_matrix[i, j]
            if report_ids[i] == report_ids[j]:
                within.append(d)
            else:
                between.append(d)

    within_arr = np.array(within) if within else np.array([0.0])
    between_arr = np.array(between) if between else np.array([0.0])

    pooled_std = np.sqrt((np.std(within_arr) ** 2 + np.std(between_arr) ** 2) / 2)
    cohens_d = (np.mean(between_arr) - np.mean(within_arr)) / pooled_std if pooled_std > 0 else 0

    return {
        "label": label,
        "within_mean": float(np.mean(within_arr)),
        "within_std": float(np.std(within_arr)),
        "within_p50": float(np.median(within_arr)),
        "between_mean": float(np.mean(between_arr)),
        "between_std": float(np.std(between_arr)),
        "between_p50": float(np.median(between_arr)),
        "cohens_d": float(cohens_d),
        "n_within": len(within),
        "n_between": len(between),
    }


def print_stats_table(all_stats: list[dict]) -> None:
    print(
        f"\n{'Dims':>6} | {'Mean':>6} | {'Std':>6} | {'IQR':>6} | {'Spread':>6} | "
        f"{'P5':>6} | {'P25':>6} | {'P50':>6} | {'P75':>6} | {'P95':>6} | {'Min':>6} | {'Max':>6}"
    )
    print("-" * 105)
    for s in all_stats:
        print(
            f"{s['label']:>6} | {s['mean']:6.4f} | {s['std']:6.4f} | {s['iqr']:6.4f} | {s['spread_ratio']:6.4f} | "
            f"{s['p5']:6.4f} | {s['p25']:6.4f} | {s['p50']:6.4f} | {s['p75']:6.4f} | {s['p95']:6.4f} | "
            f"{s['min']:6.4f} | {s['max']:6.4f}"
        )


def print_separability_table(all_sep: list[dict]) -> None:
    print(
        f"\n{'Dims':>6} | {'Within μ':>9} | {'Within σ':>9} | "
        f"{'Between μ':>10} | {'Between σ':>10} | {'Cohen d':>8} | {'Gap':>8}"
    )
    print("-" * 85)
    for s in all_sep:
        gap = s["between_mean"] - s["within_mean"]
        print(
            f"{s['label']:>6} | {s['within_mean']:9.4f} | {s['within_std']:9.4f} | "
            f"{s['between_mean']:10.4f} | {s['between_std']:10.4f} | {s['cohens_d']:8.3f} | {gap:8.4f}"
        )


def run_split_analysis(dim_levels: list[int]) -> None:
    """Analyze signal vs query embedding distributions and their cross-distances."""
    print("Loading cached embeddings (split mode)...")
    signal_embs, query_embs, report_ids = load_from_cache_split()
    n_signals = signal_embs.shape[0]
    n_queries = query_embs.shape[0]
    n_dims = signal_embs.shape[1]
    print(f"  {n_signals} signal embeddings, {n_queries} query embeddings, {n_dims} dimensions")

    dim_levels = [d for d in dim_levels if d <= n_dims]

    sig_stats_all = []
    qry_stats_all = []
    cross_stats_all = []

    for dims in dim_levels:
        print(f"  Computing {dims}d...", end=" ", flush=True)
        if dims == n_dims:
            sig = signal_embs
            qry = query_embs
        else:
            sig = truncate_and_renormalize(signal_embs, dims)
            qry = truncate_and_renormalize(query_embs, dims)

        # Signal-signal distances
        sig_dist = cosine_distance_matrix(sig)
        sig_upper = sig_dist[np.triu_indices_from(sig_dist, k=1)]
        sig_stats_all.append(analyze_distribution(sig_upper, str(dims)))

        # Query-query distances
        qry_dist = cosine_distance_matrix(qry)
        qry_upper = qry_dist[np.triu_indices_from(qry_dist, k=1)]
        qry_stats_all.append(analyze_distribution(qry_upper, str(dims)))

        # Signal-query cross distances (every signal vs every query)
        cross_dist = cosine_distance_cross(sig, qry)
        cross_stats_all.append(analyze_distribution(cross_dist.ravel(), str(dims)))

        print("done")

    sig_pairs = n_signals * (n_signals - 1) // 2
    qry_pairs = n_queries * (n_queries - 1) // 2
    cross_pairs = n_signals * n_queries

    print(f"\n=== SIGNAL-SIGNAL DISTANCES ({n_signals} signals, {sig_pairs} pairs) ===")
    print_stats_table(sig_stats_all)

    print(f"\n=== QUERY-QUERY DISTANCES ({n_queries} queries, {qry_pairs} pairs) ===")
    print_stats_table(qry_stats_all)

    print(f"\n=== SIGNAL-QUERY CROSS-DISTANCES ({cross_pairs} pairs) ===")
    print("  (This is what cosine search actually computes: query embedding vs stored signal embedding)")
    print_stats_table(cross_stats_all)

    # Compare the three distributions at each dim level
    print(f"\n=== DISTRIBUTION COMPARISON (median cosine distance) ===")
    print(
        f"\n{'Dims':>6} | {'Sig-Sig':>8} | {'Qry-Qry':>8} | {'Sig-Qry':>8} | {'Sig IQR':>8} | {'Qry IQR':>8} | {'Cross IQR':>9}"
    )
    print("-" * 70)
    for ss, qs, cs in zip(sig_stats_all, qry_stats_all, cross_stats_all):
        print(
            f"{ss['label']:>6} | {ss['p50']:8.4f} | {qs['p50']:8.4f} | {cs['p50']:8.4f} | "
            f"{ss['iqr']:8.4f} | {qs['iqr']:8.4f} | {cs['iqr']:9.4f}"
        )


def main():
    parser = argparse.ArgumentParser(description="Embedding distance distribution analysis")
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to posthog-cli JSONL export (each line: [product, doc_type, doc_id, ts, inserted_at, content, metadata, embedding])",
    )
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Use the 42-signal cached test set instead of an export file",
    )
    parser.add_argument(
        "--cached-split",
        action="store_true",
        help="Analyze cached embeddings split into signals (42) vs queries (66)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp/embedding_analysis",
        help="Output directory for distance matrices and stats (default: /tmp/embedding_analysis)",
    )
    parser.add_argument(
        "--dims",
        type=str,
        default="32,64,128,256,512,768,1024,1536",
        help="Comma-separated list of truncation dimensions to test (default: 32,64,128,256,512,768,1024,1536)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip saving distance matrices to disk (faster for quick analysis)",
    )
    args = parser.parse_args()

    if not args.input and not args.cached and not args.cached_split:
        parser.error("Provide an input file, --cached, or --cached-split")

    output_dir = Path(args.output)
    dim_levels = [int(d.strip()) for d in args.dims.split(",")]

    if args.cached_split:
        run_split_analysis(dim_levels)
        return

    if args.cached:
        print("Loading from cached test set...")
        signal_ids, embeddings, labels = load_from_cache()
    else:
        print(f"Loading from {args.input}...")
        signal_ids, embeddings, labels = load_from_export(Path(args.input))

    n_signals = len(signal_ids)
    n_dims = embeddings.shape[1]
    n_pairs = n_signals * (n_signals - 1) // 2

    # Print label breakdown
    from collections import Counter

    print(f"  {n_signals} signals, {n_dims} dimensions, {n_pairs} pairs")
    print()
    for label_name, label_values in labels.items():
        counts = Counter(label_values)
        n_groups = len(counts)
        multi = sum(1 for c in counts.values() if c > 1)
        singletons = sum(1 for c in counts.values() if c == 1)
        top3 = counts.most_common(3)
        top3_str = ", ".join(f"{k[:30]}({v})" for k, v in top3)
        print(f"  {label_name}: {n_groups} unique ({multi} multi-signal, {singletons} singletons) — top: {top3_str}")

    # Filter dim_levels to those <= actual dimensions
    dim_levels = [d for d in dim_levels if d <= n_dims]

    # Precompute distance matrices
    dist_matrices: dict[int, np.ndarray] = {}
    all_stats = []

    for dims in dim_levels:
        print(f"  Computing {dims}d...", end=" ", flush=True)
        if dims == n_dims:
            emb = embeddings
        else:
            emb = truncate_and_renormalize(embeddings, dims)

        dist_matrix = cosine_distance_matrix(emb)
        dist_matrices[dims] = dist_matrix
        upper = dist_matrix[np.triu_indices_from(dist_matrix, k=1)]

        stats = analyze_distribution(upper, str(dims))
        all_stats.append(stats)

        if not args.no_save:
            output_dir.mkdir(parents=True, exist_ok=True)
            np.save(output_dir / f"dist_matrix_{dims}d.npy", dist_matrix)

        print("done")

    # Print distance distribution
    print(f"\n=== ALL-PAIRS COSINE DISTANCE DISTRIBUTION ({n_signals} signals, {n_pairs} pairs) ===")
    print_stats_table(all_stats)

    # Separability for each label type
    all_sep_by_label: dict[str, list[dict]] = {}
    for label_name, label_values in labels.items():
        n_groups = len(set(label_values))
        # Skip if only 1 group or all singletons (no within-group pairs)
        n_within = sum(
            1 for i in range(n_signals) for j in range(i + 1, n_signals) if label_values[i] == label_values[j]
        )
        if n_within == 0:
            continue

        sep_list = []
        for dims in dim_levels:
            sep = analyze_within_vs_between(dist_matrices[dims], label_values, str(dims))
            sep_list.append(sep)
        all_sep_by_label[label_name] = sep_list

        circularity = " (CIRCULAR — pipeline used these embeddings to assign)" if label_name == "report_id" else ""
        print(f"\n=== SEPARABILITY by {label_name} ({n_groups} groups, {n_within} within-pairs){circularity} ===")
        print(f"  Cohen's d > 0.8 = good, > 1.2 = excellent")
        print_separability_table(sep_list)

    # Save metadata and stats
    if not args.no_save:
        output_dir.mkdir(parents=True, exist_ok=True)

        meta = [{"signal_id": sid, **{k: vs[i] for k, vs in labels.items()}} for i, sid in enumerate(signal_ids)]
        with open(output_dir / "signal_metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        with open(output_dir / "distribution_stats.json", "w") as f:
            json.dump({"all_pairs": all_stats, "separability": all_sep_by_label}, f, indent=2)

        print(f"\nRaw data saved to {output_dir}/")


if __name__ == "__main__":
    main()
