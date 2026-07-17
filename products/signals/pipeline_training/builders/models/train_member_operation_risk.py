"""Train a pre-mutation risk gate for member-aware report-pair proposals.

The member selectors are proposal models. This gate answers the narrower serving
question: if the selected members were moved into one report, would every moved
member belong to one labelled cross-report component? Partial recovery of one
component is safe; mixing components or activating a keep-separate pair is not.
"""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from evaluate_exact_member_components import parse_components
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from train_merge_proposer_safety import component_groups

SEED = 23
MEMBER_THRESHOLDS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.94, 0.96, 0.98)
SCORE_NAMES = ("context-logistic", "direct-hgb-d3", "rich-context-logistic")
REPORT_GATE_NAMES = ("logistic", "hgb-d2", "hgb-d3")
TRUST_WEIGHTS = {
    "deterministic_pair_operation": 1.00,
    "four_way_exact": 1.00,
    "v3_reader_exact": 0.90,
    "stable_high_overlap": 0.75,
    "direct_disputed": 0.45,
    "on_policy_dual_reader_exact": 1.00,
    "on_policy_verdict_agree": 0.75,
    "on_policy_disputed": 0.45,
}


def quantile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q)) if len(values) else 0.0


def summarize_probabilities(prefix: str, values: np.ndarray) -> dict[str, float]:
    if not len(values):
        return {
            f"{prefix}_min": 0.0,
            f"{prefix}_q10": 0.0,
            f"{prefix}_median": 0.0,
            f"{prefix}_mean": 0.0,
            f"{prefix}_q90": 0.0,
            f"{prefix}_max": 0.0,
        }
    return {
        f"{prefix}_min": float(values.min()),
        f"{prefix}_q10": quantile(values, 0.10),
        f"{prefix}_median": quantile(values, 0.50),
        f"{prefix}_mean": float(values.mean()),
        f"{prefix}_q90": quantile(values, 0.90),
        f"{prefix}_max": float(values.max()),
    }


def safe_target(label: pd.Series, selected_left: set[int], selected_right: set[int]) -> int:
    if not selected_left or not selected_right:
        return 0
    for component_left, component_right in parse_components(str(label["member_components"])):
        if selected_left <= component_left and selected_right <= component_right:
            return 1
    return 0


def proposal_features(
    label: pd.Series,
    member_rows: pd.DataFrame,
    edge_rows: pd.DataFrame,
    report_row: pd.Series,
    member_threshold: float,
) -> tuple[dict[str, float], int, bool]:
    left = member_rows.loc[member_rows["side_left"] == 1.0].sort_values("member_index")
    right = member_rows.loc[member_rows["side_left"] == 0.0].sort_values("member_index")
    probability_column = next(column for column in member_rows if column.startswith("probability:"))
    left_probabilities = left[probability_column].to_numpy(np.float64)
    right_probabilities = right[probability_column].to_numpy(np.float64)
    left_selected_mask = left_probabilities >= member_threshold
    right_selected_mask = right_probabilities >= member_threshold
    selected_left = set(left.loc[left_selected_mask, "member_index"].astype(int))
    selected_right = set(right.loc[right_selected_mask, "member_index"].astype(int))
    two_sided = bool(selected_left and selected_right)
    selected_probabilities = np.concatenate(
        [left_probabilities[left_selected_mask], right_probabilities[right_selected_mask]]
    )
    unselected_probabilities = np.concatenate(
        [left_probabilities[~left_selected_mask], right_probabilities[~right_selected_mask]]
    )
    left_size = int(label["left_size"])
    right_size = int(label["right_size"])
    selected_count = len(selected_left) + len(selected_right)
    features: dict[str, float] = {
        "member_threshold": member_threshold,
        "left_size": float(left_size),
        "right_size": float(right_size),
        "left_size_log": float(np.log1p(left_size)),
        "right_size_log": float(np.log1p(right_size)),
        "combined_size_log": float(np.log1p(left_size + right_size)),
        "size_ratio": min(left_size, right_size) / max(left_size, right_size, 1),
        "selected_left_count": float(len(selected_left)),
        "selected_right_count": float(len(selected_right)),
        "selected_count": float(selected_count),
        "selected_left_share": len(selected_left) / max(left_size, 1),
        "selected_right_share": len(selected_right) / max(right_size, 1),
        "selected_combined_share": selected_count / max(left_size + right_size, 1),
        "selected_side_balance": min(len(selected_left), len(selected_right))
        / max(len(selected_left), len(selected_right), 1),
        "left_full": float(len(selected_left) == left_size),
        "right_full": float(len(selected_right) == right_size),
        "whole_merge": float(len(selected_left) == left_size and len(selected_right) == right_size),
    }
    features.update(summarize_probabilities("selected_probability", selected_probabilities))
    features.update(summarize_probabilities("unselected_probability", unselected_probabilities))
    features["mask_boundary_margin"] = features["selected_probability_min"] - features["unselected_probability_max"]
    for name in REPORT_GATE_NAMES:
        features[f"report_gate_{name}"] = float(report_row[f"probability:{name}"])

    selected_edges = edge_rows.loc[
        edge_rows["left_member_index"].astype(int).isin(selected_left)
        & edge_rows["right_member_index"].astype(int).isin(selected_right)
    ]
    for name in SCORE_NAMES:
        values = selected_edges[f"probability:{name}"].to_numpy(np.float64)
        features.update(summarize_probabilities(f"selected_edge_{name}", values))
        for threshold in (0.30, 0.50, 0.70, 0.85):
            features[f"selected_edge_{name}_share_ge_{threshold:.2f}"] = (
                float((values >= threshold).mean()) if len(values) else 0.0
            )
        left_best = selected_edges.groupby("left_member_index")[f"probability:{name}"].max().to_numpy(np.float64)
        right_best = selected_edges.groupby("right_member_index")[f"probability:{name}"].max().to_numpy(np.float64)
        features[f"selected_edge_{name}_left_best_min"] = float(left_best.min()) if len(left_best) else 0.0
        features[f"selected_edge_{name}_left_best_mean"] = float(left_best.mean()) if len(left_best) else 0.0
        features[f"selected_edge_{name}_right_best_min"] = float(right_best.min()) if len(right_best) else 0.0
        features[f"selected_edge_{name}_right_best_mean"] = float(right_best.mean()) if len(right_best) else 0.0
    return features, safe_target(label, selected_left, selected_right), two_sided


def build_frame(
    labels: pd.DataFrame,
    member_predictions: pd.DataFrame,
    edge_predictions: pd.DataFrame,
    report_predictions: pd.DataFrame,
) -> pd.DataFrame:
    label_by_id = labels.set_index("merge_id")
    member_groups = {str(key): value for key, value in member_predictions.groupby("merge_id", sort=False)}
    edge_groups = {str(key): value for key, value in edge_predictions.groupby("merge_id", sort=False)}
    report_by_id = report_predictions.set_index("merge_id")
    rows: list[dict[str, Any]] = []
    for merge_id, label in label_by_id.iterrows():
        merge_id = str(merge_id)
        member_rows = member_groups[merge_id]
        edge_rows = edge_groups[merge_id]
        for threshold in MEMBER_THRESHOLDS:
            features, target, two_sided = proposal_features(
                label,
                member_rows,
                edge_rows,
                report_by_id.loc[merge_id],
                threshold,
            )
            rows.append(
                {
                    "merge_id": merge_id,
                    "member_label_tier": str(label["member_label_tier"]),
                    "member_verdict": str(label["member_verdict"]),
                    "training_weight": float(label["training_weight"]) * TRUST_WEIGHTS[str(label["member_label_tier"])],
                    "target": target,
                    "two_sided": two_sided,
                    **features,
                }
            )
    return pd.DataFrame(rows)


def model_specs() -> dict[str, Any]:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        "hgb-d2": HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=80, random_state=SEED),
        "hgb-d3": HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=80, random_state=SEED),
    }


def fit(model: Any, values: np.ndarray, targets: np.ndarray, weights: np.ndarray) -> None:
    if hasattr(model, "named_steps"):
        model.fit(values, targets, logisticregression__sample_weight=weights)
    else:
        model.fit(values, targets, sample_weight=weights)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=("contextual", "bipartite"), required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--member-predictions", required=True)
    parser.add_argument("--edge-predictions", required=True)
    parser.add_argument("--report-predictions", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    labels = pd.read_parquet(args.labels)
    frame = build_frame(
        labels,
        pd.read_parquet(args.member_predictions),
        pd.read_parquet(
            args.edge_predictions,
            columns=[
                "merge_id",
                "left_member_index",
                "right_member_index",
                *(f"probability:{name}" for name in SCORE_NAMES),
            ],
        ),
        pd.read_parquet(args.report_predictions),
    )
    eligible = frame["two_sided"].to_numpy(bool)
    report_groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    for fold, (_, test_indices) in enumerate(GroupKFold(5).split(labels, labels["member_verdict"], report_groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    frame["component_fold"] = frame["merge_id"].map(fold_by_id).astype(int)

    excluded = {
        "merge_id",
        "member_label_tier",
        "member_verdict",
        "training_weight",
        "target",
        "two_sided",
        "component_fold",
    }
    feature_columns = [column for column in frame if column not in excluded]
    values = frame[feature_columns].to_numpy(np.float32)
    targets = frame["target"].to_numpy(np.int8)
    weights = frame["training_weight"].to_numpy(np.float64)
    predictions = frame[
        ["merge_id", "member_threshold", "member_label_tier", "member_verdict", "target", "two_sided", "component_fold"]
    ].copy()
    artifact: dict[str, Any] = {
        "architecture": args.architecture,
        "target_contract": "selected members from both sides are contained by one labelled cross-report component",
        "member_thresholds": MEMBER_THRESHOLDS,
        "features": feature_columns,
        "models": {},
    }
    metrics: dict[str, Any] = {
        "status": "train-only component-held-out pre-mutation member-operation risk gate",
        "architecture": args.architecture,
        "proposal_rows": len(frame),
        "two_sided_rows": int(eligible.sum()),
        "two_sided_positive_rate": float(targets[eligible].mean()),
        "candidates": {},
    }
    for name, model in model_specs().items():
        oof = np.full(len(frame), np.nan)
        for fold in range(5):
            train_mask = eligible & (frame["component_fold"].to_numpy() != fold)
            test_mask = eligible & (frame["component_fold"].to_numpy() == fold)
            fold_model = pickle.loads(pickle.dumps(model))
            fit(fold_model, values[train_mask], targets[train_mask], weights[train_mask])
            oof[test_mask] = fold_model.predict_proba(values[test_mask])[:, 1]
        fit(model, values[eligible], targets[eligible], weights[eligible])
        artifact["models"][name] = model
        predictions[f"probability:{name}"] = oof
        metrics["candidates"][name] = {
            "auc": float(roc_auc_score(targets[eligible], oof[eligible])),
            "average_precision": float(average_precision_score(targets[eligible], oof[eligible])),
        }
        print(name, metrics["candidates"][name], flush=True)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output / "operation_risk_oof.parquet", index=False)
    with (output / "operation_risk_models.pkl").open("wb") as target:
        pickle.dump(artifact, target)
    (output / "operation_risk_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()
