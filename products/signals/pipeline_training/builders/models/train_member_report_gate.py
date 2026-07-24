"""Train a report-pair relatedness gate over frozen member-edge score summaries."""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from train_merge_proposer_safety import component_groups

SEED = 11
SCORE_NAMES = ("context-logistic", "direct-hgb-d3", "rich-context-logistic")


def _quantile(values: pd.Series, quantile: float) -> float:
    return float(values.quantile(quantile))


def _score_features(edges: pd.DataFrame, score_column: str, name: str) -> pd.DataFrame:
    grouped = edges.groupby("merge_id", sort=False)[score_column]
    report = grouped.agg(
        **{
            f"{name}_edge_max": "max",
            f"{name}_edge_mean": "mean",
            f"{name}_edge_q90": lambda values: _quantile(values, 0.90),
            f"{name}_edge_q95": lambda values: _quantile(values, 0.95),
            f"{name}_edge_q99": lambda values: _quantile(values, 0.99),
        }
    )
    for side, member_column in (("left", "left_member_index"), ("right", "right_member_index")):
        best = edges.groupby(["merge_id", member_column], sort=False)[score_column].max()
        by_report = best.groupby(level=0, sort=False)
        support = by_report.agg(
            **{
                f"{name}_{side}_best_q10": lambda values: _quantile(values, 0.10),
                f"{name}_{side}_best_median": "median",
                f"{name}_{side}_best_mean": "mean",
                f"{name}_{side}_best_min": "min",
            }
        )
        for threshold in (0.30, 0.50, 0.70, 0.85):
            support[f"{name}_{side}_share_ge_{threshold:.2f}"] = by_report.apply(
                lambda values, cutoff=threshold: float((values >= cutoff).mean()),
                include_groups=False,
            )
        report = report.join(support, how="left")
    mutual = edges.loc[edges["mutual_top_k"]].groupby("merge_id", sort=False)[score_column]
    mutual_frame = mutual.agg(
        **{
            f"{name}_mutual_max": "max",
            f"{name}_mutual_mean": "mean",
            f"{name}_mutual_q90": lambda values: _quantile(values, 0.90),
            f"{name}_mutual_count": "count",
        }
    )
    return report.join(mutual_frame, how="left").fillna(0.0)


def build_report_features(labels: pd.DataFrame, predictions: pd.DataFrame, edge_context: pd.DataFrame) -> pd.DataFrame:
    context = edge_context[["merge_id", "left_member_index", "right_member_index", "mutual_top_k"]]
    edges = predictions.merge(
        context,
        on=["merge_id", "left_member_index", "right_member_index"],
        how="left",
        validate="one_to_one",
    )
    edges["mutual_top_k"] = edges["mutual_top_k"].fillna(False).astype(bool)
    base = labels[["merge_id", "left_size", "right_size"]].set_index("merge_id").copy()
    base["combined_size_log"] = np.log1p(base["left_size"] + base["right_size"])
    base["left_size_log"] = np.log1p(base["left_size"])
    base["right_size_log"] = np.log1p(base["right_size"])
    base["size_ratio"] = np.minimum(base["left_size"], base["right_size"]) / np.maximum(
        base["left_size"], base["right_size"]
    )
    for name in SCORE_NAMES:
        base = base.join(_score_features(edges, f"probability:{name}", name), how="left")
    if base.isna().any().any():
        missing = base.columns[base.isna().any()].tolist()
        raise ValueError(f"missing report-gate features: {missing}")
    return base.reset_index()


def model_specs() -> dict[str, Any]:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        "hgb-d2": HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=30, random_state=SEED),
        "hgb-d3": HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=30, random_state=SEED),
    }


def _fit(model: Any, values: np.ndarray, targets: np.ndarray, weights: np.ndarray) -> None:
    if hasattr(model, "named_steps"):
        model.fit(values, targets, logisticregression__sample_weight=weights)
    else:
        model.fit(values, targets, sample_weight=weights)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    labels = pd.read_parquet(args.labels)
    predictions = pd.read_parquet(args.predictions)
    edge_context = pd.read_parquet(args.edge_context)
    frame = build_report_features(labels, predictions, edge_context)
    label_by_id = labels.set_index("merge_id")
    frame["target"] = frame["merge_id"].map((label_by_id["member_verdict"] != "keep_separate").astype(int))
    frame["training_weight"] = frame["merge_id"].map(label_by_id["training_weight"].fillna(1.0))

    report_groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    splitter = GroupKFold(n_splits=5)
    for fold, (_, test_indices) in enumerate(splitter.split(labels, labels["member_verdict"], report_groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    frame["component_fold"] = frame["merge_id"].astype(str).map(fold_by_id).astype(int)

    excluded = {"merge_id", "target", "training_weight", "component_fold"}
    feature_columns = [column for column in frame if column not in excluded]
    values = frame[feature_columns].to_numpy(dtype=np.float32)
    targets = frame["target"].to_numpy(dtype=np.int8)
    weights = frame["training_weight"].to_numpy(dtype=np.float64)
    output_predictions = frame[["merge_id", "target", "component_fold"]].copy()
    artifact: dict[str, Any] = {"features": feature_columns, "models": {}}
    metrics: dict[str, Any] = {
        "status": "component-held-out report relatedness gate over frozen top-24 member scores",
        "rows": len(frame),
        "positive_rate": float(targets.mean()),
        "candidates": {},
    }
    for name, model in model_specs().items():
        oof = np.full(len(frame), np.nan)
        for fold in range(5):
            train_mask = frame["component_fold"].to_numpy() != fold
            test_mask = ~train_mask
            fold_model = pickle.loads(pickle.dumps(model))
            _fit(fold_model, values[train_mask], targets[train_mask], weights[train_mask])
            oof[test_mask] = fold_model.predict_proba(values[test_mask])[:, 1]
        if not np.isfinite(oof).all():
            raise ValueError(f"{name} produced non-finite OOF predictions")
        _fit(model, values, targets, weights)
        artifact["models"][name] = model
        output_predictions[f"probability:{name}"] = oof
        metrics["candidates"][name] = {
            "auc": float(roc_auc_score(targets, oof)),
            "average_precision": float(average_precision_score(targets, oof)),
        }
        print(name, metrics["candidates"][name])

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    output_predictions.to_parquet(output / "report_gate_oof.parquet", index=False)
    with (output / "report_gate_models.pkl").open("wb") as target:
        pickle.dump(artifact, target)
    (output / "report_gate_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
