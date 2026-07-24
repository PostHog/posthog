"""Train report-pair relatedness and whole-merge safety models.

The 881 labels are train-only. Cross-fitting holds every connected report component
out together so the same report cannot appear on both sides of a fold. Review and
selection metadata are retained for analysis but are never model features.
"""

# ruff: noqa: T201

from __future__ import annotations

import re
import json
import math
import pickle
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CORPUS = LAB / "data" / "corpora" / "train"
LABELS = LAB / "labels" / "admission_repair" / "train_merge_labels.parquet"
OUTPUT = LAB / "data" / "groupjoin" / "20260711-merge-proposer-safety"
SEED = 20260711
EMBEDDING_DIMS = 64
PROTOTYPE_CAP = 64
SIG_FIELDS = ("tags", "surface", "failmode", "anchor", "oneliner")
TARGETS = ("reports_related", "whole_merge_safe")
SELECTED_FEATURE_SETS = {"reports_related": "geometry", "whole_merge_safe": "full"}


@dataclass(frozen=True)
class Signal:
    row: int
    product: str
    signal_type: str
    timestamp: float
    headline: str
    stack_site: str | None


@dataclass
class Report:
    size: int
    embeddings: np.ndarray
    prototypes: np.ndarray
    prototype_ids: list[str]
    centroid: np.ndarray
    centroid_sims: np.ndarray
    products: Counter[str]
    signal_types: Counter[str]
    timestamps: np.ndarray
    sig_unions: dict[str, set[str]]
    headlines: Counter[str]
    stack_sites: Counter[str]
    headline_sites: Counter[str]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as file:
        return [json.loads(line) for line in file]


def normalized_headline(text: str) -> str:
    value = str(text).replace("\x00", " ")
    before_fence = value.split("```", 1)[0]
    lines = [line.strip() for line in before_fence.splitlines() if line.strip()]
    generic = "New error tracking issue created - this particular exception was observed for the first time:"
    lines = [line for line in lines if line != generic]
    compact = re.sub(r"\s+", " ", " ".join(lines)).strip()[:620].lower()
    compact = re.sub(r"https?://\S+", "<url>", compact)
    compact = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", compact)
    compact = re.sub(r"\b\d{5,}\b", "<n>", compact)
    return re.sub(r"\s+", " ", compact).strip()


def first_stack_site(text: str) -> str | None:
    value = str(text)
    if "```" not in value:
        return None
    stack = value.split("```", 1)[1].split("```", 1)[0]
    lines = [line.strip() for line in stack.splitlines() if line.strip()]
    for frame in lines[1:6]:
        function = frame.split(" in ", 1)[0]
        token = re.sub(r"[^A-Za-z0-9_$]", "", function)
        if function not in {"?", "<anonymous>"} and len(token) >= 4:
            return function[:180]
    return None


def normalize_rows(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-8)


def stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def distribution(prefix: str, values: np.ndarray) -> dict[str, float]:
    if not len(values):
        return {f"{prefix}_{name}": 0.0 for name in ("min", "p10", "p25", "p50", "p75", "p90", "max", "mean", "std")}
    return {
        f"{prefix}_min": float(values.min()),
        f"{prefix}_p10": float(np.quantile(values, 0.10)),
        f"{prefix}_p25": float(np.quantile(values, 0.25)),
        f"{prefix}_p50": float(np.quantile(values, 0.50)),
        f"{prefix}_p75": float(np.quantile(values, 0.75)),
        f"{prefix}_p90": float(np.quantile(values, 0.90)),
        f"{prefix}_max": float(values.max()),
        f"{prefix}_mean": float(values.mean()),
        f"{prefix}_std": float(values.std()),
    }


def component_groups(frame: pd.DataFrame) -> np.ndarray:
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    source_rows: list[list[str]] = []
    source_values = frame["source_report_ids"] if "source_report_ids" in frame else [None] * len(frame)
    for source_value, left, right in zip(
        source_values,
        frame["left_report_id"],
        frame["right_report_id"],
        strict=True,
    ):
        parsed = json.loads(source_value) if isinstance(source_value, str) and source_value else []
        source_rows.append(list(map(str, parsed)) if parsed else [str(left), str(right)])
    for source_ids in source_rows:
        anchor = source_ids[0]
        for source_id in source_ids[1:]:
            union(anchor, source_id)
    return np.asarray([find(source_ids[0]) for source_ids in source_rows])


def report_prototype_indices(member_ids: list[str], embeddings: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    if len(member_ids) <= PROTOTYPE_CAP:
        return np.arange(len(member_ids))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        similarities = embeddings @ centroid
    if not np.isfinite(similarities).all():
        raise ValueError("non-finite report prototype similarities")
    candidates: list[int] = []
    candidates.extend(np.argsort(similarities)[:16].tolist())
    candidates.extend(np.argsort(similarities)[-16:].tolist())
    candidates.extend(range(max(0, len(member_ids) - 16), len(member_ids)))
    candidates.extend(sorted(range(len(member_ids)), key=lambda index: stable_hash(member_ids[index]))[:16])
    unique = list(dict.fromkeys(candidates))
    if len(unique) < PROTOTYPE_CAP:
        unique.extend(index for index in np.argsort(similarities)[::-1] if int(index) not in unique)
    return np.asarray(unique[:PROTOTYPE_CAP], dtype=np.int64)


def build_report(
    member_ids: list[str],
    signals: dict[str, Signal],
    embeddings: np.ndarray,
    signatures: dict[str, dict[str, set[str]]],
) -> Report:
    missing = [member for member in member_ids if member not in signals]
    if missing:
        raise KeyError(f"{len(missing)} report members are absent from the train corpus")
    rows = np.asarray([signals[member].row for member in member_ids], dtype=np.int64)
    member_embeddings = normalize_rows(np.asarray(embeddings[rows, :EMBEDDING_DIMS], dtype=np.float64))
    centroid = member_embeddings.mean(axis=0)
    centroid /= max(float(np.linalg.norm(centroid)), 1e-8)
    prototype_indices = report_prototype_indices(member_ids, member_embeddings, centroid)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        centroid_sims = member_embeddings @ centroid
    if not np.isfinite(centroid_sims).all():
        raise ValueError("non-finite within-report similarities")
    sig_unions = {
        field: set().union(*(signatures.get(member, {}).get(field, set()) for member in member_ids))
        for field in SIG_FIELDS
    }
    headlines = Counter(signals[member].headline for member in member_ids)
    stack_sites = Counter(signals[member].stack_site for member in member_ids if signals[member].stack_site)
    headline_sites = Counter(
        f"{signals[member].headline}\x1f{signals[member].stack_site}"
        for member in member_ids
        if signals[member].stack_site
    )
    return Report(
        size=len(member_ids),
        embeddings=member_embeddings,
        prototypes=member_embeddings[prototype_indices],
        prototype_ids=[member_ids[index] for index in prototype_indices],
        centroid=centroid,
        centroid_sims=centroid_sims,
        products=Counter(signals[member].product for member in member_ids),
        signal_types=Counter(signals[member].signal_type for member in member_ids),
        timestamps=np.asarray([signals[member].timestamp for member in member_ids], dtype=np.float64),
        sig_unions=sig_unions,
        headlines=headlines,
        stack_sites=stack_sites,
        headline_sites=headline_sites,
    )


def counter_jaccard(left: Counter[str], right: Counter[str]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left[key], right[key]) for key in keys)
    return sum(min(left[key], right[key]) for key in keys) / denominator if denominator else 0.0


def counter_support(left: Counter[str], right: Counter[str], denominator: int) -> float:
    return sum(count for key, count in left.items() if key in right) / max(denominator, 1)


def pair_features(left: Report, right: Report, signatures: dict[str, dict[str, set[str]]]) -> dict[str, float]:
    smaller, larger = sorted((left.size, right.size))
    features: dict[str, float] = {
        "shape_log_min_size": math.log1p(smaller),
        "shape_log_max_size": math.log1p(larger),
        "shape_log_total_size": math.log1p(smaller + larger),
        "shape_size_ratio": smaller / larger,
        "geometry_centroid_cosine": float(left.centroid @ right.centroid),
        "metadata_product_jaccard": counter_jaccard(left.products, right.products),
        "metadata_type_jaccard": counter_jaccard(left.signal_types, right.signal_types),
        "metadata_same_modal_product": float(left.products.most_common(1)[0][0] == right.products.most_common(1)[0][0]),
        "metadata_same_modal_type": float(
            left.signal_types.most_common(1)[0][0] == right.signal_types.most_common(1)[0][0]
        ),
    }
    left_headline_support = counter_support(left.headlines, right.headlines, left.size)
    right_headline_support = counter_support(right.headlines, left.headlines, right.size)
    left_stack_support = counter_support(left.stack_sites, right.stack_sites, left.size)
    right_stack_support = counter_support(right.stack_sites, left.stack_sites, right.size)
    left_pair_support = counter_support(left.headline_sites, right.headline_sites, left.size)
    right_pair_support = counter_support(right.headline_sites, left.headline_sites, right.size)
    left_modal_headline, left_modal_headline_count = left.headlines.most_common(1)[0]
    right_modal_headline, right_modal_headline_count = right.headlines.most_common(1)[0]
    left_modal_stack = left.stack_sites.most_common(1)[0] if left.stack_sites else (None, 0)
    right_modal_stack = right.stack_sites.most_common(1)[0] if right.stack_sites else (None, 0)
    features.update(
        {
            "text_headline_counter_jaccard": counter_jaccard(left.headlines, right.headlines),
            "text_stack_site_counter_jaccard": counter_jaccard(left.stack_sites, right.stack_sites),
            "text_headline_site_counter_jaccard": counter_jaccard(left.headline_sites, right.headline_sites),
            "text_same_modal_headline": float(left_modal_headline == right_modal_headline),
            "text_same_modal_stack_site": float(
                left_modal_stack[0] is not None and left_modal_stack[0] == right_modal_stack[0]
            ),
            "text_modal_headline_share_min": min(
                left_modal_headline_count / left.size, right_modal_headline_count / right.size
            ),
            "text_modal_stack_site_share_min": min(left_modal_stack[1] / left.size, right_modal_stack[1] / right.size),
            "text_headline_support_min": min(left_headline_support, right_headline_support),
            "text_headline_support_mean": (left_headline_support + right_headline_support) / 2,
            "text_stack_site_support_min": min(left_stack_support, right_stack_support),
            "text_stack_site_support_mean": (left_stack_support + right_stack_support) / 2,
            "text_headline_site_support_min": min(left_pair_support, right_pair_support),
            "text_headline_site_support_mean": (left_pair_support + right_pair_support) / 2,
            "text_same_headline_modal_stack_conflict": float(
                left_modal_headline == right_modal_headline
                and left_modal_stack[0] is not None
                and right_modal_stack[0] is not None
                and left_modal_stack[0] != right_modal_stack[0]
            ),
        }
    )
    left_start, left_end = float(left.timestamps.min()), float(left.timestamps.max())
    right_start, right_end = float(right.timestamps.min()), float(right.timestamps.max())
    gap = max(0.0, max(left_start, right_start) - min(left_end, right_end))
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    features.update(
        {
            "metadata_log_time_gap_seconds": math.log1p(gap),
            "metadata_log_combined_span_seconds": math.log1p(max(left_end, right_end) - min(left_start, right_start)),
            "metadata_time_overlap_fraction": overlap
            / max(max(left_end, right_end) - min(left_start, right_start), 1.0),
        }
    )
    for side, report in (("left", left), ("right", right)):
        features.update(distribution(f"cohesion_{side}", report.centroid_sims))
    for statistic in ("min", "p25", "p50", "mean"):
        left_value = features[f"cohesion_left_{statistic}"]
        right_value = features[f"cohesion_right_{statistic}"]
        features[f"cohesion_pair_min_{statistic}"] = min(left_value, right_value)
        features[f"cohesion_pair_absdiff_{statistic}"] = abs(left_value - right_value)

    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        cross = left.prototypes @ right.prototypes.T
    if not np.isfinite(cross).all():
        raise ValueError("non-finite cross-report similarities")
    flat = cross.ravel()
    features.update(distribution("geometry_cross", flat))
    for count in (1, 3, 5, 10, 20):
        take = min(count, len(flat))
        features[f"geometry_cross_top{count}_mean"] = float(np.partition(flat, len(flat) - take)[-take:].mean())
    left_best = cross.max(axis=1)
    right_best = cross.max(axis=0)
    features.update(distribution("geometry_left_best", left_best))
    features.update(distribution("geometry_right_best", right_best))
    for threshold in (0.50, 0.60, 0.70, 0.80, 0.90):
        left_fraction = float((left_best >= threshold).mean())
        right_fraction = float((right_best >= threshold).mean())
        key = str(threshold).replace(".", "")
        features[f"geometry_support_min_{key}"] = min(left_fraction, right_fraction)
        features[f"geometry_support_mean_{key}"] = (left_fraction + right_fraction) / 2

    for field in SIG_FIELDS:
        features[f"signature_union_{field}_jaccard"] = jaccard(left.sig_unions[field], right.sig_unions[field])
        matrix = np.zeros((len(left.prototype_ids), len(right.prototype_ids)), dtype=np.float32)
        for left_index, left_id in enumerate(left.prototype_ids):
            left_values = signatures.get(left_id, {}).get(field, set())
            for right_index, right_id in enumerate(right.prototype_ids):
                matrix[left_index, right_index] = jaccard(left_values, signatures.get(right_id, {}).get(field, set()))
        left_signature_best = matrix.max(axis=1)
        right_signature_best = matrix.max(axis=0)
        features[f"signature_member_{field}_max"] = float(matrix.max())
        features[f"signature_member_{field}_bidirectional_mean"] = float(
            (left_signature_best.mean() + right_signature_best.mean()) / 2
        )
        for threshold in (0.25, 0.50, 0.75):
            key = str(threshold).replace(".", "")
            features[f"signature_member_{field}_support_min_{key}"] = min(
                float((left_signature_best >= threshold).mean()),
                float((right_signature_best >= threshold).mean()),
            )
    return features


def score_predictions(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    return {
        "auc": float(roc_auc_score(labels, probabilities)),
        "average_precision": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "positive_rate": float(labels.mean()),
        "rows": int(len(labels)),
    }


def choose_threshold(labels: np.ndarray, probabilities: np.ndarray, precision_floor: float) -> dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    candidates = [
        (float(recall[index]), float(precision[index]), float(thresholds[index]))
        for index in range(len(thresholds))
        if precision[index] >= precision_floor
    ]
    if not candidates:
        index = int(np.argmax(precision[:-1]))
        return {
            "threshold": float(thresholds[index]),
            "precision": float(precision[index]),
            "recall": float(recall[index]),
        }
    best = max(candidates)
    return {"threshold": best[2], "precision": best[1], "recall": best[0]}


def choose_recall_threshold(labels: np.ndarray, probabilities: np.ndarray, recall_floor: float) -> dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    candidates = [
        (float(precision[index]), float(thresholds[index]), float(recall[index]))
        for index in range(len(thresholds))
        if recall[index] >= recall_floor
    ]
    if not candidates:
        index = int(np.argmax(recall[:-1]))
        return {
            "threshold": float(thresholds[index]),
            "precision": float(precision[index]),
            "recall": float(recall[index]),
        }
    best = max(candidates)
    return {"threshold": best[1], "precision": best[0], "recall": best[2]}


def fit_crossfit(
    features: pd.DataFrame,
    labels: np.ndarray,
    weights: np.ndarray,
    groups: np.ndarray,
    selected_columns: list[str],
) -> tuple[np.ndarray, list[dict[str, float | int]], HistGradientBoostingClassifier]:
    values = features[selected_columns].to_numpy(dtype=np.float32)
    predictions = np.zeros(len(features), dtype=np.float64)
    folds: list[dict[str, float | int]] = []
    splitter = GroupKFold(n_splits=5)
    for fold, (train_index, test_index) in enumerate(splitter.split(values, labels, groups)):
        model = HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.05,
            max_iter=200,
            min_samples_leaf=20,
            l2_regularization=2.0,
            random_state=SEED + fold,
        )
        model.fit(values[train_index], labels[train_index], sample_weight=weights[train_index])
        predictions[test_index] = model.predict_proba(values[test_index])[:, 1]
        folds.append(
            {
                "fold": fold,
                "train_rows": int(len(train_index)),
                "test_rows": int(len(test_index)),
                "train_positive_rate": float(labels[train_index].mean()),
                "test_positive_rate": float(labels[test_index].mean()),
                "test_components": int(len(set(groups[test_index]))),
            }
        )
    final_model = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.05,
        max_iter=200,
        min_samples_leaf=20,
        l2_regularization=2.0,
        random_state=SEED,
    )
    final_model.fit(values, labels, sample_weight=weights)
    return predictions, folds, final_model


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frame = pd.read_parquet(LABELS)
    feature_path = OUTPUT / "merge_pair_features.parquet"
    metadata_columns = ["merge_id", *TARGETS, "verdict", "training_weight"]
    if feature_path.exists():
        feature_output = pd.read_parquet(feature_path)
        if list(feature_output["merge_id"]) != list(frame["merge_id"]):
            raise ValueError("cached merge features do not match the current label ledger")
        features = feature_output.drop(columns=metadata_columns)
        print(f"reusing {len(features)} cached merge feature rows")
    else:
        signal_rows = load_jsonl(CORPUS / "signals.jsonl")
        signals = {
            str(row["id"]): Signal(
                row=index,
                product=str(row.get("product") or ""),
                signal_type=str(row.get("type") or ""),
                timestamp=float(row.get("ts") or 0.0),
                headline=normalized_headline(str(row.get("content") or "")),
                stack_site=first_stack_site(str(row.get("content") or "")),
            )
            for index, row in enumerate(signal_rows)
        }
        signatures: dict[str, dict[str, set[str]]] = {}
        with (CORPUS / "sigs.jsonl").open() as file:
            for line in file:
                row = json.loads(line)
                signatures[str(row["document_id"])] = {
                    field: {str(value) for value in row.get(field, [])} for field in SIG_FIELDS
                }
        embeddings = np.load(CORPUS / "embeddings.npy", mmap_mode="r")
        report_cache: dict[tuple[str, ...], Report] = {}
        feature_rows: list[dict[str, float]] = []
        for index, row in frame.iterrows():
            left_ids = json.loads(str(row["left_members"]))
            right_ids = json.loads(str(row["right_members"]))
            left_key, right_key = tuple(left_ids), tuple(right_ids)
            if left_key not in report_cache:
                report_cache[left_key] = build_report(left_ids, signals, embeddings, signatures)
            if right_key not in report_cache:
                report_cache[right_key] = build_report(right_ids, signals, embeddings, signatures)
            feature_rows.append(pair_features(report_cache[left_key], report_cache[right_key], signatures))
            if (index + 1) % 100 == 0:
                print(f"features: {index + 1}/{len(frame)}")
        features = pd.DataFrame(feature_rows).sort_index(axis=1)
        feature_output = pd.concat([frame[metadata_columns].reset_index(drop=True), features], axis=1)
        feature_output.to_parquet(feature_path, index=False)
    groups = component_groups(frame)
    fold_ids = np.full(len(frame), -1, dtype=np.int64)
    for fold, (_, test_index) in enumerate(GroupKFold(n_splits=5).split(features, frame["whole_merge_safe"], groups)):
        fold_ids[test_index] = fold
    weights = frame["training_weight"].to_numpy(dtype=np.float64)
    feature_sets = {
        "shape": [column for column in features if column.startswith(("shape_", "metadata_"))],
        "geometry": [
            column for column in features if column.startswith(("shape_", "metadata_", "cohesion_", "geometry_"))
        ],
        "signature": [column for column in features if column.startswith(("shape_", "metadata_", "signature_"))],
        "full": list(features.columns),
    }
    metrics: dict[str, Any] = {
        "status": "train-only report-component cross-fit; proposer and whole-merge safety are separate outputs",
        "rows": len(frame),
        "reports": len(set(frame["left_report_id"]) | set(frame["right_report_id"])),
        "components": len(set(groups)),
        "feature_count": len(features.columns),
        "feature_sets": {name: len(columns) for name, columns in feature_sets.items()},
        "targets": {},
    }
    oof = frame[["merge_id", *TARGETS, "verdict", "policy", "training_weight"]].copy()
    oof["component_fold"] = fold_ids
    final_models: dict[str, HistGradientBoostingClassifier] = {}
    ablation_models: dict[str, dict[str, HistGradientBoostingClassifier]] = {target: {} for target in TARGETS}
    full_folds: list[dict[str, float | int]] | None = None
    for target in TARGETS:
        labels = frame[target].astype(int).to_numpy()
        selected_feature_set = SELECTED_FEATURE_SETS[target]
        target_metrics: dict[str, Any] = {
            "ablations": {},
            "selected_feature_set": selected_feature_set,
        }
        for feature_set, columns in feature_sets.items():
            predictions, folds, final_model = fit_crossfit(features, labels, weights, groups, columns)
            ablation_models[target][feature_set] = final_model
            target_metrics["ablations"][feature_set] = score_predictions(labels, predictions)
            if feature_set == selected_feature_set:
                oof[f"{target}_probability"] = predictions
                final_models[target] = final_model
                full_folds = folds
                target_metrics["selected"] = score_predictions(labels, predictions)
                target_metrics["threshold_precision_080"] = choose_threshold(labels, predictions, 0.80)
                target_metrics["threshold_precision_090"] = choose_threshold(labels, predictions, 0.90)
                target_metrics["threshold_precision_095"] = choose_threshold(labels, predictions, 0.95)
                target_metrics["threshold_precision_098"] = choose_threshold(labels, predictions, 0.98)
                target_metrics["threshold_recall_085"] = choose_recall_threshold(labels, predictions, 0.85)
                target_metrics["by_policy"] = {
                    policy: score_predictions(labels[frame["policy"] == policy], predictions[frame["policy"] == policy])
                    for policy in sorted(frame["policy"].unique())
                }
                target_metrics["by_fold"] = {
                    str(fold): score_predictions(labels[fold_ids == fold], predictions[fold_ids == fold])
                    for fold in range(5)
                }
                if target == "whole_merge_safe":
                    related = frame["reports_related"].to_numpy(dtype=bool)
                    target_metrics["related_pairs_only"] = score_predictions(labels[related], predictions[related])
        metrics["targets"][target] = target_metrics
    metrics["folds"] = full_folds

    proposer = metrics["targets"]["reports_related"]["threshold_recall_085"]
    proposer_pass = oof["reports_related_probability"].to_numpy() >= proposer["threshold"]
    truth = frame["whole_merge_safe"].to_numpy(dtype=bool)
    metrics["cascade"] = {
        "proposer": {
            "threshold": proposer["threshold"],
            "proposed_pairs": int(proposer_pass.sum()),
            "precision": proposer["precision"],
            "recall": proposer["recall"],
            "whole_merge_recall": float(proposer_pass[truth].mean()),
            "subset_rescue_recall": float(proposer_pass[frame["subset_rescue"].to_numpy(dtype=bool)].mean()),
            "keep_separate_proposal_rate": float(proposer_pass[~frame["reports_related"].to_numpy(dtype=bool)].mean()),
        },
        "safety_profiles": {},
    }
    for floor in (0.90, 0.95, 0.98):
        safety = metrics["targets"]["whole_merge_safe"][f"threshold_precision_{int(floor * 100):03d}"]
        predictions = proposer_pass & (oof["whole_merge_safe_probability"].to_numpy() >= safety["threshold"])
        true_positive = int((predictions & truth).sum())
        metrics["cascade"]["safety_profiles"][f"precision_{floor:.2f}"] = {
            "safety_threshold": safety["threshold"],
            "executed_whole_merges": int(predictions.sum()),
            "precision": true_positive / max(int(predictions.sum()), 1),
            "recall": true_positive / int(truth.sum()),
            "false_whole_merges": int((predictions & ~truth).sum()),
        }
    selected_safety = metrics["targets"]["whole_merge_safe"]["threshold_precision_095"]
    oof.to_parquet(OUTPUT / "merge_oof.parquet", index=False)
    with (OUTPUT / "merge_models.pkl").open("wb") as file:
        pickle.dump(
            {
                "models": final_models,
                "ablation_models": ablation_models,
                "feature_columns": {
                    target: feature_sets[feature_set] for target, feature_set in SELECTED_FEATURE_SETS.items()
                },
                "selected_feature_sets": SELECTED_FEATURE_SETS,
                "proposer_threshold": proposer["threshold"],
                "safety_threshold": selected_safety["threshold"],
                "embedding_dims": EMBEDDING_DIMS,
                "prototype_cap": PROTOTYPE_CAP,
            },
            file,
        )
    (OUTPUT / "merge_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
