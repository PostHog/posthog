"""The network's inputs and settings, kept apart from `network.py` so that callers can build them
without importing torch."""

import numpy as np

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import PROJECT_VECTOR_KINDS

# The exported graph's names. A network without context takes only the first input, and a network
# without user history only the first three.
ONNX_INPUTS = ("report", "project", "has_history", "user")
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
class PairTrainingConfig:
    """How a pair network trains its cold path and holds back its user branch, beside its
    `NetworkConfig`. A pair family without one trains as the report lane does.

    The cold path is the same network with every user input at zero. User-input dropout zeroes the
    user offsets and the user-history columns of a share of each batch's rows, so the network learns
    to score a row without them. It keeps `is_suggested_reviewer` and the report inputs.

    Early stopping holds out the newest train days as a validation split, keeps the weights of the
    epoch with the lowest validation loss, and refits on every labeled row for that many epochs.
    """

    user_input_dropout: float = 0.2
    # Dropout on the projected user offsets and their products with the report, apart from the
    # trunk's own dropout, because the user branch overfits first.
    user_dropout: float = 0.5
    validation_share: float = 0.15
    patience: int = 3
    max_epochs: int = 30

    def __post_init__(self) -> None:
        for name, share in (
            ("user_input_dropout", self.user_input_dropout),
            ("user_dropout", self.user_dropout),
            ("validation_share", self.validation_share),
        ):
            if not 0.0 <= share < 1.0:
                raise ValueError(f"{name} is {share}; pick a share in [0, 1)")
        if self.patience < 1 or self.max_epochs < 1:
            raise ValueError("patience and max_epochs must be at least 1")


@frozen
class ProjectContext:
    """The team's project vectors per (team, moment), shared by every report of that pair."""

    # (pairs, kinds, D) float32; an all-zero row where the kind's history is too thin.
    vectors: np.ndarray
    # (pairs, kinds) float32, 1.0 where the kind had enough history to carry a mean.
    has_history: np.ndarray
    # (rows,) int, the pair each example row reads.
    index: np.ndarray
    kinds: tuple[str, ...] = PROJECT_VECTOR_KINDS

    def __post_init__(self) -> None:
        if self.has_history.shape[1:] != (len(self.kinds),):
            raise ValueError(f"project context has {self.has_history.shape[1:]} history columns for kinds {self.kinds}")


@frozen
class UserContext:
    """The user-history offsets per (team, user, birth day), shared by every pair of that key."""

    # (keys, user kinds, D) float32: the user's vector minus the team's project vector of the same
    # kind (`user_offsets`), all zero where either side is missing.
    vectors: np.ndarray
    # (rows,) int, the key each pair row reads.
    index: np.ndarray


@frozen
class NetworkInputs:
    # (rows, D + report features) float32: the report vector, then any columns the feature set adds.
    reports: np.ndarray
    context: ProjectContext | None = None
    # Only a pair network reads user history, and only next to a project context.
    users: UserContext | None = None

    def __post_init__(self) -> None:
        if self.users is not None and self.context is None:
            raise ValueError("a network that reads user history needs project vectors")

    def __len__(self) -> int:
        return len(self.reports)
