"""Writes the ONNX fixtures the ranking scoring tests load, so the tests need neither torch nor network.

Run from the repository root:

    uv run --with onnx==1.21.0 python products/signals/backend/test/fixtures/onnx/build_onnx_fixtures.py

Each graph is `sigmoid(report @ weights + bias)`, the shape the inbox ranking network exports:
an input `report` of shape (batch, width) and an output `probabilities` of shape (batch, heads).
The weights are seeded, so a rerun writes the same files.
"""

from pathlib import Path

import onnx
import numpy as np
from onnx import TensorProto, helper, numpy_helper

FIXTURES = Path(__file__).parent
# Opset 17 is the oldest one every onnxruntime the repo pins can read.
OPSET = 17
HEADS = 2
SERVED_WIDTH = 1536
EXPECTED_ROWS = 3


def _graph(input_name: str, width: int, seed: int) -> tuple[onnx.ModelProto, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    weights = (rng.normal(size=(width, HEADS)) * 0.05).astype(np.float32)
    bias = rng.normal(size=HEADS).astype(np.float32)
    graph = helper.make_graph(
        nodes=[
            helper.make_node("MatMul", [input_name, "weights"], ["logits_no_bias"]),
            helper.make_node("Add", ["logits_no_bias", "bias"], ["logits"]),
            helper.make_node("Sigmoid", ["logits"], ["probabilities"]),
        ],
        name="inbox_ranking_fixture",
        inputs=[helper.make_tensor_value_info(input_name, TensorProto.FLOAT, ["batch", width])],
        outputs=[helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, ["batch", HEADS])],
        initializer=[numpy_helper.from_array(weights, "weights"), numpy_helper.from_array(bias, "bias")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", OPSET)], producer_name="posthog-fixture")
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model, weights, bias


def main() -> None:
    served, weights, bias = _graph("report", SERVED_WIDTH, seed=0)
    onnx.save(served, FIXTURES / "report.onnx")
    report = np.random.default_rng(1).normal(size=(EXPECTED_ROWS, SERVED_WIDTH)).astype(np.float32)
    logits = report.astype(np.float64) @ weights.astype(np.float64) + bias.astype(np.float64)
    probabilities = (1.0 / (1.0 + np.exp(-logits))).astype(np.float32)
    np.savez(FIXTURES / "report.expected.npz", report=report, probabilities=probabilities)

    narrow, _, _ = _graph("report", 8, seed=2)
    onnx.save(narrow, FIXTURES / "narrow_report.onnx")
    renamed, _, _ = _graph("vector", 8, seed=3)
    onnx.save(renamed, FIXTURES / "unknown_input.onnx")


if __name__ == "__main__":
    main()
