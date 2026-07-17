"""Export the exact final direct groupjoin state as a versioned ONNX artifact.

Normalization is part of the graph, so serving accepts the same raw engineered
features produced by Rust. The manifest is written only after ONNX validation.
This does not make the model serving-ready: Rust execution and replay parity are
separate required gates documented in ``NEURAL_SERVING_REVIEW.md``.
"""

# ruff: noqa: T201

from __future__ import annotations

import json
import pickle
import hashlib
import argparse
from pathlib import Path

import onnx
import numpy as np
import torch
from train_groupjoin_neural import ENGINEERED_FEATURE_NAMES, MEMBER_CAP, POOL_DIMS, TOKEN_DIMS, DirectGroupJoin


class ServingGroupJoin(torch.nn.Module):
    def __init__(self, model: DirectGroupJoin, mean: np.ndarray, std: np.ndarray) -> None:
        super().__init__()
        self.model = model
        self.register_buffer("engineered_mean", torch.from_numpy(mean.astype(np.float32)))
        self.register_buffer("engineered_std", torch.from_numpy(std.astype(np.float32)))

    def forward(
        self,
        report_tokens: torch.Tensor,
        member_mask: torch.Tensor,
        engineered_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        normalized = (engineered_features - self.engineered_mean) / self.engineered_std
        return self.model(report_tokens, member_mask, normalized)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--variant", choices=("binary", "listwise", "listwise_w05"), default="binary")
    args = parser.parse_args()

    build = Path(args.build).resolve()
    suffix = {
        "binary": "",
        "listwise": "_listwise",
        "listwise_w05": "_listwise_w05",
    }[args.variant]
    state_path = build / f"groupjoin_direct{suffix}.pt"
    state = torch.load(state_path, map_location="cpu", weights_only=False)
    if state.get("schema_version") != 1 or state.get("model_family") != "groupjoin_direct_deepsets":
        raise ValueError("unsupported groupjoin state contract")
    if list(state["feature_names"]) != ENGINEERED_FEATURE_NAMES:
        raise ValueError("engineered feature contract mismatch")
    model = DirectGroupJoin()
    model.load_state_dict(state["state_dict"], strict=True)
    serving = ServingGroupJoin(model.eval(), state["engineered_mean"], state["engineered_std"]).eval()

    output = build / f"groupjoin_direct{suffix}.onnx"
    torch.onnx.export(
        serving,
        (
            torch.zeros(3, MEMBER_CAP, TOKEN_DIMS, dtype=torch.float32),
            torch.ones(3, MEMBER_CAP, dtype=torch.bool),
            torch.zeros(3, len(ENGINEERED_FEATURE_NAMES), dtype=torch.float32),
        ),
        output,
        input_names=["report_tokens", "member_mask", "engineered_features"],
        output_names=["join_logit", "pointer_logits", "pooled_representation"],
        dynamic_axes={
            "report_tokens": {0: "candidate_reports"},
            "member_mask": {0: "candidate_reports"},
            "engineered_features": {0: "candidate_reports"},
            "join_logit": {0: "candidate_reports"},
            "pointer_logits": {0: "candidate_reports"},
            "pooled_representation": {0: "candidate_reports"},
        },
        opset_version=18,
        dynamo=False,
    )
    graph = onnx.load(output)
    onnx.checker.check_model(graph, full_check=True)
    with (build / f"groupjoin_direct{suffix}_isotonic.pkl").open("rb") as file:
        isotonic = pickle.load(file)

    manifest = {
        "schema_version": 1,
        "model_family": "groupjoin_direct_deepsets",
        "feature_contract": "lab2-groupjoin-v1",
        "artifact": {"path": output.name, "bytes": output.stat().st_size, "sha256": sha256(output)},
        "source_state": {
            "path": state_path.name,
            "bytes": state_path.stat().st_size,
            "sha256": sha256(state_path),
        },
        "opset": 18,
        "listwise_weight": float(state.get("listwise_weight", 0.0)),
        "inputs": {
            "report_tokens": {"dtype": "float32", "shape": ["candidate_reports", MEMBER_CAP, TOKEN_DIMS]},
            "member_mask": {"dtype": "bool", "shape": ["candidate_reports", MEMBER_CAP]},
            "engineered_features": {
                "dtype": "float32",
                "shape": ["candidate_reports", len(ENGINEERED_FEATURE_NAMES)],
                "names": ENGINEERED_FEATURE_NAMES,
                "normalization": "embedded in graph",
            },
        },
        "outputs": {
            "join_logit": {"dtype": "float32", "shape": ["candidate_reports"]},
            "pointer_logits": {"dtype": "float32", "shape": ["candidate_reports", MEMBER_CAP]},
            "pooled_representation": {"dtype": "float32", "shape": ["candidate_reports", POOL_DIMS]},
        },
        "calibration": {
            "type": "isotonic_linear_interpolation_clip",
            "input": "sigmoid(join_logit)",
            "x": [float(value) for value in isotonic.X_thresholds_],
            "y": [float(value) for value in isotonic.y_thresholds_],
        },
        "status": "awaiting ONNX runtime parity, Rust executor parity, and exact-artifact replay",
    }
    manifest_path = build / f"groupjoin_direct{suffix}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"wrote {output} ({output.stat().st_size:,} bytes, sha256 {sha256(output)})")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
