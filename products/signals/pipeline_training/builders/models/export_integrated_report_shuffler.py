"""Export the integrated report shuffler for Rust replay."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
from pathlib import Path

import onnx
import numpy as np
import torch
from export_member_repair_pipeline import (
    EDGE_FEATURE_COUNT,
    artifact_record,
    dump_models,
)
from train_bipartite_member_selector import EDGE_FEATURES
from train_full_embedding_member_selector import EMBEDDING_DIMS
from train_integrated_report_shuffler import IntegratedReportShuffler


class ServingIntegratedReportShuffler(torch.nn.Module):
    def __init__(
        self,
        model: IntegratedReportShuffler,
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
        left_embeddings: torch.Tensor,
        right_embeddings: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
        member_threshold: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        normalized_edges = torch.where(
            edge_mask.unsqueeze(-1),
            (edge_features - self.edge_mean) / self.edge_std,
            torch.zeros_like(edge_features),
        )
        return self.model(
            (left_features - self.node_mean) / self.node_std,
            (right_features - self.node_mean) / self.node_std,
            left_embeddings,
            right_embeddings,
            normalized_edges,
            edge_mask,
            member_threshold,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    root = Path(args.base_root).resolve()
    state_path = Path(args.state).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = torch.load(state_path, map_location="cpu", weights_only=False)
    if state.get("schema_version") != 1 or state.get("model_family") != "integrated_bipartite_report_shuffler":
        raise ValueError("unsupported integrated report-shuffler state")
    interaction = str(state["interaction"])
    node_columns = list(state["node_columns"])
    model = IntegratedReportShuffler(len(node_columns), EDGE_FEATURE_COUNT, interaction)
    model.load_state_dict(state["state_dict"], strict=True)
    serving = ServingIntegratedReportShuffler(
        model.eval(),
        state["node_mean"],
        state["node_std"],
        state["edge_mean"],
        state["edge_std"],
    ).eval()

    artifact = output / f"integrated_{interaction}_report_shuffler.onnx"
    left_members = 7
    right_members = 11
    torch.onnx.export(
        serving,
        (
            torch.zeros(1, left_members, len(node_columns), dtype=torch.float32),
            torch.zeros(1, right_members, len(node_columns), dtype=torch.float32),
            torch.zeros(1, left_members, EMBEDDING_DIMS, dtype=torch.float32),
            torch.zeros(1, right_members, EMBEDDING_DIMS, dtype=torch.float32),
            torch.zeros(1, left_members, right_members, EDGE_FEATURE_COUNT, dtype=torch.float32),
            torch.ones(1, left_members, right_members, dtype=torch.bool),
            torch.full((1, 1), 0.5, dtype=torch.float32),
        ),
        artifact,
        input_names=[
            "left_features",
            "right_features",
            "left_embeddings",
            "right_embeddings",
            "edge_features",
            "edge_mask",
            "member_threshold",
        ],
        output_names=["left_logits", "right_logits", "action_logit", "safety_logit"],
        dynamic_axes={
            "left_features": {0: "report_pairs", 1: "left_members"},
            "right_features": {0: "report_pairs", 1: "right_members"},
            "left_embeddings": {0: "report_pairs", 1: "left_members"},
            "right_embeddings": {0: "report_pairs", 1: "right_members"},
            "edge_features": {0: "report_pairs", 1: "left_members", 2: "right_members"},
            "edge_mask": {0: "report_pairs", 1: "left_members", 2: "right_members"},
            "member_threshold": {0: "report_pairs"},
            "left_logits": {0: "report_pairs", 1: "left_members"},
            "right_logits": {0: "report_pairs", 1: "right_members"},
            "action_logit": {0: "report_pairs"},
            "safety_logit": {0: "report_pairs"},
        },
        opset_version=18,
        dynamo=False,
    )
    onnx.checker.check_model(onnx.load(artifact), full_check=True)

    manifest = {
        "schema_version": 3,
        "model_family": "integrated_bipartite_report_shuffler",
        "feature_contract": "lab2-exact-member-v3-integrated-shuffler-v1",
        "serving_contract": "dynamic-member-axes-v1",
        "interaction": interaction,
        "feature_independence": {
            "external_report_gate_in_neural_input": False,
            "external_operation_risk_in_neural_input": False,
        },
        "caps": {
            "top_k_each_direction": 24,
            "embedding_dims": EMBEDDING_DIMS,
        },
        "node_feature_names": node_columns,
        "edge_feature_names": list(EDGE_FEATURES),
        "compatibility_primary": dump_models(root / "train_primary/member_compatibility_models.pkl"),
        "compatibility_consensus": dump_models(root / "train_consensus/member_compatibility_models.pkl"),
        "report_gate": dump_models(root / "train_report_gate_repaired/report_gate_models.pkl"),
        "operation_risk_contextual": dump_models(root / "train_operation_risk_contextual/operation_risk_models.pkl"),
        "operation_risk_bipartite": dump_models(root / "train_operation_risk_bipartite/operation_risk_models.pkl"),
        "bipartite": {
            "variant": "integrated",
            "interaction": interaction,
            "artifact": artifact_record(artifact),
            "input_shapes": {
                "left_features": ["report_pairs", "left_members", len(node_columns)],
                "right_features": ["report_pairs", "right_members", len(node_columns)],
                "left_embeddings": ["report_pairs", "left_members", EMBEDDING_DIMS],
                "right_embeddings": ["report_pairs", "right_members", EMBEDDING_DIMS],
                "edge_features": [
                    "report_pairs",
                    "left_members",
                    "right_members",
                    EDGE_FEATURE_COUNT,
                ],
                "edge_mask": ["report_pairs", "left_members", "right_members"],
                "member_threshold": ["report_pairs", 1],
            },
            "output_shapes": {
                "left_logits": ["report_pairs", "left_members"],
                "right_logits": ["report_pairs", "right_members"],
                "action_logit": ["report_pairs"],
                "safety_logit": ["report_pairs"],
            },
        },
        "status": "dynamic integrated member, action, and safety outputs exported for replay",
    }
    manifest_path = output / "integrated_report_shuffler.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote dynamic integrated ONNX model {artifact}")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
