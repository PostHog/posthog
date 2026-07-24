"""Export repaired member selectors and their sklearn prerequisites for Rust replay."""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import hashlib
import argparse
from pathlib import Path
from typing import Any

import onnx
import numpy as np
import torch
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from torch import nn
from train_bipartite_member_selector import BipartiteMemberSelector, EDGE_FEATURES
from train_contextual_member_selector import MemberSetSelector

MAX_REPORT_MEMBERS = 300
MAX_COMBINED_MEMBERS = 450
NODE_FEATURES = 51
EDGE_FEATURE_COUNT = len(EDGE_FEATURES)
CONTEXTUAL_BUCKETS = (16, 64, 128, 256, MAX_COMBINED_MEMBERS)
BIPARTITE_BUCKETS = (8, 32, 64, 128, MAX_REPORT_MEMBERS)


class ServingContextualSelector(nn.Module):
    def __init__(self, model: MemberSetSelector, mean: np.ndarray, std: np.ndarray) -> None:
        super().__init__()
        self.model = model
        self.register_buffer("mean", torch.from_numpy(mean.astype(np.float32)))
        self.register_buffer("std", torch.from_numpy(std.astype(np.float32)))

    def forward(self, features: torch.Tensor, sides: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        return self.model((features - self.mean) / self.std, sides, mask)


class ServingBipartiteSelector(nn.Module):
    def __init__(
        self,
        model: BipartiteMemberSelector,
        node_mean: np.ndarray,
        node_std: np.ndarray,
        edge_mean: np.ndarray,
        edge_std: np.ndarray,
    ) -> None:
        super().__init__()
        self.model = model
        self.register_buffer("node_mean", torch.from_numpy(node_mean.astype(np.float32)))
        self.register_buffer("node_std", torch.from_numpy(node_std.astype(np.float32)))
        self.register_buffer("edge_mean", torch.from_numpy(edge_mean.astype(np.float32)))
        self.register_buffer("edge_std", torch.from_numpy(edge_std.astype(np.float32)))

    def forward(
        self,
        left_features: torch.Tensor,
        right_features: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        normalized_edges = torch.where(
            edge_mask.unsqueeze(-1),
            (edge_features - self.edge_mean) / self.edge_std,
            torch.zeros_like(edge_features),
        )
        return self.model(
            (left_features - self.node_mean) / self.node_std,
            (right_features - self.node_mean) / self.node_std,
            normalized_edges,
            edge_mask,
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_hgb(model: HistGradientBoostingClassifier, feature_names: list[str]) -> dict[str, Any]:
    trees = []
    for iteration in model._predictors:
        if len(iteration) != 1:
            raise ValueError("binary HistGradientBoostingClassifier expected")
        trees.append(
            [
                {
                    "value": float(node["value"]),
                    "feature_idx": int(node["feature_idx"]),
                    "num_threshold": float(node["num_threshold"]),
                    "missing_go_to_left": bool(node["missing_go_to_left"]),
                    "left": int(node["left"]),
                    "right": int(node["right"]),
                    "is_leaf": bool(node["is_leaf"]),
                }
                for node in iteration[0].nodes
            ]
        )
    return {
        "kind": "gbdt",
        "baseline": float(np.ravel(model._baseline_prediction)[0]),
        "trees": trees,
        "feature_names": feature_names,
    }


def dump_pipeline(model: Pipeline, feature_names: list[str]) -> dict[str, Any]:
    scaler = model.named_steps["standardscaler"]
    logistic = model.named_steps["logisticregression"]
    coefficients = np.asarray(logistic.coef_[0], dtype=np.float64)
    scale = np.asarray(scaler.scale_, dtype=np.float64)
    mean = np.asarray(scaler.mean_, dtype=np.float64)
    weights = coefficients / scale
    bias = float(logistic.intercept_[0] - np.sum(coefficients * mean / scale))
    return {
        "kind": "linear",
        "feature_names": feature_names,
        "weights": weights.tolist(),
        "bias": bias,
    }


def dump_models(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("rb") as source:
        artifact = pickle.load(source)  # noqa: S301 - local research artifact
    output: dict[str, dict[str, Any]] = {}
    for name, model in artifact["models"].items():
        feature_names = (
            list(artifact["features"][name])
            if isinstance(artifact["features"], dict)
            else list(artifact["features"])
        )
        if isinstance(model, HistGradientBoostingClassifier):
            output[name] = dump_hgb(model, feature_names)
        elif isinstance(model, Pipeline):
            output[name] = dump_pipeline(model, feature_names)
        else:
            raise TypeError(f"unsupported portable classifier {name}: {type(model).__name__}")
    return output


def artifact_record(path: Path) -> dict[str, Any]:
    return {"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def export_contextual(state_path: Path, output_dir: Path) -> tuple[list[str], list[dict[str, Any]]]:
    state = torch.load(state_path, map_location="cpu", weights_only=False)
    feature_columns = list(state["feature_columns"])
    if len(feature_columns) != NODE_FEATURES:
        raise ValueError(f"contextual node feature width changed: {len(feature_columns)}")
    model = MemberSetSelector(len(feature_columns))
    model.load_state_dict(state["state_dict"], strict=True)
    serving = ServingContextualSelector(model.eval(), state["mean"], state["std"]).eval()
    buckets: list[dict[str, Any]] = []
    for width in CONTEXTUAL_BUCKETS:
        output = output_dir / f"contextual_member_repair_{width}.onnx"
        torch.onnx.export(
            serving,
            (
                torch.zeros(1, width, NODE_FEATURES, dtype=torch.float32),
                torch.zeros(1, width, dtype=torch.int64),
                torch.ones(1, width, dtype=torch.bool),
            ),
            output,
            input_names=["features", "sides", "mask"],
            output_names=["member_logits"],
            dynamic_axes={
                "features": {0: "report_pairs"},
                "sides": {0: "report_pairs"},
                "mask": {0: "report_pairs"},
                "member_logits": {0: "report_pairs"},
            },
            opset_version=18,
            dynamo=False,
        )
        graph = onnx.load(output)
        onnx.checker.check_model(graph, full_check=True)
        buckets.append({"width": width, "artifact": artifact_record(output)})
    return feature_columns, buckets


def export_bipartite(state_path: Path, output_dir: Path) -> tuple[list[str], list[dict[str, Any]]]:
    state = torch.load(state_path, map_location="cpu", weights_only=False)
    node_columns = list(state["node_columns"])
    if len(node_columns) != NODE_FEATURES:
        raise ValueError(f"bipartite node feature width changed: {len(node_columns)}")
    model = BipartiteMemberSelector(len(node_columns), EDGE_FEATURE_COUNT)
    model.load_state_dict(state["state_dict"], strict=True)
    serving = ServingBipartiteSelector(
        model.eval(),
        state["node_mean"],
        state["node_std"],
        state["edge_mean"],
        state["edge_std"],
    ).eval()
    buckets: list[dict[str, Any]] = []
    for width in BIPARTITE_BUCKETS:
        output = output_dir / f"bipartite_member_repair_{width}.onnx"
        torch.onnx.export(
            serving,
            (
                torch.zeros(1, width, NODE_FEATURES, dtype=torch.float32),
                torch.zeros(1, width, NODE_FEATURES, dtype=torch.float32),
                torch.zeros(1, width, width, EDGE_FEATURE_COUNT, dtype=torch.float32),
                torch.ones(1, width, width, dtype=torch.bool),
            ),
            output,
            input_names=["left_features", "right_features", "edge_features", "edge_mask"],
            output_names=["left_logits", "right_logits"],
            dynamic_axes={
                "left_features": {0: "report_pairs"},
                "right_features": {0: "report_pairs"},
                "edge_features": {0: "report_pairs"},
                "edge_mask": {0: "report_pairs"},
                "left_logits": {0: "report_pairs"},
                "right_logits": {0: "report_pairs"},
            },
            opset_version=18,
            dynamo=False,
        )
        graph = onnx.load(output)
        onnx.checker.check_model(graph, full_check=True)
        buckets.append({"width": width, "artifact": artifact_record(output)})
    return node_columns, buckets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="repaired member-alignment artifact root")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    contextual_features, contextual_buckets = export_contextual(
        root / "train_contextual_primary_gate_repaired/contextual_member_selector.pt",
        output,
    )
    bipartite_features, bipartite_buckets = export_bipartite(
        root / "train_bipartite_consensus_gate_repaired/bipartite_member_selector.pt",
        output,
    )
    if contextual_features != bipartite_features:
        raise ValueError("contextual and bipartite node feature contracts differ")

    manifest = {
        "schema_version": 1,
        "model_family": "member_aware_report_pair_repair",
        "feature_contract": "lab2-exact-member-v3-live-replay-v2-bucketed-members",
        "caps": {
            "top_k_each_direction": 24,
            "max_report_members": MAX_REPORT_MEMBERS,
            "max_combined_members": MAX_COMBINED_MEMBERS,
        },
        "node_feature_names": contextual_features,
        "edge_feature_names": list(EDGE_FEATURES),
        "compatibility_primary": dump_models(root / "train_primary/member_compatibility_models.pkl"),
        "compatibility_consensus": dump_models(root / "train_consensus/member_compatibility_models.pkl"),
        "report_gate": dump_models(root / "train_report_gate_repaired/report_gate_models.pkl"),
        "operation_risk_contextual": dump_models(
            root / "train_operation_risk_contextual/operation_risk_models.pkl"
        ),
        "operation_risk_bipartite": dump_models(
            root / "train_operation_risk_bipartite/operation_risk_models.pkl"
        ),
        "contextual": {
            "buckets": contextual_buckets,
            "input_shapes": {
                "features": ["report_pairs", "bucketed_members", NODE_FEATURES],
                "sides": ["report_pairs", "bucketed_members"],
                "mask": ["report_pairs", "bucketed_members"],
            },
            "output_shape": ["report_pairs", "bucketed_members"],
            "member_order": "left arrival order, then right arrival order",
        },
        "bipartite": {
            "buckets": bipartite_buckets,
            "input_shapes": {
                "left_features": ["report_pairs", "bucketed_members", NODE_FEATURES],
                "right_features": ["report_pairs", "bucketed_members", NODE_FEATURES],
                "edge_features": [
                    "report_pairs",
                    "bucketed_members",
                    "bucketed_members",
                    EDGE_FEATURE_COUNT,
                ],
                "edge_mask": ["report_pairs", "bucketed_members", "bucketed_members"],
            },
            "output_shapes": {
                "left_logits": ["report_pairs", "bucketed_members"],
                "right_logits": ["report_pairs", "bucketed_members"],
            },
        },
        "status": "portable prerequisites, neural selectors, and operation-risk models exported",
    }
    manifest_path = output / "member_repair.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(contextual_buckets)} contextual ONNX buckets")
    print(f"wrote {len(bipartite_buckets)} bipartite ONNX buckets")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
