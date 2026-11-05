"""A multi-head network over a report's vector and, optionally, its team's project vectors and a
user's history.

    report vector ─┐
                   ├─ shared Linear(1536 → k) ─ concat ─ dropout ─ trunk (ReLU) ─ dropout ─ one logit per head
    project vectors┤   (and report ⊙ project per kind, plus a history flag per kind)
    user offsets ──┘   (and report ⊙ user offset per kind)

One projection serves every vector, so the report and the team's history land in one learned space
and their element-wise product can say "this report looks like what the team engaged with". Weight
decay is decoupled (AdamW), and dropout sits on the trunk's input and output.

A pair network also takes `user`: per user-history kind, the user's vector minus the team's project
vector of that kind. It goes through the same projection, so its product with the report can say
"this report looks like what this person reads more than the team does". With the default of zero
user kinds, the graph has no `user` input.

The `report` input can carry `report_features` columns after the vector, such as the report's
priority levels. Those columns skip the projection and go straight into the trunk input. With the
default of zero, the graph is the vector-only one.

A label is NaN where the head has no example for the row, and a NaN label adds no gradient, so one
network trains every head on rows that only some heads cover.

torch is not a main dependency: it comes from the `inbox-ranking` dependency group. Import this
module only from dev code, never from a module on the Django, Temporal or Dagster import path.
"""

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.dags.inbox_ranking.multihead.inputs import ONNX_INPUTS, ONNX_OUTPUT, NetworkConfig, NetworkInputs

# text-embedding-3 vectors are unit length, so each component is about 1/sqrt(D). Scaling by
# sqrt(D) gives the projection unit-variance inputs, which is what its initialization assumes.
INPUT_SCALE = math.sqrt(EMBEDDING_DIMENSIONS)

ONNX_OPSET = 17


class _Model(nn.Module):
    def __init__(
        self, *, heads: int, kinds: int, config: NetworkConfig, report_features: int = 0, user_kinds: int = 0
    ) -> None:
        super().__init__()
        self.kinds = kinds
        self.report_features = report_features
        self.user_kinds = user_kinds
        k, h = config.projection_dim, config.trunk_dim
        self.projection = nn.Linear(EMBEDDING_DIMENSIONS, k)
        self.input_dropout = nn.Dropout(config.dropout)
        self.trunk = nn.Linear(k + report_features + kinds * (2 * k + 1) + user_kinds * 2 * k, h)
        self.output_dropout = nn.Dropout(config.dropout)
        self.heads = nn.Linear(h, heads)
        for layer in (self.projection, self.trunk, self.heads):
            nn.init.xavier_normal_(layer.weight)
            nn.init.zeros_(layer.bias)

    def forward(
        self,
        report: torch.Tensor,
        project: torch.Tensor | None = None,
        has_history: torch.Tensor | None = None,
        user: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """(N, heads) logits from `report` (N, D + report_features), `project` (N, kinds, D),
        `has_history` (N, kinds) and `user` (N, user_kinds, D)."""
        # Sliced only when there are extra columns, so a vector-only graph stays as it was exported.
        vector = report[:, :EMBEDDING_DIMENSIONS] if self.report_features else report
        projected = self.projection(vector * INPUT_SCALE)
        parts = [projected]
        if self.report_features:
            parts.append(report[:, EMBEDDING_DIMENSIONS:])
        if self.kinds:
            if project is None or has_history is None:
                raise ValueError("a network built with context needs project vectors")
            projected_context = self.projection(project * INPUT_SCALE)
            parts += [
                projected_context.flatten(1),
                (projected.unsqueeze(1) * projected_context).flatten(1),
                has_history,
            ]
        if self.user_kinds:
            if user is None:
                raise ValueError("a network built with user history needs user offsets")
            projected_user = self.projection(user * INPUT_SCALE)
            parts += [projected_user.flatten(1), (projected.unsqueeze(1) * projected_user).flatten(1)]
        trunk_input = torch.cat(parts, dim=1) if len(parts) > 1 else projected
        trunk_out = F.relu(self.trunk(self.input_dropout(trunk_input)))
        return self.heads(self.output_dropout(trunk_out))


class _Probabilities(nn.Module):
    """The exported graph: the sigmoid of every head's logit."""

    def __init__(self, model: _Model) -> None:
        super().__init__()
        self.model = model

    def forward(self, *inputs: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.model(*inputs))


def masked_binary_cross_entropy(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """The mean binary cross-entropy over the labels that are not NaN."""
    observed = ~torch.isnan(labels)
    # The NaN labels are replaced before the loss, not masked after it: 0 * NaN is NaN, also in the gradient.
    losses = F.binary_cross_entropy_with_logits(logits, torch.where(observed, labels, 0.0), reduction="none")
    return (losses * observed).sum() / observed.sum().clamp(min=1)


class MultiHeadNetwork:
    def __init__(
        self,
        *,
        heads: Sequence[str],
        with_context: bool,
        kinds: int,
        config: NetworkConfig,
        report_features: int = 0,
        user_kinds: int = 0,
    ) -> None:
        if user_kinds and not with_context:
            raise ValueError("a network that reads user history needs project vectors")
        self.head_names = tuple(heads)
        self.with_context = with_context
        self.kinds = kinds if with_context else 0
        self.report_features = report_features
        self.user_kinds = user_kinds
        self.config = config
        # Every random draw (initialization, shuffle, dropout) comes from this seeded state, and the
        # global torch state stays as it was.
        self._rng_state = torch.Generator().manual_seed(config.seed).get_state()
        with self._seeded():
            self.model = _Model(
                heads=len(self.head_names),
                kinds=self.kinds,
                config=config,
                report_features=report_features,
                user_kinds=user_kinds,
            )
        weights = [parameter for name, parameter in self.model.named_parameters() if name.endswith("weight")]
        biases = [parameter for name, parameter in self.model.named_parameters() if name.endswith("bias")]
        self._optimizer = torch.optim.AdamW(
            [
                {"params": weights, "weight_decay": config.weight_decay},
                # Biases are not decayed: shrinking a head's bias pulls its base rate away from the label rate.
                {"params": biases, "weight_decay": 0.0},
            ],
            lr=config.learning_rate,
        )

    def fit(self, inputs: NetworkInputs, labels: np.ndarray, rows: np.ndarray) -> list[float]:
        """Train on `rows` for the configured epochs; returns the mean loss per epoch."""
        history: list[float] = []
        self.model.train()
        with self._seeded():
            for _ in range(self.config.epochs):
                losses = []
                for batch in self._batches(rows, shuffle=True):
                    loss = masked_binary_cross_entropy(
                        self.model(*self._tensors(inputs, batch)), torch.from_numpy(labels[batch]).float()
                    )
                    self._optimizer.zero_grad()
                    loss.backward()
                    self._optimizer.step()
                    losses.append(loss.item())
                history.append(float(np.mean(losses)) if losses else float("nan"))
        return history

    def predict(self, inputs: NetworkInputs, rows: np.ndarray) -> np.ndarray:
        """(len(rows), heads) probabilities, without dropout."""
        if len(rows) == 0:
            return np.zeros((0, len(self.head_names)), dtype=np.float32)
        self.model.eval()
        with torch.no_grad():
            return np.concatenate(
                [
                    torch.sigmoid(self.model(*self._tensors(inputs, batch))).numpy()
                    for batch in self._batches(rows, shuffle=False)
                ]
            )

    def _tensors(self, inputs: NetworkInputs, rows: np.ndarray) -> tuple[torch.Tensor, ...]:
        report = torch.from_numpy(inputs.reports[rows]).float()
        if not self.with_context:
            return (report,)
        if inputs.context is None:
            raise ValueError("a network built with context needs project vectors")
        pairs = inputs.context.index[rows]
        tensors = (
            report,
            torch.from_numpy(inputs.context.vectors[pairs]).float(),
            torch.from_numpy(inputs.context.has_history[pairs]).float(),
        )
        if not self.user_kinds:
            return tensors
        if inputs.users is None:
            raise ValueError("a network built with user history needs user offsets")
        return (*tensors, torch.from_numpy(inputs.users.vectors[inputs.users.index[rows]]).float())

    def _batches(self, rows: np.ndarray, *, shuffle: bool) -> Iterator[np.ndarray]:
        order = rows[torch.randperm(len(rows)).numpy()] if shuffle else rows
        size = self.config.batch_size
        for start in range(0, len(order), size):
            yield order[start : start + size]

    @contextmanager
    def _seeded(self) -> Iterator[None]:
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(self._rng_state)
            yield
            self._rng_state = torch.get_rng_state()


def export_onnx(network: MultiHeadNetwork, path: Path) -> tuple[str, ...]:
    """Write the network to `path` as an ONNX graph and return its head order.

    The inputs are `report` (N, D + report_features), for a network with context `project` (N, kinds, D)
    and `has_history` (N, kinds), and for a network with user history `user` (N, user_kinds, D), all
    float32. The one output is `probabilities` (N, heads), in the returned head order. N is a dynamic
    axis.
    """
    module = _Probabilities(network.model).eval()
    batch = 2
    example: tuple[torch.Tensor, ...] = (torch.zeros(batch, EMBEDDING_DIMENSIONS + network.report_features),)
    if network.with_context:
        example += (torch.zeros(batch, network.kinds, EMBEDDING_DIMENSIONS), torch.zeros(batch, network.kinds))
    if network.user_kinds:
        example += (torch.zeros(batch, network.user_kinds, EMBEDDING_DIMENSIONS),)
    input_names = list(ONNX_INPUTS[: len(example)])
    # torch 2.9 defaults to the dynamo exporter, which needs onnxscript. The TorchScript exporter
    # covers these layers without it.
    torch.onnx.export(
        module,
        example,
        str(path),
        input_names=input_names,
        output_names=[ONNX_OUTPUT],
        dynamic_axes={name: {0: "batch"} for name in (*input_names, ONNX_OUTPUT)},
        opset_version=ONNX_OPSET,
        dynamo=False,
    )
    return network.head_names
