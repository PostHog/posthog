"""Score sparse member edges and derive report-pair graph operations."""

# ruff: noqa: T201

from __future__ import annotations

import json
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RAW_THRESHOLDS = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98)
CAL_THRESHOLDS = (0.50, 0.70, 0.80, 0.88, 0.94, 0.98, 0.99)


def load_scores(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    scores: dict[tuple[str, str], tuple[float, float]] = {}
    with path.open() as source:
        for line_index, line in enumerate(source, start=1):
            row = json.loads(line)
            key = (str(row["doc_a"]), str(row["doc_b"]))
            if key in scores:
                raise ValueError(f"duplicate pair feature key: {key}")
            scores[key] = (float(row["pair_raw"]), float(row["pair_cal"]))
            if line_index % 100_000 == 0:
                print(f"loaded pair scores: {line_index}")
    return scores


def graph_stats(
    group: pd.DataFrame,
    left_size: int,
    right_size: int,
    score_column: str,
    threshold: float,
) -> dict[str, float | int | bool]:
    active = group.loc[group[score_column] >= threshold]
    left_covered = {int(value) for value in active["left_member_index"]}
    right_covered = {int(value) for value in active["right_member_index"]}
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(node: tuple[str, int]) -> tuple[str, int]:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: tuple[str, int], right: tuple[str, int]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[left_root] = right_root

    for row in active.itertuples(index=False):
        union(("left", int(row.left_member_index)), ("right", int(row.right_member_index)))
    components: dict[tuple[str, int], dict[str, set[int]]] = defaultdict(lambda: {"left": set(), "right": set()})
    for node in parent:
        side, index = node
        components[find(node)][side].add(index)
    cross_components = [value for value in components.values() if value["left"] and value["right"]]
    cross_components.sort(key=lambda value: len(value["left"]) + len(value["right"]), reverse=True)
    largest = cross_components[0] if cross_components else {"left": set(), "right": set()}
    covers_all = len(left_covered) == left_size and len(right_covered) == right_size
    whole_merge = covers_all and len(cross_components) == 1
    return {
        "active_edges": len(active),
        "left_coverage": len(left_covered) / left_size,
        "right_coverage": len(right_covered) / right_size,
        "min_coverage": min(len(left_covered) / left_size, len(right_covered) / right_size),
        "cross_components": len(cross_components),
        "largest_left_share": len(largest["left"]) / left_size,
        "largest_right_share": len(largest["right"]) / right_size,
        "largest_min_share": min(len(largest["left"]) / left_size, len(largest["right"]) / right_size),
        "whole_merge": whole_merge,
        "subset_rescue": bool(cross_components) and not whole_merge,
    }


def quantiles(values: np.ndarray, prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_q10": float(np.quantile(values, 0.10)),
        f"{prefix}_q25": float(np.quantile(values, 0.25)),
        f"{prefix}_median": float(np.median(values)),
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_q75": float(np.quantile(values, 0.75)),
        f"{prefix}_max": float(np.max(values)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--edges", required=True)
    parser.add_argument("--pair-features", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    ledger = pd.read_parquet(args.ledger)
    edges = pd.read_parquet(args.edges)
    scores = load_scores(Path(args.pair_features))
    edge_keys = list(zip(edges["doc_a"], edges["doc_b"]))
    missing = [key for key in edge_keys if key not in scores]
    if missing:
        raise ValueError(f"missing {len(missing)} scored member edges")
    edges["pair_raw"] = [scores[key][0] for key in edge_keys]
    edges["pair_cal"] = [scores[key][1] for key in edge_keys]

    ledger_by_id = ledger.set_index("merge_id")
    report_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    for group_index, (merge_id, group) in enumerate(edges.groupby("merge_id", sort=False), start=1):
        label = ledger_by_id.loc[merge_id]
        left_size = int(label["left_size"])
        right_size = int(label["right_size"])
        left_support_raw = group.groupby("left_member_index")["pair_raw"].max().reindex(range(left_size), fill_value=0).to_numpy()
        right_support_raw = group.groupby("right_member_index")["pair_raw"].max().reindex(range(right_size), fill_value=0).to_numpy()
        left_support_cal = group.groupby("left_member_index")["pair_cal"].max().reindex(range(left_size), fill_value=0).to_numpy()
        right_support_cal = group.groupby("right_member_index")["pair_cal"].max().reindex(range(right_size), fill_value=0).to_numpy()
        row: dict[str, Any] = {
            "merge_id": merge_id,
            "policy": str(label["policy"]),
            "verdict": str(label["verdict"]),
            "reports_related": bool(label["reports_related"]),
            "whole_merge_safe": bool(label["whole_merge_safe"]),
            "subset_rescue_label": bool(label["subset_rescue"]),
            "left_size": left_size,
            "right_size": right_size,
            "edge_count": len(group),
        }
        row.update(quantiles(left_support_raw, "left_raw_support"))
        row.update(quantiles(right_support_raw, "right_raw_support"))
        row.update(quantiles(left_support_cal, "left_cal_support"))
        row.update(quantiles(right_support_cal, "right_cal_support"))
        for scale, thresholds in (("raw", RAW_THRESHOLDS), ("cal", CAL_THRESHOLDS)):
            for threshold in thresholds:
                prefix = f"{scale}_{threshold:.2f}"
                for name, value in graph_stats(group, left_size, right_size, f"pair_{scale}", threshold).items():
                    row[f"{prefix}_{name}"] = value
        report_rows.append(row)
        for side, support_raw, support_cal in (
            ("left", left_support_raw, left_support_cal),
            ("right", right_support_raw, right_support_cal),
        ):
            for member_index, (raw, cal) in enumerate(zip(support_raw, support_cal)):
                member_rows.append(
                    {
                        "merge_id": merge_id,
                        "side": side,
                        "member_index": member_index,
                        "max_pair_raw": float(raw),
                        "max_pair_cal": float(cal),
                        "verdict": str(label["verdict"]),
                    }
                )
        if group_index % 250 == 0:
            print(f"alignment graphs: {group_index}/{len(ledger)}")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(output / "scored_member_edges.parquet", index=False)
    pd.DataFrame(member_rows).to_parquet(output / "member_support.parquet", index=False)
    report_frame = pd.DataFrame(report_rows)
    report_frame.to_parquet(output / "report_alignment_features.parquet", index=False)
    summary = {
        "status": "direct pair-compatibility graph baseline; no member identity labels consumed",
        "report_pairs": len(report_frame),
        "member_edges": len(edges),
        "member_rows": len(member_rows),
        "raw_thresholds": RAW_THRESHOLDS,
        "calibrated_thresholds": CAL_THRESHOLDS,
    }
    (output / "graph_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
