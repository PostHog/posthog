"""Train the source-pinned report-level GroupJoin tree baseline.

Cross-fit models hold out one clone-linkage fold at a time. A training tuple is
removed whenever either its query or any candidate-report member belongs to the
held-out fold. Every OOF prediction therefore has a cold query; the subset whose
members are also in the query fold is fully document-disjoint on both sides.

Run from lab/2:
    python models/train_groupjoin.py --build data/groupjoin/<build-id> --run-id <run-id>
"""

# ruff: noqa: T201

from __future__ import annotations

import sys
import json
import pickle
import hashlib
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

HERE = Path(__file__).resolve().parent
BUILDER_ROOT = HERE.parent
sys.path.insert(0, str(BUILDER_ROOT))
from models.groupjoin_features import ENGINEERED_FEATURE_NAMES  # noqa: E402

N_FOLDS = 5
SEED = 17


def stable_fold(group_id: object) -> int:
    digest = hashlib.sha256(f"groupjoin:{group_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % N_FOLDS


def document_groups(path: str | Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not value:
        raise ValueError("--document-groups must contain a non-empty document-to-linkage-group object")
    groups: dict[str, object] = {}
    for document_id, group_id in value.items():
        if not isinstance(document_id, str) or not document_id or not isinstance(group_id, str) or not group_id:
            raise ValueError("--document-groups contains an invalid document or group ID")
        groups[document_id] = group_id
    return groups


def attach_folds(frame: pd.DataFrame, document_groups_path: str | Path) -> pd.DataFrame:
    group_of = document_groups(document_groups_path)
    query_folds: list[int] = []
    touched_fold_masks: list[int] = []
    touched_group_counts: list[int] = []
    for row in frame.itertuples(index=False):
        query = str(row.query)
        members = [str(member) for member in json.loads(row.members)]
        try:
            query_group = group_of[query]
            groups = {query_group, *(group_of[member] for member in members)}
        except KeyError as error:
            raise ValueError(f"tuple references a document outside the train shard: {error.args[0]}") from error
        folds = {stable_fold(group) for group in groups}
        query_folds.append(stable_fold(query_group))
        touched_fold_masks.append(sum(1 << fold for fold in folds))
        touched_group_counts.append(len(groups))
    result = frame.copy()
    result["query_fold"] = query_folds
    result["touched_fold_mask"] = touched_fold_masks
    result["touched_group_count"] = touched_group_counts
    result["strict_cold"] = [mask == 1 << fold for mask, fold in zip(touched_fold_masks, query_folds)]
    return result


def metric_set(y: np.ndarray, raw: np.ndarray, calibrated: np.ndarray, weight: np.ndarray) -> dict[str, float]:
    if len(np.unique(y)) < 2:
        return {"rows": float(len(y))}
    return {
        "rows": float(len(y)),
        "positive_rate": float(np.average(y, weights=weight)),
        "auc_raw": float(roc_auc_score(y, raw, sample_weight=weight)),
        "ap_raw": float(average_precision_score(y, raw, sample_weight=weight)),
        "brier_calibrated": float(brier_score_loss(y, calibrated, sample_weight=weight)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--document-groups", required=True)
    parser.add_argument("--out")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--exclude-mixed",
        action="store_true",
        help="sensitivity artifact: remove tuples carrying both positive and negative evidence",
    )
    args = parser.parse_args()

    build = Path(args.build).resolve()
    frame = pd.read_parquet(build / "groupjoin_frame.parquet")
    frame = frame[frame["label_known"]].reset_index(drop=True)
    features = pd.read_parquet(build / "groupjoin_features.parquet")
    if len(features) != len(frame):
        raise ValueError(f"feature rows {len(features)} != labeled frame rows {len(frame)}")
    for column in ("tuple_id", "decision_id", "candidate_report", "query"):
        if not np.array_equal(features[column].astype(str).to_numpy(), frame[column].astype(str).to_numpy()):
            raise ValueError(f"feature/frame row alignment failed on {column}")

    frame = attach_folds(frame, args.document_groups)
    if args.exclude_mixed:
        keep = ~frame["mixed_evidence"].to_numpy(bool)
        frame = frame.loc[keep].reset_index(drop=True)
        features = features.loc[keep].reset_index(drop=True)

    X = features[ENGINEERED_FEATURE_NAMES].to_numpy(dtype=np.float32)
    y = frame["label"].to_numpy(bool)
    weight = frame["sample_weight"].to_numpy(dtype=np.float64)
    query_fold = frame["query_fold"].to_numpy(dtype=np.int8)
    touched_mask = frame["touched_fold_mask"].to_numpy(dtype=np.int16)
    if len(np.unique(y)) < 2:
        raise ValueError("groupjoin training frame needs both positive and negative labels")

    oof_raw = np.full(len(frame), np.nan, dtype=np.float64)
    fold_summary: dict[str, dict[str, int]] = {}
    for fold in range(N_FOLDS):
        train = (touched_mask & (1 << fold)) == 0
        validate = query_fold == fold
        if len(np.unique(y[train])) < 2:
            raise ValueError(f"fold {fold} training partition has only one class")
        model = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
        model.fit(X[train], y[train], sample_weight=weight[train])
        oof_raw[validate] = model.predict_proba(X[validate])[:, 1]
        fold_summary[str(fold)] = {
            "train": int(train.sum()),
            "validate": int(validate.sum()),
            "strict_cold": int((validate & frame["strict_cold"].to_numpy(bool)).sum()),
        }
        print(
            f"fold {fold}: train {int(train.sum()):,}, validate {int(validate.sum()):,}, "
            f"strict-cold {fold_summary[str(fold)]['strict_cold']:,}",
            flush=True,
        )
    if np.isnan(oof_raw).any():
        raise ValueError(f"cross-fit left {int(np.isnan(oof_raw).sum())} tuples without predictions")

    # Calibrator quality is measured by a second fold-wise cross-fit. The deploy
    # calibrator below is then fit once on all raw OOF predictions.
    oof_calibrated = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        calibration_train = query_fold != fold
        validate = query_fold == fold
        isotonic_fold = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        isotonic_fold.fit(oof_raw[calibration_train], y[calibration_train], sample_weight=weight[calibration_train])
        oof_calibrated[validate] = isotonic_fold.predict(oof_raw[validate])

    isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    isotonic.fit(oof_raw, y, sample_weight=weight)
    final = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
    final.fit(X, y, sample_weight=weight)

    strict_cold = frame["strict_cold"].to_numpy(bool)
    clean_evidence = ~frame["mixed_evidence"].to_numpy(bool)
    metrics = {
        "all": metric_set(y, oof_raw, oof_calibrated, weight),
        "strict_cold": metric_set(
            y[strict_cold], oof_raw[strict_cold], oof_calibrated[strict_cold], weight[strict_cold]
        ),
        "clean_evidence": metric_set(
            y[clean_evidence], oof_raw[clean_evidence], oof_calibrated[clean_evidence], weight[clean_evidence]
        ),
    }
    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)

    suffix = "-nomixed" if args.exclude_mixed else ""
    output = Path(args.out).resolve() if args.out else build / f"groupjoin_tree{suffix}.pkl"
    artifact = {
        "model": final,
        "iso": isotonic,
        "tau": 0.5,
        "feature_names": ENGINEERED_FEATURE_NAMES,
        "frame": "groupjoin_frame.parquet",
        "features": "groupjoin_features.parquet",
        "recipe": "source-pinned-groupjoin-tree-v1",
        "label_rule": "negative evidence wins" + ("; mixed evidence excluded" if args.exclude_mixed else ""),
        "oof_strategy": (
            "five clone-linkage folds; held fold absent from query and candidate members in fit; "
            "strict_cold slice has query and all members in held fold"
        ),
        "fold_summary": fold_summary,
        "metrics": metrics,
        "n_train": len(frame),
    }
    with output.open("wb") as file:
        pickle.dump(artifact, file)
    (output.with_suffix(".metrics.json")).write_text(json.dumps(artifact | {"model": None, "iso": None}, indent=2))
    np.savez(
        output.with_name(f"{output.stem}_oof.npz"),
        raw=oof_raw,
        calibrated=oof_calibrated,
        query_fold=query_fold,
        strict_cold=strict_cold,
        clean_evidence=clean_evidence,
    )
    print(f"wrote {output}", flush=True)

    if args.run_id:
        sys.path.insert(0, str(BUILDER_ROOT / "perf"))
        from perfdb import PerfDB  # noqa: PLC0415

        member = "groupjoin-tree-nomixed" if args.exclude_mixed else "groupjoin-tree"
        db = PerfDB()
        activity = db.start_activity(
            args.run_id,
            stage="train",
            kind="fit",
            member=member,
            params={
                "component": member,
                "n_rows": len(frame),
                "features": len(ENGINEERED_FEATURE_NAMES),
                "cross_fit": artifact["oof_strategy"],
            },
        )
        for slice_name, values in metrics.items():
            for metric_name, value in values.items():
                db.metric(
                    args.run_id,
                    f"groupjoin_{metric_name}",
                    value,
                    stage="train",
                    member=member,
                    slice=slice_name,
                    shard="train",
                    layer="train",
                )
        db.finish_activity(activity)


if __name__ == "__main__":
    main()
