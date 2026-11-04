import sys
import tempfile
import subprocess
from pathlib import Path

import pytest

import numpy as np
from parameterized import parameterized

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS, USER_HISTORY_KINDS
from products.signals.dags.inbox_ranking.dataset.project_vectors import VECTOR_KINDS
from products.signals.dags.inbox_ranking.multihead.inputs import (
    NetworkConfig,
    NetworkInputs,
    ProjectContext,
    UserContext,
)

torch = pytest.importorskip("torch")
onnxruntime = pytest.importorskip("onnxruntime")

from products.signals.dags.inbox_ranking.multihead.network import (  # noqa: E402
    MultiHeadNetwork,
    export_onnx,
    masked_binary_cross_entropy,
)

HEADS = ("open", "action", "fixed")
KINDS = len(VECTOR_KINDS)
CONFIG = NetworkConfig(projection_dim=8, trunk_dim=8, dropout=0.2, epochs=3, batch_size=16)

# A clean interpreter: pytest has already imported half the world, so this process cannot tell
# which import pulled torch in.
_IMPORT_PATH_SNAPSHOT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import posthog.dags.locations.signals
import posthog.dags.locations.signals_ml
import products.signals.backend.temporal
import products.signals.backend.ranking.scorer
import products.signals.dags.inbox_ranking.multihead.local
import sys
print("torch" in sys.modules)
"""


def _inputs(rows: int, *, with_context: bool, seed: int = 0, user_kinds: int = 0) -> NetworkInputs:
    rng = np.random.default_rng(seed)
    reports = rng.normal(0.0, 1 / np.sqrt(EMBEDDING_DIMENSIONS), size=(rows, EMBEDDING_DIMENSIONS)).astype(np.float32)
    if not with_context:
        return NetworkInputs(reports=reports)
    context = ProjectContext(
        vectors=rng.normal(0.0, 1 / np.sqrt(EMBEDDING_DIMENSIONS), size=(rows, KINDS, EMBEDDING_DIMENSIONS)).astype(
            np.float32
        ),
        has_history=rng.integers(0, 2, size=(rows, KINDS)).astype(np.float32),
        index=np.arange(rows),
    )
    users = None
    if user_kinds:
        users = UserContext(
            vectors=rng.normal(
                0.0, 1 / np.sqrt(EMBEDDING_DIMENSIONS), size=(rows, user_kinds, EMBEDDING_DIMENSIONS)
            ).astype(np.float32),
            index=np.arange(rows),
        )
    return NetworkInputs(reports=reports, context=context, users=users)


def test_a_nan_label_adds_no_gradient_and_no_loss() -> None:
    logits = torch.tensor([[2.0, -1.0, 0.5], [-0.5, 3.0, 1.0]], requires_grad=True)
    labels = torch.tensor([[1.0, float("nan"), 0.0], [0.0, float("nan"), float("nan")]])

    loss = masked_binary_cross_entropy(logits, labels)
    loss.backward()

    expected = torch.nn.functional.binary_cross_entropy_with_logits(
        torch.stack([logits[0, 0], logits[0, 2], logits[1, 0]]), torch.tensor([1.0, 0.0, 0.0])
    )
    assert loss.item() == pytest.approx(expected.item())
    assert logits.grad is not None
    assert not torch.isnan(logits.grad).any()
    assert torch.equal(logits.grad[:, 1], torch.zeros(2))
    assert logits.grad[1, 2].item() == 0.0


@parameterized.expand([("report_only", False), ("with_project_vectors", True)])
def test_a_seeded_fit_is_repeatable(_name: str, with_context: bool) -> None:
    inputs = _inputs(64, with_context=with_context)
    labels = np.random.default_rng(1).integers(0, 2, size=(64, len(HEADS))).astype(np.float32)
    labels[::3, 2] = np.nan
    rows = np.arange(64)

    runs = []
    for _ in range(2):
        network = MultiHeadNetwork(heads=HEADS, with_context=with_context, kinds=KINDS, config=CONFIG)
        losses = network.fit(inputs, labels, rows)
        runs.append((losses, network.predict(inputs, rows)))

    assert runs[0][0] == runs[1][0]
    np.testing.assert_array_equal(runs[0][1], runs[1][1])


@parameterized.expand(
    [("report_only", False, 0), ("with_project_vectors", True, 0), ("with_user_history", True, len(USER_HISTORY_KINDS))]
)
def test_onnx_export_matches_the_torch_network(_name: str, with_context: bool, user_kinds: int) -> None:
    rows = 37
    inputs = _inputs(rows, with_context=with_context, seed=2, user_kinds=user_kinds)
    labels = np.random.default_rng(3).integers(0, 2, size=(rows, len(HEADS))).astype(np.float32)
    network = MultiHeadNetwork(
        heads=HEADS, with_context=with_context, kinds=KINDS, config=CONFIG, user_kinds=user_kinds
    )
    network.fit(inputs, labels, np.arange(rows))

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "multihead.onnx"
        head_order = export_onnx(network, path)
        session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    feeds = {"report": inputs.reports}
    if inputs.context is not None:
        feeds |= {"project": inputs.context.vectors, "has_history": inputs.context.has_history}
    if inputs.users is not None:
        feeds |= {"user": inputs.users.vectors}
    assert [i.name for i in session.get_inputs()] == list(feeds)
    assert [o.name for o in session.get_outputs()] == ["probabilities"]
    (probabilities,) = session.run(None, feeds)
    assert head_order == HEADS
    np.testing.assert_allclose(probabilities, network.predict(inputs, np.arange(rows)), atol=1e-5)


def test_torch_stays_off_the_django_temporal_and_dagster_import_paths() -> None:
    result = subprocess.run([sys.executable, "-c", _IMPORT_PATH_SNAPSHOT], capture_output=True, text=True, timeout=180)

    assert result.returncode == 0, f"import failed:\n{result.stderr[-2000:]}"
    assert result.stdout.strip().splitlines()[-1] == "False", (
        "torch comes from the inbox-ranking dependency group and is not in the main image. "
        "Import multihead.network only from dev code, at call time."
    )
