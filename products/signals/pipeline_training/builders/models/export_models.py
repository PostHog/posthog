"""Export source-pinned sklearn artifacts to the engine's models.json and parity fixtures.

The JSON transform is carried verbatim from the old replayer's export (parity-tested):
HistGradientBoosting per-tree node arrays + isotonic knots; raw = sigmoid(baseline + leaf sums).

The burst index is DATA, not a model: per (product, type), the sorted epoch array of arrivals
in a corpus — the serving featurizer counts neighbors within ±1h. It ships inside models.json
(old contract) and must be built from the TRAIN corpus for training-frame featurization
(shard firewall: tune/test arrivals never inform train features).

Run from lab/2:
  python models/export_models.py --pair models/pair_v19l2.pkl --burst-corpus data/corpora/train \
      --out models/models_v19l2.json [--fixtures-frame <features jsonl> --fixtures-out <path>]
"""

# ruff: noqa: T201

import os
import json
import pickle
import argparse

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def dump_gbdt(artifact: dict, extra_keys: tuple[str, ...] = ("tau",)) -> dict:
    model, iso = artifact["model"], artifact["iso"]
    trees = []
    for iteration in model._predictors:
        assert len(iteration) == 1, "binary classifier expected"
        trees.append(
            [
                {
                    "value": float(n["value"]),
                    "feature_idx": int(n["feature_idx"]),
                    "num_threshold": float(n["num_threshold"]),
                    "missing_go_to_left": bool(n["missing_go_to_left"]),
                    "left": int(n["left"]),
                    "right": int(n["right"]),
                    "is_leaf": bool(n["is_leaf"]),
                }
                for n in iteration[0].nodes
            ]
        )
    out = {
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": trees,
        "iso_x": [float(v) for v in artifact["iso"].X_thresholds_],
        "iso_y": [float(v) for v in artifact["iso"].y_thresholds_],
        "feature_names": list(artifact["feature_names"]),
    }
    for k in extra_keys:
        if k in artifact:
            out[k] = float(artifact[k])
    return out


def build_burst(corpus_dir: str) -> dict[str, list[float]]:
    burst: dict[str, list[float]] = {}
    with open(os.path.join(corpus_dir, "signals.jsonl")) as f:
        for line in f:
            o = json.loads(line)
            burst.setdefault(f"{o['product']}\x00{o['type']}", []).append(float(o["ts"]))
    return {k: sorted(v) for k, v in burst.items()}


def fixtures_for(artifact: dict, features_jsonl: str, n: int = 300) -> list[dict]:
    frame = pd.read_json(features_jsonl, lines=True).sample(n, random_state=7)
    X = frame[list(artifact["feature_names"])]
    raw = artifact["model"].predict_proba(X)[:, 1]
    cal = artifact["iso"].predict(raw)
    return [
        {"x": [float(v) for v in row], "raw": float(r), "cal": float(c)} for row, r, c in zip(X.to_numpy(), raw, cal)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True)
    ap.add_argument("--join")
    ap.add_argument("--groupjoin")
    ap.add_argument("--concern")
    ap.add_argument("--burst-corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fixtures-frame", help="features jsonl to draw parity fixtures from")
    ap.add_argument("--fixtures-out")
    args = ap.parse_args()

    with open(args.pair, "rb") as f:
        pair = pickle.load(f)
    models: dict = {"pair": dump_gbdt(pair), "burst": build_burst(args.burst_corpus)}
    for key, path in (("join", args.join), ("groupjoin", args.groupjoin)):
        if path:
            with open(path, "rb") as f:
                models[key] = dump_gbdt(pickle.load(f))
    if args.concern:
        with open(args.concern, "rb") as f:
            models["concern"] = dump_gbdt(pickle.load(f), ("gamma", "sigma"))
        models["concern"]["thresholds_on_raw"] = True  # lab-1 v2-gate convention
    with open(args.out, "w") as f:
        json.dump(models, f)
    print(
        f"{args.out}: pair {len(models['pair']['trees'])} trees, "
        f"{len(models['pair']['feature_names'])} features, burst {len(models['burst'])} types"
        + "".join(f", {k} {len(models[k]['trees'])} trees" for k in ("join", "groupjoin", "concern") if k in models)
    )

    if args.fixtures_frame and args.fixtures_out:
        fixtures = {"pair": fixtures_for(pair, args.fixtures_frame)}
        with open(args.fixtures_out, "w") as f:
            json.dump(fixtures, f)
        print(f"fixtures: {args.fixtures_out} ({len(fixtures['pair'])} rows)")


if __name__ == "__main__":
    main()
