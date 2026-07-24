"""Train direct and report-conditioned member compatibility heads."""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from score_member_alignment_graphs import graph_stats
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from train_merge_proposer_safety import component_groups

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
LABELS = LAB / "labels/admission_repair/train_merge_labels_v3.parquet"
EDGES = LAB / "data/member_alignment/20260711-v1/train/scored_member_edges.parquet"
PAIR_FEATURES = LAB / "data/member_alignment/20260711-v1/train/pair_features.parquet"
OUTPUT = LAB / "data/member_alignment/20260711-v1"
SEED = 7

DIRECT_FEATURES = (
    "embedding_cosine",
    "left_rank_filled",
    "right_rank_filled",
    "mutual_top_k",
    "pair_raw",
    "pair_cal",
)
CONTEXT_FEATURES = (
    *DIRECT_FEATURES,
    "left_raw_max",
    "right_raw_max",
    "left_raw_margin",
    "right_raw_margin",
    "left_raw_relative",
    "right_raw_relative",
    "left_cal_max",
    "right_cal_max",
    "left_cal_relative",
    "right_cal_relative",
    "left_size_log",
    "right_size_log",
    "combined_size_log",
    "report_left_raw_q10",
    "report_right_raw_q10",
    "report_left_raw_median",
    "report_right_raw_median",
    "report_left_raw_mean",
    "report_right_raw_mean",
)
RUST_FEATURE_NAMES = (
    "best_projected_distance",
    "best_rank",
    "both_et",
    "burst_c",
    "burst_q",
    "contrast_c",
    "contrast_min",
    "contrast_q",
    "cos_raw",
    "cos_residual",
    "firstline_jac",
    "gram3_jac",
    "has_stack_min",
    "id_conflict",
    "id_overlap",
    "id_shared_w",
    "len_ratio",
    "log_gap_hours",
    "log_len_absdiff",
    "n_projections_surfaced",
    "neg_density_min",
    "neg_density_ratio",
    "punct_frac_ratio",
    "residual_norm_c",
    "residual_norm_q",
    "same_hour",
    "same_product",
    "same_source_id",
    "same_type",
    "sig_anchor_match",
    "sig_both_success",
    "sig_cos",
    "sig_failmode_jac",
    "sig_oneliner_jac",
    "sig_polarity_mismatch",
    "sig_surface_jac",
    "sig_tags_jac",
    "slot_conflict_w",
    "surfaced_by_own_type",
    "template_sim",
    "ttr_ratio",
    "upper_frac_ratio",
)
RICH_DIRECT_FEATURES = (*DIRECT_FEATURES, *(f"rust_{name}" for name in RUST_FEATURE_NAMES))
RICH_CONTEXT_FEATURES = (*CONTEXT_FEATURES, *(f"rust_{name}" for name in RUST_FEATURE_NAMES))


def model_specs() -> dict[str, tuple[str, str, Any]]:
    return {
        "direct-logistic": (
            "direct",
            "logistic",
            make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        ),
        "direct-hgb-d2": (
            "direct",
            "hgb",
            HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=40, random_state=SEED),
        ),
        "direct-hgb-d3": (
            "direct",
            "hgb",
            HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=40, random_state=SEED),
        ),
        "context-logistic": (
            "context",
            "logistic",
            make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        ),
        "context-hgb-d2": (
            "context",
            "hgb",
            HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=40, random_state=SEED),
        ),
        "context-hgb-d3": (
            "context",
            "hgb",
            HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=40, random_state=SEED),
        ),
        "rich-direct-hgb-d2": (
            "rich_direct",
            "hgb",
            HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=40, random_state=SEED),
        ),
        "rich-direct-hgb-d3": (
            "rich_direct",
            "hgb",
            HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=40, random_state=SEED),
        ),
        "rich-context-logistic": (
            "rich_context",
            "logistic",
            make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        ),
    }


def add_rank_context(
    edges: pd.DataFrame, labels: pd.DataFrame, pair_features: str | Path | None = None
) -> pd.DataFrame:
    labels = labels.copy()
    if "training_weight" not in labels:
        labels["training_weight"] = 1.0
    frame = edges.merge(
        labels[["merge_id", "verdict", "training_weight", "left_size", "right_size"]],
        on="merge_id",
        how="left",
        validate="many_to_one",
    )
    if pair_features:
        rust = pd.read_parquet(pair_features, columns=["doc_a", "doc_b", *RUST_FEATURE_NAMES]).rename(
            columns={name: f"rust_{name}" for name in RUST_FEATURE_NAMES}
        )
        frame = frame.merge(rust, on=["doc_a", "doc_b"], how="left", validate="many_to_one")
        if frame[[f"rust_{name}" for name in RUST_FEATURE_NAMES]].isna().any().any():
            raise ValueError("missing Rust features after member-edge join")
    frame["left_rank_filled"] = frame["left_rank"].fillna(5).astype(float)
    frame["right_rank_filled"] = frame["right_rank"].fillna(5).astype(float)
    for side, member_column in (("left", "left_member_index"), ("right", "right_member_index")):
        keys = ["merge_id", member_column]
        for scale in ("raw", "cal"):
            score = f"pair_{scale}"
            support = frame.groupby(keys)[score].agg(["max", "mean"])
            second = frame.groupby(keys)[score].nlargest(2).groupby(level=[0, 1]).min().rename("second")
            support = support.join(second).reset_index()
            support[f"{side}_{scale}_margin"] = support["max"] - support["second"]
            support = support.rename(
                columns={
                    "max": f"{side}_{scale}_max",
                    "mean": f"{side}_{scale}_mean",
                }
            )
            frame = frame.merge(
                support[
                    [
                        *keys,
                        f"{side}_{scale}_max",
                        f"{side}_{scale}_mean",
                        f"{side}_{scale}_margin",
                    ]
                ],
                on=keys,
                how="left",
                validate="many_to_one",
            )
            frame[f"{side}_{scale}_relative"] = frame[score] / frame[f"{side}_{scale}_max"].clip(lower=1e-6)
    frame["left_size_log"] = np.log1p(frame["left_size"])
    frame["right_size_log"] = np.log1p(frame["right_size"])
    frame["combined_size_log"] = np.log1p(frame["left_size"] + frame["right_size"])
    for side, member_column in (("left", "left_member_index"), ("right", "right_member_index")):
        member_support = frame.groupby(["merge_id", member_column])["pair_raw"].max()
        report_stats = member_support.groupby(level=0).agg(
            q10=lambda values: values.quantile(0.10),
            median="median",
            mean="mean",
        )
        report_stats = report_stats.rename(columns={name: f"report_{side}_raw_{name}" for name in report_stats})
        frame = frame.merge(report_stats, left_on="merge_id", right_index=True, how="left", validate="many_to_one")
    return frame


def ranking_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float | int]:
    return {
        "rows": len(labels),
        "positive_rate": float(labels.mean()),
        "auc": float(roc_auc_score(labels, predictions)),
        "average_precision": float(average_precision_score(labels, predictions)),
    }


def fit_model(model: Any, values: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> None:
    if hasattr(model, "named_steps"):
        model.fit(values, labels, logisticregression__sample_weight=weights)
    else:
        model.fit(values, labels, sample_weight=weights)


def operation_metrics(
    labels: pd.DataFrame,
    edges: pd.DataFrame,
    probability_column: str,
) -> list[dict[str, float | int]]:
    label_by_id = labels.set_index("merge_id")
    rows: list[dict[str, float | int]] = []
    for threshold in (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98):
        true_positive = false_positive = subset_true = keep_false = executed = 0
        for merge_id, group in edges.groupby("merge_id", sort=False):
            label = label_by_id.loc[merge_id]
            stats = graph_stats(
                group,
                int(label["left_size"]),
                int(label["right_size"]),
                probability_column,
                threshold,
            )
            if stats["whole_merge"]:
                executed += 1
                if bool(label["whole_merge_safe"]):
                    true_positive += 1
                else:
                    false_positive += 1
            elif stats["subset_rescue"]:
                if bool(label["subset_rescue"]):
                    subset_true += 1
                elif str(label["verdict"]) == "keep_separate":
                    keep_false += 1
        rows.append(
            {
                "threshold": threshold,
                "executed_whole_merges": executed,
                "true_whole_merges": true_positive,
                "false_whole_merges": false_positive,
                "whole_merge_precision": true_positive / max(executed, 1),
                "whole_merge_recall": true_positive / int(labels["whole_merge_safe"].sum()),
                "subset_pairs_with_component": subset_true,
                "keep_separate_pairs_with_component": keep_false,
            }
        )
    return rows


def exact_edge_targets(edges: pd.DataFrame, labels: pd.DataFrame, component_column: str) -> np.ndarray:
    components_by_id = {
        str(row.merge_id): [
            (set(component["left_indices"]), set(component["right_indices"]))
            for component in json.loads(getattr(row, component_column))
        ]
        for row in labels.loc[labels["member_labels_known"]].itertuples(index=False)
    }
    targets = np.zeros(len(edges), dtype=np.int8)
    for row_index, row in enumerate(edges.itertuples(index=False)):
        for left_indices, right_indices in components_by_id.get(str(row.merge_id), []):
            if int(row.left_member_index) in left_indices and int(row.right_member_index) in right_indices:
                targets[row_index] = 1
                break
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default=str(LABELS))
    parser.add_argument("--edges", default=str(EDGES))
    parser.add_argument("--pair-features", default=str(PAIR_FEATURES))
    parser.add_argument("--output-dir", default=str(OUTPUT))
    parser.add_argument("--member-labels", help="optional finalized exact member-component ledger")
    parser.add_argument("--member-label-mode", choices=("opus", "consensus"), default="opus")
    parser.add_argument("--training-scope", choices=("all", "subset"), default="all")
    args = parser.parse_args()

    labels = pd.read_parquet(args.member_labels or args.labels)
    if args.member_labels:
        labels["original_verdict"] = labels["verdict"]
        labels["verdict"] = labels["member_verdict"]
        labels["whole_merge_safe"] = labels["member_verdict"] == "merge_all"
        labels["subset_rescue"] = labels["member_verdict"] == "merge_subset"
    edges = add_rank_context(pd.read_parquet(args.edges), labels, args.pair_features)
    report_groups = component_groups(labels)
    fold_ids = np.full(len(labels), -1, dtype=np.int64)
    splitter = GroupKFold(n_splits=5)
    for fold, (_, test_indices) in enumerate(splitter.split(labels, labels["verdict"], report_groups)):
        fold_ids[test_indices] = fold
    fold_by_merge = dict(zip(labels["merge_id"], fold_ids, strict=True))
    edges["component_fold"] = edges["merge_id"].map(fold_by_merge).astype(int)
    if args.member_labels:
        opus_targets = exact_edge_targets(edges, labels, "member_components")
        if args.member_label_mode == "consensus":
            sonnet_targets = exact_edge_targets(edges, labels, "sonnet_member_components")
            known = pd.Series(opus_targets == sonnet_targets, index=edges.index)
            edge_labels = opus_targets
            supervision = "exact member edges where Opus and Sonnet agree; disputed edges score-only"
        else:
            known_by_id = labels.set_index("merge_id")["member_labels_known"].astype(bool).to_dict()
            known = edges["merge_id"].map(known_by_id).fillna(False).astype(bool)
            edge_labels = opus_targets
            supervision = "Opus-primary exact member components; all finalized edges known"
    else:
        known = edges["verdict"].isin(["merge_all", "keep_separate"])
        edge_labels = (edges["verdict"] == "merge_all").astype(int).to_numpy()
        supervision = "weak deterministic edges from merge-all and keep-separate; subset identities excluded"
    if args.training_scope == "subset":
        if not args.member_labels:
            raise ValueError("subset training scope requires exact member labels")
        subset_by_id = (labels.set_index("merge_id")["member_verdict"] == "merge_subset").to_dict()
        known &= edges["merge_id"].map(subset_by_id).fillna(False).astype(bool)
        supervision = f"{supervision}; fitted only on exact subset rows"
    edge_counts = edges.groupby("merge_id")["merge_id"].transform("size")
    edge_weights = edges["training_weight"].fillna(1.0).to_numpy() / edge_counts.to_numpy()

    metrics: dict[str, Any] = {
        "status": f"train-only {supervision}",
        "edges": len(edges),
        "known_edges": int(known.sum()),
        "subset_edges_scored_only": int((~known).sum()),
        "candidates": {},
    }
    artifact: dict[str, Any] = {"models": {}, "features": {}}
    output_edges = edges[
        [
            "merge_id",
            "left_member_index",
            "right_member_index",
            "left_id",
            "right_id",
            "verdict",
            "component_fold",
        ]
    ].copy()
    for name, (feature_set, _, model) in model_specs().items():
        columns = list(
            {
                "direct": DIRECT_FEATURES,
                "context": CONTEXT_FEATURES,
                "rich_direct": RICH_DIRECT_FEATURES,
                "rich_context": RICH_CONTEXT_FEATURES,
            }[feature_set]
        )
        values = edges[columns].to_numpy(dtype=np.float32)
        oof = np.full(len(edges), np.nan)
        for fold in range(5):
            train_mask = known.to_numpy() & (edges["component_fold"].to_numpy() != fold)
            test_mask = edges["component_fold"].to_numpy() == fold
            fold_model = pickle.loads(pickle.dumps(model))
            fit_model(fold_model, values[train_mask], edge_labels[train_mask], edge_weights[train_mask])
            oof[test_mask] = fold_model.predict_proba(values[test_mask])[:, 1]
        if not np.isfinite(oof).all():
            raise ValueError(f"{name} left non-finite OOF predictions")
        fit_model(model, values[known], edge_labels[known], edge_weights[known])
        artifact["models"][name] = model
        artifact["features"][name] = columns
        output_edges[f"probability:{name}"] = oof
        metrics["candidates"][name] = {
            "feature_set": feature_set,
            "features": len(columns),
            "known_edge_ranking": ranking_metrics(edge_labels[known], oof[known]),
            "operation_oof": operation_metrics(labels, output_edges.assign(**{name: oof}), name),
        }
        print(name, metrics["candidates"][name]["known_edge_ranking"])

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output_edges.to_parquet(output / "member_compatibility_oof.parquet", index=False)
    with (output / "member_compatibility_models.pkl").open("wb") as destination:
        pickle.dump(artifact, destination)
    (output / "member_compatibility_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
