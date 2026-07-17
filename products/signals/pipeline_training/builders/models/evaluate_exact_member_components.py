"""Evaluate exact member-mask and component recovery from OOF edge scores."""

# ruff: noqa: T201

from __future__ import annotations

import json
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

THRESHOLDS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98)
GRAPH_MODES = ("all", "mutual_embedding", "reciprocal_embedding_2", "mutual_score_best", "reciprocal_score_2")


def active_edges(
    group: pd.DataFrame,
    score_column: str,
    threshold: float,
    mode: str = "all",
) -> pd.DataFrame:
    active = group.loc[group[score_column] >= threshold]
    if mode == "mutual_embedding":
        active = active.loc[active["mutual_top_k"]]
    elif mode == "reciprocal_embedding_2":
        active = active.loc[(active["left_rank_filled"] <= 2) & (active["right_rank_filled"] <= 2)]
    elif mode in {"mutual_score_best", "reciprocal_score_2"}:
        limit = 1 if mode == "mutual_score_best" else 2
        active = active.loc[
            (active[f"{score_column}:left_score_rank"] <= limit)
            & (active[f"{score_column}:right_score_rank"] <= limit)
        ]
    return active


def graph_components(
    group: pd.DataFrame,
    score_column: str,
    threshold: float,
    mode: str = "all",
) -> list[tuple[set[int], set[int]]]:
    active = active_edges(group, score_column, threshold, mode)
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
    components: dict[tuple[str, int], tuple[set[int], set[int]]] = defaultdict(lambda: (set(), set()))
    for node in parent:
        side, index = node
        left, right = components[find(node)]
        (left if side == "left" else right).add(index)
    return [component for component in components.values() if component[0] and component[1]]


def parse_components(value: str) -> list[tuple[set[int], set[int]]]:
    return [(set(component["left_indices"]), set(component["right_indices"])) for component in json.loads(value)]


def selected(components: list[tuple[set[int], set[int]]], side: int) -> set[int]:
    return set().union(*(component[side] for component in components)) if components else set()


def cross_pairs(components: list[tuple[set[int], set[int]]]) -> set[tuple[int, int]]:
    return {(left, right) for left_members, right_members in components for left in left_members for right in right_members}


def signature(components: list[tuple[set[int], set[int]]]) -> set[frozenset[str]]:
    return {
        frozenset([*(f"L:{index}" for index in left), *(f"R:{index}" for index in right)])
        for left, right in components
    }


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def score_subset_rows(
    labels: pd.DataFrame,
    edges_by_id: dict[str, pd.DataFrame],
    keep_edges: pd.DataFrame,
    score_column: str,
    threshold: float,
    mode: str,
) -> dict[str, float | int | str]:
    label_by_id = labels.set_index("merge_id")
    member_tp = member_fp = member_fn = 0
    pair_tp = pair_fp = pair_fn = 0
    left_jaccard = right_jaccard = pair_jaccard = 0.0
    exact_masks = exact_partitions = any_components = 0
    rows = labels.loc[labels["member_verdict"] == "merge_subset"]
    for merge_id in rows["merge_id"]:
        truth = parse_components(str(label_by_id.loc[merge_id, "member_components"]))
        predicted = graph_components(edges_by_id[str(merge_id)], score_column, threshold, mode)
        any_components += bool(predicted)
        exact_partitions += signature(predicted) == signature(truth)
        true_left = selected(truth, 0)
        true_right = selected(truth, 1)
        predicted_left = selected(predicted, 0)
        predicted_right = selected(predicted, 1)
        exact_masks += predicted_left == true_left and predicted_right == true_right
        for true_members, predicted_members in ((true_left, predicted_left), (true_right, predicted_right)):
            member_tp += len(true_members & predicted_members)
            member_fp += len(predicted_members - true_members)
            member_fn += len(true_members - predicted_members)
        left_union = true_left | predicted_left
        right_union = true_right | predicted_right
        left_jaccard += ratio(len(true_left & predicted_left), len(left_union))
        right_jaccard += ratio(len(true_right & predicted_right), len(right_union))
        true_pairs = cross_pairs(truth)
        predicted_pairs = cross_pairs(predicted)
        pair_tp += len(true_pairs & predicted_pairs)
        pair_fp += len(predicted_pairs - true_pairs)
        pair_fn += len(true_pairs - predicted_pairs)
        pair_jaccard += ratio(len(true_pairs & predicted_pairs), len(true_pairs | predicted_pairs))
    row_count = len(rows)
    keep_false = active_edges(keep_edges, score_column, threshold, mode)["merge_id"].nunique()
    return {
        "threshold": threshold,
        "graph_mode": mode,
        "subset_rows": row_count,
        "subset_rows_with_component": any_components,
        "exact_member_masks": exact_masks,
        "exact_component_partitions": exact_partitions,
        "member_precision": ratio(member_tp, member_tp + member_fp),
        "member_recall": ratio(member_tp, member_tp + member_fn),
        "macro_left_member_jaccard": left_jaccard / row_count,
        "macro_right_member_jaccard": right_jaccard / row_count,
        "cross_pair_precision": ratio(pair_tp, pair_tp + pair_fp),
        "cross_pair_recall": ratio(pair_tp, pair_tp + pair_fn),
        "macro_cross_pair_jaccard": pair_jaccard / row_count,
        "keep_separate_rows_with_component": keep_false,
    }


def oracle_retrieval(labels: pd.DataFrame, edges_by_id: dict[str, pd.DataFrame]) -> dict[str, float | int]:
    label_by_id = labels.set_index("merge_id")
    recovered_members = total_members = recovered_pairs = total_pairs = exact_masks = exact_partitions = 0
    rows = labels.loc[labels["member_verdict"] == "merge_subset"]
    for merge_id in rows["merge_id"]:
        truth = parse_components(str(label_by_id.loc[merge_id, "member_components"]))
        group = edges_by_id[str(merge_id)].copy()
        true_pairs = cross_pairs(truth)
        group["oracle"] = [
            (int(row.left_member_index), int(row.right_member_index)) in true_pairs for row in group.itertuples(index=False)
        ]
        predicted = graph_components(group, "oracle", 0.5)
        true_left = selected(truth, 0)
        true_right = selected(truth, 1)
        predicted_left = selected(predicted, 0)
        predicted_right = selected(predicted, 1)
        recovered_members += len(true_left & predicted_left) + len(true_right & predicted_right)
        total_members += len(true_left) + len(true_right)
        predicted_pairs = cross_pairs(predicted)
        recovered_pairs += len(true_pairs & predicted_pairs)
        total_pairs += len(true_pairs)
        exact_masks += predicted_left == true_left and predicted_right == true_right
        exact_partitions += signature(predicted) == signature(truth)
    return {
        "subset_rows": len(rows),
        "sparse_retrieval_member_recall_ceiling": ratio(recovered_members, total_members),
        "sparse_retrieval_cross_pair_recall_ceiling": ratio(recovered_pairs, total_pairs),
        "sparse_retrieval_exact_mask_ceiling": exact_masks / len(rows),
        "sparse_retrieval_exact_partition_ceiling": exact_partitions / len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--surface-name", default="evaluation surface")
    args = parser.parse_args()

    labels = pd.read_parquet(args.labels)
    edges = pd.read_parquet(args.predictions)
    context = pd.read_parquet(args.edge_context)[
        ["merge_id", "left_member_index", "right_member_index", "left_rank", "right_rank", "mutual_top_k"]
    ].copy()
    context["left_rank_filled"] = context["left_rank"].fillna(5).astype(float)
    context["right_rank_filled"] = context["right_rank"].fillna(5).astype(float)
    edges = edges.merge(
        context,
        on=["merge_id", "left_member_index", "right_member_index"],
        how="left",
        validate="one_to_one",
    )
    score_columns = [column for column in edges if column.startswith("probability:")]
    for score_column in score_columns:
        edges[f"{score_column}:left_score_rank"] = edges.groupby(["merge_id", "left_member_index"])[
            score_column
        ].rank(method="min", ascending=False)
        edges[f"{score_column}:right_score_rank"] = edges.groupby(["merge_id", "right_member_index"])[
            score_column
        ].rank(method="min", ascending=False)
    edges_by_id = {str(merge_id): group for merge_id, group in edges.groupby("merge_id", sort=False)}
    keep_ids = set(labels.loc[labels["member_verdict"] == "keep_separate", "merge_id"].astype(str))
    keep_edges = edges.loc[edges["merge_id"].isin(keep_ids)]
    output: dict[str, Any] = {
        "status": f"exact member-component recovery on {args.surface_name}",
        "oracle_retrieval": oracle_retrieval(labels, edges_by_id),
        "candidates": {},
    }
    for score_column in score_columns:
        name = score_column.removeprefix("probability:")
        output["candidates"][name] = {
            mode: [
                score_subset_rows(labels, edges_by_id, keep_edges, score_column, threshold, mode)
                for threshold in THRESHOLDS
            ]
            for mode in GRAPH_MODES
        }
        print(name)
    Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["oracle_retrieval"], indent=2))


if __name__ == "__main__":
    main()
