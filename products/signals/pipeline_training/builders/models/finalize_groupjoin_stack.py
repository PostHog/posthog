"""Finalize the leakage-safe neural-representation + tree groupjoin lineage.

The binary direct-neural trainer emits a pooled representation for every tuple
from an encoder that did not see that tuple's clone-linkage fold. This script
fits the served tree on those OOF pools, exports it into a models.json, and
keeps the direct neural join head out of the decision path.

Run from lab/2:
    python models/finalize_groupjoin_stack.py \
        --build data/groupjoin/<build-id> \
        --base-models data/groupjoin/<build-id>/models-tree-nomixed.json
"""

# ruff: noqa: T201

from __future__ import annotations

import sys
import json
import pickle
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

HERE = Path(__file__).resolve().parent
LAB2 = HERE.parent
sys.path.insert(0, str(LAB2))
from models.export_models import dump_gbdt  # noqa: E402
from models.groupjoin_features import ENGINEERED_FEATURE_NAMES  # noqa: E402
from models.train_groupjoin import N_FOLDS, attach_folds  # noqa: E402

# Match the already reported stack ablation exactly. HistGradientBoosting's
# internal early-stopping split is seed-sensitive on this frame.
SEED = 29
POOL_DIMS = 32
POOL_FEATURE_NAMES = [f"dsm_{index}" for index in range(POOL_DIMS)]


def metric_set(
    y: np.ndarray,
    raw: np.ndarray,
    calibrated: np.ndarray,
    weight: np.ndarray,
    selected: np.ndarray,
) -> dict[str, float]:
    return {
        "rows": float(selected.sum()),
        "positive_rate": float(np.average(y[selected], weights=weight[selected])),
        "auc_raw": float(roc_auc_score(y[selected], raw[selected], sample_weight=weight[selected])),
        "ap_raw": float(average_precision_score(y[selected], raw[selected], sample_weight=weight[selected])),
        "brier_calibrated": float(
            brier_score_loss(y[selected], calibrated[selected], sample_weight=weight[selected])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--document-groups", required=True)
    parser.add_argument("--base-models", required=True)
    parser.add_argument("--out-model")
    parser.add_argument("--out-models")
    args = parser.parse_args()

    build = Path(args.build).resolve()
    frame = pd.read_parquet(build / "groupjoin_frame.parquet")
    frame = frame[frame["label_known"]].reset_index(drop=True)
    features = pd.read_parquet(build / "groupjoin_features.parquet")
    if len(frame) != len(features):
        raise ValueError("frame and engineered features are not row-aligned")
    for column in ("tuple_id", "decision_id", "candidate_report", "query"):
        if not np.array_equal(frame[column].astype(str).to_numpy(), features[column].astype(str).to_numpy()):
            raise ValueError(f"feature/frame row alignment failed on {column}")

    frame = attach_folds(frame, args.document_groups)
    keep = ~frame["mixed_evidence"].to_numpy(bool)
    frame = frame.loc[keep].reset_index(drop=True)
    features = features.loc[keep].reset_index(drop=True)
    neural_oof = np.load(build / "groupjoin_direct_oof.npz")
    pooled = neural_oof["pooled"].astype(np.float32)
    if pooled.shape != (len(frame), POOL_DIMS):
        raise ValueError(f"binary neural OOF pool shape {pooled.shape} != {(len(frame), POOL_DIMS)}")
    if not np.array_equal(neural_oof["query_fold"], frame["query_fold"].to_numpy(dtype=np.int8)):
        raise ValueError("binary neural OOF folds do not match the clean training frame")

    engineered = features[ENGINEERED_FEATURE_NAMES].to_numpy(dtype=np.float32)
    X = np.concatenate([engineered, pooled], axis=1)
    y = frame["label"].to_numpy(bool)
    weight = frame["sample_weight"].to_numpy(dtype=np.float64)
    query_fold = frame["query_fold"].to_numpy(dtype=np.int8)
    touched_mask = frame["touched_fold_mask"].to_numpy(dtype=np.int16)
    strict_cold = frame["strict_cold"].to_numpy(bool)

    oof_raw = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        train = (touched_mask & (1 << fold)) == 0
        validate = query_fold == fold
        model = HistGradientBoostingClassifier(max_depth=3, random_state=SEED + fold)
        model.fit(X[train], y[train], sample_weight=weight[train])
        oof_raw[validate] = model.predict_proba(X[validate])[:, 1]
        print(f"fold {fold}: train {int(train.sum()):,}, validate {int(validate.sum()):,}", flush=True)
    if np.isnan(oof_raw).any():
        raise ValueError("stack cross-fit left rows without predictions")

    oof_calibrated = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        fit = query_fold != fold
        validate = query_fold == fold
        fold_iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        fold_iso.fit(oof_raw[fit], y[fit], sample_weight=weight[fit])
        oof_calibrated[validate] = fold_iso.predict(oof_raw[validate])

    isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    isotonic.fit(oof_raw, y, sample_weight=weight)
    final = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
    final.fit(X, y, sample_weight=weight)

    all_rows = np.ones(len(frame), dtype=bool)
    contested = frame.groupby("decision_id", sort=False).indices.values()
    contested = [np.asarray(rows, dtype=np.int64) for rows in contested if y[rows].any() and not y[rows].all()]
    metrics = {
        "all": metric_set(y, oof_raw, oof_calibrated, weight, all_rows),
        "strict_cold": metric_set(y, oof_raw, oof_calibrated, weight, strict_cold),
        "contested_top1": float(np.mean([y[rows[np.argmax(oof_raw[rows])]] for rows in contested])),
    }
    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)

    artifact = {
        "model": final,
        "iso": isotonic,
        "tau": 0.5,
        "feature_names": [*ENGINEERED_FEATURE_NAMES, *POOL_FEATURE_NAMES],
        "recipe": "lab2-groupjoin-binary-oof-pool-plus-tree-v1",
        "encoder": "groupjoin_direct.onnx",
        "encoder_manifest": "groupjoin_direct.manifest.json",
        "label_rule": "mixed evidence excluded",
        "oof_strategy": (
            "five clone-linkage folds; tree fit uses pooled representations from fold-excluded encoders; "
            "held fold absent from query and candidate members in each tree fit"
        ),
        "metrics": metrics,
        "n_train": len(frame),
    }
    output = Path(args.out_model).resolve() if args.out_model else build / "groupjoin_stack.pkl"
    with output.open("wb") as file:
        pickle.dump(artifact, file)
    output.with_suffix(".metrics.json").write_text(
        json.dumps(artifact | {"model": None, "iso": None}, indent=2, sort_keys=True)
    )
    np.savez(
        output.with_name(f"{output.stem}_oof.npz"),
        raw=oof_raw,
        calibrated=oof_calibrated,
        query_fold=query_fold,
        strict_cold=strict_cold,
    )

    base_models_path = Path(args.base_models).resolve()
    models = json.loads(base_models_path.read_text())
    models["groupjoin"] = dump_gbdt(artifact)
    models_output = Path(args.out_models).resolve() if args.out_models else build / "models-stack.json"
    models_output.write_text(json.dumps(models))
    print(f"wrote {output}", flush=True)
    print(f"wrote {models_output}", flush=True)


if __name__ == "__main__":
    main()
