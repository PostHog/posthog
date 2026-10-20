"""The network's inputs and settings, kept apart from `network.py` so that callers can build them
without importing torch."""

import numpy as np

from posthog.dataclasses import frozen

# The exported graph's names. A network without context takes only the first input.
ONNX_INPUTS = ("report", "project", "has_history")
ONNX_OUTPUT = "probabilities"


@frozen
class NetworkConfig:
    projection_dim: int = 64
    trunk_dim: int = 64
    dropout: float = 0.2
    weight_decay: float = 1e-2
    learning_rate: float = 1e-3
    epochs: int = 15
    batch_size: int = 256
    seed: int = 0


@frozen
class ProjectContext:
    """The team's project vectors per (team, moment), shared by every report of that pair."""

    # (pairs, kinds, D) float32; an all-zero row where the kind's history is too thin.
    vectors: np.ndarray
    # (pairs, kinds) float32, 1.0 where the kind had enough history to carry a mean.
    has_history: np.ndarray
    # (rows,) int, the pair each example row reads.
    index: np.ndarray


@frozen
class NetworkInputs:
    # (rows, D + report features) float32: the report vector, then any columns the feature set adds.
    reports: np.ndarray
    context: ProjectContext | None = None

    def __len__(self) -> int:
        return len(self.reports)
