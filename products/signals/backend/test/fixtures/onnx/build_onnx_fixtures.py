"""Writes the ONNX fixtures the ranking scoring tests load, so the tests need neither torch nor network.

Run from the repository root:

    uv run --with onnx==1.21.0 python products/signals/backend/test/fixtures/onnx/build_onnx_fixtures.py

Each graph is `sigmoid(report @ weights + bias)`, the shape the inbox ranking network exports:
an input `report` of shape (batch, width) and an output `probabilities` of shape (batch, heads).
`project_report.onnx` also takes `project` (batch, kinds, width) and `has_history` (batch, kinds),
the inputs of a network that reads the team's project vectors, and adds a term for each.
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
KINDS = 4
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


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    return (1.0 / (1.0 + np.exp(-logits))).astype(np.float32)


def _project_graph(seed: int) -> tuple[onnx.ModelProto, dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    weights = {
        "report_weights": (rng.normal(size=(SERVED_WIDTH, HEADS)) * 0.05).astype(np.float32),
        "project_weights": (rng.normal(size=(KINDS * SERVED_WIDTH, HEADS)) * 0.05).astype(np.float32),
        "history_weights": rng.normal(size=(KINDS, HEADS)).astype(np.float32),
        "bias": rng.normal(size=HEADS).astype(np.float32),
    }
    flat_shape = np.array([-1, KINDS * SERVED_WIDTH], dtype=np.int64)
    graph = helper.make_graph(
        nodes=[
            helper.make_node("MatMul", ["report", "report_weights"], ["report_logits"]),
            helper.make_node("Reshape", ["project", "flat_shape"], ["project_flat"]),
            helper.make_node("MatMul", ["project_flat", "project_weights"], ["project_logits"]),
            helper.make_node("MatMul", ["has_history", "history_weights"], ["history_logits"]),
            helper.make_node("Sum", ["report_logits", "project_logits", "history_logits", "bias"], ["logits"]),
            helper.make_node("Sigmoid", ["logits"], ["probabilities"]),
        ],
        name="inbox_ranking_project_fixture",
        inputs=[
            helper.make_tensor_value_info("report", TensorProto.FLOAT, ["batch", SERVED_WIDTH]),
            helper.make_tensor_value_info("project", TensorProto.FLOAT, ["batch", KINDS, SERVED_WIDTH]),
            helper.make_tensor_value_info("has_history", TensorProto.FLOAT, ["batch", KINDS]),
        ],
        outputs=[helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, ["batch", HEADS])],
        initializer=[
            *(numpy_helper.from_array(value, name) for name, value in weights.items()),
            numpy_helper.from_array(flat_shape, "flat_shape"),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", OPSET)], producer_name="posthog-fixture")
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model, weights


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

    with_project, project_weights = _project_graph(seed=4)
    onnx.save(with_project, FIXTURES / "project_report.onnx")
    # One team's project vectors, so every row shares them, as in one scorer call.
    rng = np.random.default_rng(5)
    team_project = rng.normal(size=(KINDS, SERVED_WIDTH)).astype(np.float32)
    team_history = np.array([1.0, 1.0, 0.0, 1.0], dtype=np.float32)
    team_project[team_history == 0.0] = 0.0
    project = np.repeat(team_project[None], EXPECTED_ROWS, axis=0)
    has_history = np.repeat(team_history[None], EXPECTED_ROWS, axis=0)
    logits = (
        report.astype(np.float64) @ project_weights["report_weights"].astype(np.float64)
        + project.reshape(EXPECTED_ROWS, -1).astype(np.float64) @ project_weights["project_weights"].astype(np.float64)
        + has_history.astype(np.float64) @ project_weights["history_weights"].astype(np.float64)
        + project_weights["bias"].astype(np.float64)
    )
    np.savez(
        FIXTURES / "project_report.expected.npz",
        report=report,
        project=team_project,
        has_history=team_history,
        probabilities=_sigmoid(logits),
    )


if __name__ == "__main__":
    main()
