"""Train a direct member-selection head from frozen top-24 edge evidence."""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from evaluate_exact_member_components import parse_components, selected
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from train_merge_proposer_safety import component_groups

SEED = 13
SCORE_NAMES = ("context-logistic", "direct-hgb-d3", "rich-context-logistic")


def _quantile(values: pd.Series, quantile: float) -> float:
    return float(values.quantile(quantile))


def _side_features(edges: pd.DataFrame, side: str) -> pd.DataFrame:
    member_column = f"{side}_member_index"
    keys = ["merge_id", member_column]
    summaries: list[pd.DataFrame] = []
    for score_name in SCORE_NAMES:
        score_column = f"probability:{score_name}"
        grouped = edges.groupby(keys, sort=False)[score_column]
        summary = grouped.agg(
            **{
                f"{score_name}_max": "max",
                f"{score_name}_mean": "mean",
                f"{score_name}_q75": lambda values: _quantile(values, 0.75),
                f"{score_name}_q90": lambda values: _quantile(values, 0.90),
            }
        )
        second = grouped.nlargest(2).groupby(level=[0, 1]).min()
        summary[f"{score_name}_margin"] = summary[f"{score_name}_max"] - second
        for threshold in (0.30, 0.50, 0.70, 0.85):
            summary[f"{score_name}_share_ge_{threshold:.2f}"] = grouped.apply(
                lambda values, cutoff=threshold: float((values >= cutoff).mean()),
                include_groups=False,
            )
        mutual = edges.loc[edges["mutual_top_k"]].groupby(keys, sort=False)[score_column].max()
        summary[f"{score_name}_mutual_max"] = mutual
        summaries.append(summary)
    frame = pd.concat(summaries, axis=1).fillna(0.0)
    raw = edges.groupby(keys, sort=False).agg(
        pair_raw_max=("pair_raw", "max"),
        pair_raw_mean=("pair_raw", "mean"),
        pair_cal_max=("pair_cal", "max"),
        embedding_cosine_max=("embedding_cosine", "max"),
    )
    frame = frame.join(raw, how="left").reset_index().rename(columns={member_column: "member_index"})
    frame["side_left"] = float(side == "left")
    return frame


def build_member_features(
    labels: pd.DataFrame,
    member_predictions: pd.DataFrame,
    edge_context: pd.DataFrame,
    report_predictions: pd.DataFrame,
) -> pd.DataFrame:
    context_columns = [
        "merge_id",
        "left_member_index",
        "right_member_index",
        "mutual_top_k",
        "pair_raw",
        "pair_cal",
        "embedding_cosine",
    ]
    edges = member_predictions.merge(
        edge_context[context_columns],
        on=["merge_id", "left_member_index", "right_member_index"],
        how="left",
        validate="one_to_one",
    )
    edges["mutual_top_k"] = edges["mutual_top_k"].fillna(False).astype(bool)
    frame = pd.concat([_side_features(edges, "left"), _side_features(edges, "right")], ignore_index=True)
    sizes = labels[["merge_id", "left_size", "right_size"]]
    frame = frame.merge(sizes, on="merge_id", how="left", validate="many_to_one")
    frame["member_side_size"] = np.where(frame["side_left"] == 1.0, frame["left_size"], frame["right_size"])
    frame["opposite_side_size"] = np.where(frame["side_left"] == 1.0, frame["right_size"], frame["left_size"])
    frame["member_side_size_log"] = np.log1p(frame["member_side_size"])
    frame["opposite_side_size_log"] = np.log1p(frame["opposite_side_size"])
    frame["combined_size_log"] = np.log1p(frame["left_size"] + frame["right_size"])
    for score_name in SCORE_NAMES:
        maximum = f"{score_name}_max"
        report_max = frame.groupby(["merge_id", "side_left"], sort=False)[maximum].transform("max").clip(lower=1e-6)
        frame[f"{score_name}_relative_to_report_max"] = frame[maximum] / report_max
        frame[f"{score_name}_member_rank_share"] = frame.groupby(["merge_id", "side_left"], sort=False)[maximum].rank(
            method="average", ascending=False
        ) / frame["member_side_size"].clip(lower=1)
    report_columns = ["merge_id", *(column for column in report_predictions if column.startswith("probability:"))]
    report_frame = report_predictions[report_columns].rename(
        columns={column: f"report_gate_{column.removeprefix('probability:')}" for column in report_columns[1:]}
    )
    frame = frame.merge(report_frame, on="merge_id", how="left", validate="many_to_one")
    if frame.isna().any().any():
        missing = frame.columns[frame.isna().any()].tolist()
        raise ValueError(f"missing member-selector features: {missing}")
    return frame


def add_targets(frame: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    target_sets: dict[tuple[str, float], set[int]] = {}
    for row in labels.itertuples(index=False):
        components = parse_components(str(row.member_components))
        target_sets[(str(row.merge_id), 1.0)] = selected(components, 0)
        target_sets[(str(row.merge_id), 0.0)] = selected(components, 1)
    output = frame.copy()
    output["target"] = [
        int(int(row.member_index) in target_sets[(str(row.merge_id), float(row.side_left))])
        for row in output.itertuples(index=False)
    ]
    return output


def model_specs() -> dict[str, Any]:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000)),
        "hgb-d2": HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=80, random_state=SEED),
        "hgb-d3": HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=80, random_state=SEED),
    }


def _fit(model: Any, values: np.ndarray, targets: np.ndarray, weights: np.ndarray) -> None:
    if hasattr(model, "named_steps"):
        model.fit(values, targets, logisticregression__sample_weight=weights)
    else:
        model.fit(values, targets, sample_weight=weights)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--member-predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--report-predictions", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--training-scope", choices=("all", "subset"), default="all")
    args = parser.parse_args()

    labels = pd.read_parquet(args.labels)
    frame = add_targets(
        build_member_features(
            labels,
            pd.read_parquet(args.member_predictions),
            pd.read_parquet(args.edge_context),
            pd.read_parquet(args.report_predictions),
        ),
        labels,
    )
    report_groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    splitter = GroupKFold(n_splits=5)
    for fold, (_, test_indices) in enumerate(splitter.split(labels, labels["member_verdict"], report_groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    frame["component_fold"] = frame["merge_id"].astype(str).map(fold_by_id).astype(int)
    label_by_id = labels.set_index("merge_id")
    frame["member_verdict"] = frame["merge_id"].map(label_by_id["member_verdict"])
    frame["training_weight"] = frame["merge_id"].map(label_by_id["training_weight"].fillna(1.0)) / (
        frame["left_size"] + frame["right_size"]
    )
    eligible = (
        pd.Series(True, index=frame.index)
        if args.training_scope == "all"
        else frame["member_verdict"] == "merge_subset"
    )
    positive_weight = frame.loc[eligible & (frame["target"] == 1), "training_weight"].sum()
    negative_weight = frame.loc[eligible & (frame["target"] == 0), "training_weight"].sum()
    frame.loc[eligible & (frame["target"] == 1), "training_weight"] *= 0.5 / positive_weight
    frame.loc[eligible & (frame["target"] == 0), "training_weight"] *= 0.5 / negative_weight
    excluded = {"merge_id", "member_index", "target", "component_fold", "training_weight", "member_verdict"}
    feature_columns = [column for column in frame if column not in excluded]
    values = frame[feature_columns].to_numpy(dtype=np.float32)
    targets = frame["target"].to_numpy(dtype=np.int8)
    weights = frame["training_weight"].to_numpy(dtype=np.float64)
    predictions = frame[["merge_id", "side_left", "member_index", "target", "component_fold"]].copy()
    artifact: dict[str, Any] = {"features": feature_columns, "training_scope": args.training_scope, "models": {}}
    metrics: dict[str, Any] = {
        "status": f"component-held-out direct member selection over frozen top-24 evidence; {args.training_scope} training scope",
        "member_rows": len(frame),
        "training_rows": int(eligible.sum()),
        "positive_rate": float(targets.mean()),
        "candidates": {},
    }
    for name, model in model_specs().items():
        oof = np.full(len(frame), np.nan)
        for fold in range(5):
            train_mask = eligible.to_numpy() & (frame["component_fold"].to_numpy() != fold)
            test_mask = frame["component_fold"].to_numpy() == fold
            fold_model = pickle.loads(pickle.dumps(model))
            _fit(fold_model, values[train_mask], targets[train_mask], weights[train_mask])
            oof[test_mask] = fold_model.predict_proba(values[test_mask])[:, 1]
        if not np.isfinite(oof).all():
            raise ValueError(f"{name} produced non-finite OOF predictions")
        _fit(model, values[eligible], targets[eligible], weights[eligible])
        artifact["models"][name] = model
        predictions[f"probability:{name}"] = oof
        metrics["candidates"][name] = {
            "auc": float(roc_auc_score(targets[eligible], oof[eligible])),
            "average_precision": float(average_precision_score(targets[eligible], oof[eligible])),
        }
        print(name, metrics["candidates"][name])

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output / "member_selector_oof.parquet", index=False)
    with (output / "member_selector_models.pkl").open("wb") as target:
        pickle.dump(artifact, target)
    (output / "member_selector_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
