"""Retrain the lab-1 pairwise frontier (v19 recipe) on the new train shard.

Identical featureset and recipe to lab 1: the 32 engineered pair features (computed by the
engine's featurizer — the serving featurizer, so train/serve identity holds by construction),
depth-3 HistGradientBoosting, isotonic calibration on out-of-fold predictions, CV folds
assigned by CONNECTED COMPONENT (documents linked by a positive pair share a fold — no
near-twin leakage across folds; lab-1 whitepaper §5). New everything else: train-shard frame
(labels/pair_bank/train_frame_v1.parquet), sample weights from the label-confidence column.

Inputs:  train_frame_v1.parquet + features jsonl from `engine featurize`
Outputs: models/pair_v19l2.pkl (sklearn artifacts) + models.json via export for the engine,
         train metrics (auc_oof weighted/raw) printed and written to the perf DB if --run-id.

Run from lab/2:
  python models/train_pair.py --features data/frames/train_frame_v1_feats.jsonl [--run-id X]
"""

# ruff: noqa: T201

import os
import sys
import pickle
import hashlib
import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
LAB2 = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_FRAME = os.path.join(LAB2, "labels", "pair_bank", "train_frame_v1.parquet")
N_FOLDS = 5
SEED = 7


def components(pairs: pd.DataFrame) -> dict[str, str]:
    """Union positive components; isolated documents remain their own components."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in pairs.itertuples():
        find(r.doc_a)
        find(r.doc_b)
        if r.y:
            union(r.doc_a, r.doc_b)
    return {d: find(d) for d in parent}


def stable_fold(component_id: str) -> int:
    digest = hashlib.sha256(component_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % N_FOLDS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True, help="jsonl from `engine featurize`")
    ap.add_argument("--frame", default=DEFAULT_FRAME)
    ap.add_argument("--out", default=os.path.join(HERE, "pair_v19l2.pkl"))
    ap.add_argument("--run-id", help="write train metrics to this perf-DB run")
    args = ap.parse_args()

    frame = pd.read_parquet(args.frame)
    feats = pd.read_json(args.features, lines=True)
    pair_keys = ["doc_a", "doc_b"]
    duplicate_frame = frame.duplicated(pair_keys, keep=False)
    duplicate_feats = feats.duplicated(pair_keys, keep=False)
    if duplicate_frame.any():
        raise ValueError(f"frame contains {int(duplicate_frame.sum())} rows with duplicate pair keys")
    if duplicate_feats.any():
        duplicate_keys = int(feats.loc[duplicate_feats, pair_keys].drop_duplicates().shape[0])
        raise ValueError(
            f"features contain {int(duplicate_feats.sum())} rows across {duplicate_keys} duplicate pair keys; "
            "regenerate the feature artifact before training"
        )
    # lab-1 v1.6 feature set: the featurizer also emits 10 text-stat features (v1.7), which
    # lab-1 REJECTED (regressed the corpus-3 frontier). Identical featureset = exclude them.
    TEXTSTATS = {
        "firstline_jac",
        "gram3_jac",
        "has_stack_min",
        "len_ratio",
        "log_len_absdiff",
        "neg_density_min",
        "neg_density_ratio",
        "punct_frac_ratio",
        "ttr_ratio",
        "upper_frac_ratio",
    }
    feat_cols = [
        c
        for c in feats.columns
        if c not in ("doc_a", "doc_b", "pair_score", "pair_raw", "pair_cal") and c not in TEXTSTATS
    ]
    df = frame.merge(feats, on=pair_keys, how="inner", validate="one_to_one")
    if len(df) != len(frame):
        missing = len(frame) - len(df)
        raise ValueError(f"features are missing {missing} frame pairs")
    print(f"frame {len(frame)} pairs · featurized {len(df)} · {len(feat_cols)} features")

    comp = components(df)
    df["fold_a"] = [stable_fold(comp[a]) for a in df["doc_a"]]
    df["fold_b"] = [stable_fold(comp[b]) for b in df["doc_b"]]
    df["fold_lo"] = np.minimum(df["fold_a"], df["fold_b"])
    df["fold_hi"] = np.maximum(df["fold_a"], df["fold_b"])
    fold_summary = (
        pd.DataFrame(
            {
                "documents": pd.Series(comp)
                .index.to_series()
                .groupby(lambda document: stable_fold(comp[document]))
                .size(),
                "pair_endpoints": pd.concat([df["fold_a"], df["fold_b"]]).value_counts().sort_index(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    print(f"document folds:\n{fold_summary.to_string()}")

    X = df[feat_cols].to_numpy()
    y = df["y"].to_numpy().astype(int)
    w = df["weight"].to_numpy()

    # Cross-fit every pair while keeping both endpoint documents out of fit. Same-fold pairs
    # hold out one fold; cross-fold negatives hold out both folds. The previous implementation
    # calibrated on same-fold pairs only, which discarded two thirds of the frame and distorted
    # isotonic calibration toward positive components.
    oof = np.full(len(df), np.nan)
    fold_pairs = sorted(set(zip(df["fold_lo"], df["fold_hi"])))
    for fold_lo, fold_hi in fold_pairs:
        held_out = {fold_lo, fold_hi}
        tr = ~df["fold_a"].isin(held_out) & ~df["fold_b"].isin(held_out)
        te = (df["fold_lo"] == fold_lo) & (df["fold_hi"] == fold_hi)
        m = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
        m.fit(X[tr], y[tr], sample_weight=w[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]

    oof_mask = ~np.isnan(oof)
    if not oof_mask.all():
        raise ValueError(f"cross-fit left {int((~oof_mask).sum())} pairs without predictions")
    auc_w = roc_auc_score(y[oof_mask], oof[oof_mask], sample_weight=w[oof_mask])
    auc = roc_auc_score(y[oof_mask], oof[oof_mask])
    print(f"OOF AUC {auc:.4f} (weighted {auc_w:.4f}, n={int(oof_mask.sum())})")
    source_auc: dict[str, float] = {}
    for source, indices in df.groupby("source").groups.items():
        source_y = y[indices]
        if len(np.unique(source_y)) < 2:
            continue
        source_auc[str(source)] = roc_auc_score(source_y, oof[indices], sample_weight=w[indices])
    if source_auc:
        print("OOF AUC by mixed-label source: " + ", ".join(f"{k}={v:.4f}" for k, v in source_auc.items()))

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
        oof[oof_mask], y[oof_mask], sample_weight=w[oof_mask]
    )
    final = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
    final.fit(X, y, sample_weight=w)

    with open(args.out, "wb") as f:
        pickle.dump(
            {
                "model": final,
                "iso": iso,
                "feature_names": feat_cols,
                "frame": os.path.basename(args.frame),
                "features": os.path.basename(args.features),
                "recipe": "v19-l2",
                "oof_strategy": "document-disjoint fold-pair cross-fit",
                "oof_auc_weighted": auc_w,
                "oof_auc_raw": auc,
                "oof_auc_by_source": source_auc,
            },
            f,
        )
    print(f"wrote {args.out}")

    if args.run_id:
        sys.path.insert(0, os.path.join(LAB2, "perf"))
        from perfdb import PerfDB  # noqa: PLC0415

        db = PerfDB()
        act = db.start_activity(
            args.run_id,
            stage="train",
            kind="fit",
            member="pair",
            params={
                "component": "pair",
                "frame": os.path.basename(args.frame),
                "n_pairs": len(df),
                "features": len(feat_cols),
                "recipe": "HistGBM d3 + isotonic OOF, document-disjoint fold-pair cross-fit",
            },
        )
        db.metric(args.run_id, "auc_oof", round(auc_w, 4), stage="train", member="pair", shard="train", layer="train")
        db.metric(args.run_id, "auc_oof_raw", round(auc, 4), stage="train", member="pair", shard="train", layer="train")
        db.metric(
            args.run_id, "n_train_pairs", float(len(df)), stage="train", member="pair", shard="train", layer="train"
        )
        for source, source_value in source_auc.items():
            db.metric(
                args.run_id,
                "auc_oof",
                round(source_value, 4),
                stage="train",
                member="pair",
                slice=f"source={source}",
                shard="train",
                layer="train",
            )
        db.finish_activity(act)


if __name__ == "__main__":
    main()
