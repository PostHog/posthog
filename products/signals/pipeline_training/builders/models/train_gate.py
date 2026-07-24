"""Train the source-pinned concern gate split model.

Frame: harvested MST cut proposals (label_cuts.py: pair-label projection — a cut is GOOD if it
separates judged-different material, BAD if it severs same-concern pairs) featurized
serve-identically by `engine featurize-cuts` (split features + group signature features,
driven by the SERVING pair model). Model: depth-3 HistGradientBoosting + isotonic on OOF.
Folds are grouped by REPORT (all cuts of one report share a fold — cuts of the same report are
correlated evidence). The model predicts COHERENCE (y=1 = sides belong together = do NOT cut) to match serve semantics.

Run from lab/2:
  python models/train_gate.py --features data/frames/cut_feats.jsonl [--run-id X]
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
LABELS = os.path.join(LAB2, "labels", "pair_bank", "cut_labels_v1.parquet")
N_FOLDS = 5
SEED = 7
DEFAULT_REPORT_WEIGHT_CAP = 100.0


def assign_folds(frame: pd.DataFrame) -> dict[str, int]:
    report_stats = frame.groupby("report_id").agg(
        rows=("cut_id", "size"),
        positives=("y", "sum"),
        weight=("weight", "sum"),
    )
    fold_stats = [{"rows": 0.0, "positives": 0.0, "weight": 0.0, "reports": 0.0} for _ in range(N_FOLDS)]
    fold_of: dict[str, int] = {}
    ordered = sorted(
        report_stats.itertuples(),
        key=lambda row: (-float(row.weight), -int(row.rows), hashlib.sha256(str(row.Index).encode()).hexdigest()),
    )
    totals = report_stats[["rows", "positives", "weight"]].sum().replace(0, 1).astype(float)

    def add_report(report: object, fold: int) -> None:
        fold_of[str(report.Index)] = fold
        fold_stats[fold]["rows"] += float(report.rows)
        fold_stats[fold]["positives"] += float(report.positives)
        fold_stats[fold]["weight"] += float(report.weight)
        fold_stats[fold]["reports"] += 1

    for fold, report in enumerate(ordered[:N_FOLDS]):
        add_report(report, fold)

    for report in ordered[N_FOLDS:]:

        def cost(fold: int, current_report: object = report) -> tuple[float, int]:
            projected = [stats.copy() for stats in fold_stats]
            projected[fold]["rows"] += float(current_report.rows)
            projected[fold]["positives"] += float(current_report.positives)
            projected[fold]["weight"] += float(current_report.weight)
            projected[fold]["reports"] += 1
            imbalance = sum(
                (stats[name] / float(totals[name]) - 1 / N_FOLDS) ** 2
                for stats in projected
                for name in ("rows", "positives", "weight")
            )
            return imbalance, fold

        chosen = min(range(N_FOLDS), key=cost)
        add_report(report, chosen)
    return fold_of


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True, help="jsonl from `engine featurize-cuts`")
    ap.add_argument("--labels", default=LABELS)
    ap.add_argument("--out", default=os.path.join(HERE, "concern_l2.pkl"))
    ap.add_argument("--run-id")
    ap.add_argument(
        "--report-weight-cap",
        type=float,
        default=DEFAULT_REPORT_WEIGHT_CAP,
        help="cap each source report's total training weight; 0 disables the cap",
    )
    args = ap.parse_args()

    labels = pd.read_parquet(args.labels)
    feats = pd.read_json(args.features, lines=True)
    duplicate_labels = labels.duplicated(["cut_id"], keep=False)
    duplicate_feats = feats.duplicated(["cut_id"], keep=False)
    if duplicate_labels.any():
        raise ValueError(f"labels contain {int(duplicate_labels.sum())} rows with duplicate cut ids")
    if duplicate_feats.any():
        raise ValueError(f"features contain {int(duplicate_feats.sum())} rows with duplicate cut ids")
    feat_cols = sorted(c for c in feats.columns if c != "cut_id")
    df = labels.merge(feats, on="cut_id", how="inner", validate="one_to_one")
    if len(df) != len(labels):
        raise ValueError(f"features are missing {len(labels) - len(df)} labeled cuts")
    raw_report_weight = df.groupby("report_id")["weight"].sum()
    if args.report_weight_cap > 0:
        report_scale = (args.report_weight_cap / raw_report_weight).clip(upper=1.0)
        df["weight"] *= df["report_id"].map(report_scale)
    effective_report_weight = df.groupby("report_id")["weight"].sum()
    print(
        f"labels {len(labels)} · featurized {len(df)} · {len(feat_cols)} features"
        f" · good {int(df.y.sum())} / bad {int((~df.y).sum())}"
    )
    print(
        f"report-weight cap {args.report_weight_cap:g} · top report share "
        f"{raw_report_weight.max() / raw_report_weight.sum():.4f} -> "
        f"{effective_report_weight.max() / effective_report_weight.sum():.4f}"
    )

    fold_of = assign_folds(df)
    df["fold"] = df["report_id"].astype(str).map(fold_of)
    fold_summary = df.groupby("fold").agg(
        rows=("cut_id", "size"), reports=("report_id", "nunique"), positives=("y", "sum"), weight=("weight", "sum")
    )
    if set(fold_summary.index) != set(range(N_FOLDS)):
        raise ValueError(f"fold allocation did not populate all {N_FOLDS} folds")
    print(f"folds:\n{fold_summary.to_string()}")

    X = df[feat_cols].to_numpy()
    # SERVE SEMANTICS INVERSION: the engine's concern score C is COHERENCE — the gate splits when
    # the worst cut's C <= sigma (classifier.rs eval_group_after_join). Our labels score CUT
    # GOODNESS, so the model must be trained on the negation: y=1 = "sides belong together".
    y = (~df["y"]).to_numpy().astype(int)
    w = df["weight"].to_numpy()

    oof = np.full(len(df), np.nan)
    for f in range(N_FOLDS):
        tr, te = df["fold"] != f, df["fold"] == f
        if not te.any():
            raise ValueError(f"fold {f} has no validation rows")
        m = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
        m.fit(X[tr], y[tr], sample_weight=w[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]

    auc_w = roc_auc_score(y, oof, sample_weight=w)
    auc = roc_auc_score(y, oof)
    print(f"OOF AUC {auc:.4f} (weighted {auc_w:.4f})")

    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(oof, y, sample_weight=w)
    final = HistGradientBoostingClassifier(max_depth=3, random_state=SEED)
    final.fit(X, y, sample_weight=w)

    with open(args.out, "wb") as f:
        pickle.dump(
            {
                "model": final,
                "iso": iso,
                "feature_names": feat_cols,
                "frame": os.path.basename(args.labels),
                "features": os.path.basename(args.features),
                "recipe": "concern-gate-l2",
                "report_weight_cap": args.report_weight_cap,
                "oof_strategy": "deterministic report-disjoint balanced folds",
                "oof_auc_weighted": auc_w,
                "oof_auc_raw": auc,
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
            member="concern",
            params={
                "component": "concern",
                "frame": os.path.basename(args.labels),
                "n_cuts": len(df),
                "features": len(feat_cols),
                "report_weight_cap": args.report_weight_cap,
                "recipe": "HistGBM d3 + isotonic OOF, report-grouped folds with capped report weight",
            },
        )
        db.metric(
            args.run_id, "auc_oof", round(auc_w, 4), stage="train", member="concern", shard="train", layer="train"
        )
        db.metric(
            args.run_id, "n_train_cuts", float(len(df)), stage="train", member="concern", shard="train", layer="train"
        )
        db.finish_activity(act)


if __name__ == "__main__":
    main()
