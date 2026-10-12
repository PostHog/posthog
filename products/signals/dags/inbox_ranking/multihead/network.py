"""A multi-head network over a report's vector and, optionally, its team's project vectors.

    report vector ─┐
                   ├─ shared Linear(1536 → k) ─ concat ─ dropout ─ trunk (ReLU) ─ dropout ─ one logit per head
    project vectors┘   (and report ⊙ project per kind, plus a history flag per kind)

One projection serves every vector, so the report and the team's history land in one learned space
and their element-wise product can say "this report looks like what the team engaged with". Weight
decay is decoupled (AdamW), and dropout sits on the trunk's input and output.

Plain numpy with a hand-written backward pass, because torch is not a main dependency and the
prototype has to run from the default environment. A gradient check test pins the backward pass.
A label is NaN where the head has no example for the row, and a NaN label adds no gradient.
"""

import math
from collections.abc import Iterator

import numpy as np

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS

# text-embedding-3 vectors are unit length, so each component is about 1/sqrt(D). Scaling by
# sqrt(D) gives the projection unit-variance inputs, which is what its initialization assumes.
INPUT_SCALE = math.sqrt(EMBEDDING_DIMENSIONS)


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
    # (rows, D) float32.
    reports: np.ndarray
    context: ProjectContext | None = None

    def __len__(self) -> int:
        return len(self.reports)


@frozen(frozen=False)
class _Cache:
    """What the forward pass keeps for the backward pass of one batch."""

    reports: np.ndarray
    projected: np.ndarray
    context: np.ndarray | None
    projected_context: np.ndarray | None
    trunk_input: np.ndarray
    trunk_input_keep: np.ndarray | None
    trunk_pre: np.ndarray
    trunk_out: np.ndarray
    trunk_out_keep: np.ndarray | None


class MultiHeadNetwork:
    def __init__(self, *, heads: int, with_context: bool, kinds: int, config: NetworkConfig) -> None:
        self.heads = heads
        self.with_context = with_context
        self.kinds = kinds if with_context else 0
        self.config = config
        self._rng = np.random.default_rng(config.seed)
        k, h = config.projection_dim, config.trunk_dim
        trunk_in = k + self.kinds * (2 * k + 1)
        self.params: dict[str, np.ndarray] = {
            "projection_w": self._glorot(EMBEDDING_DIMENSIONS, k),
            "projection_b": np.zeros(k, dtype=np.float32),
            "trunk_w": self._glorot(trunk_in, h),
            "trunk_b": np.zeros(h, dtype=np.float32),
            "heads_w": self._glorot(h, heads),
            "heads_b": np.zeros(heads, dtype=np.float32),
        }
        self._first_moment = {name: np.zeros_like(value) for name, value in self.params.items()}
        self._second_moment = {name: np.zeros_like(value) for name, value in self.params.items()}
        self._steps = 0

    def _glorot(self, fan_in: int, fan_out: int) -> np.ndarray:
        scale = math.sqrt(2.0 / (fan_in + fan_out))
        return self._rng.normal(0.0, scale, size=(fan_in, fan_out)).astype(np.float32)

    def _dropout_mask(self, shape: tuple[int, ...]) -> np.ndarray | None:
        rate = self.config.dropout
        if rate <= 0:
            return None
        return (self._rng.random(shape) >= rate).astype(np.float32) / (1.0 - rate)

    def _forward(self, inputs: NetworkInputs, rows: np.ndarray, *, train: bool) -> tuple[np.ndarray, _Cache]:
        p = self.params
        reports = inputs.reports[rows] * INPUT_SCALE
        projected = reports @ p["projection_w"] + p["projection_b"]
        parts = [projected]
        context = projected_context = None
        if self.with_context:
            if inputs.context is None:
                raise ValueError("a network built with context needs project vectors")
            pairs = inputs.context.index[rows]
            context = inputs.context.vectors[pairs] * INPUT_SCALE
            projected_context = context @ p["projection_w"] + p["projection_b"]
            batch = len(rows)
            parts += [
                projected_context.reshape(batch, -1),
                (projected[:, None, :] * projected_context).reshape(batch, -1),
                inputs.context.has_history[pairs],
            ]
        trunk_input = np.concatenate(parts, axis=1) if len(parts) > 1 else projected
        trunk_input_keep = self._dropout_mask(trunk_input.shape) if train else None
        dropped_input = trunk_input * trunk_input_keep if trunk_input_keep is not None else trunk_input
        trunk_pre = dropped_input @ p["trunk_w"] + p["trunk_b"]
        trunk_out = np.maximum(trunk_pre, 0.0)
        trunk_out_keep = self._dropout_mask(trunk_out.shape) if train else None
        dropped_out = trunk_out * trunk_out_keep if trunk_out_keep is not None else trunk_out
        logits = dropped_out @ p["heads_w"] + p["heads_b"]
        cache = _Cache(
            reports=reports,
            projected=projected,
            context=context,
            projected_context=projected_context,
            trunk_input=dropped_input,
            trunk_input_keep=trunk_input_keep,
            trunk_pre=trunk_pre,
            trunk_out=dropped_out,
            trunk_out_keep=trunk_out_keep,
        )
        return logits, cache

    def loss_and_gradients(
        self, inputs: NetworkInputs, labels: np.ndarray, rows: np.ndarray, *, train: bool = True
    ) -> tuple[float, dict[str, np.ndarray]]:
        """The mean binary cross-entropy over the observed labels of `rows`, and its gradients.

        Weight decay is not part of the loss, because AdamW applies it to the weights directly."""
        logits, cache = self._forward(inputs, rows, train=train)
        targets = labels[rows]
        observed = ~np.isnan(targets)
        count = max(int(observed.sum()), 1)
        filled = np.where(observed, targets, 0.0)
        # log(1 + exp(-|x|)) + max(x, 0) - x * y is the cross-entropy without overflow.
        losses = np.logaddexp(0.0, -np.abs(logits)) + np.maximum(logits, 0.0) - logits * filled
        loss = float((losses * observed).sum() / count)
        d_logits = (_sigmoid(logits) - filled) * observed / count
        return loss, self._backward(cache, d_logits)

    def _backward(self, cache: _Cache, d_logits: np.ndarray) -> dict[str, np.ndarray]:
        p = self.params
        k = self.config.projection_dim
        grads: dict[str, np.ndarray] = {
            "heads_w": cache.trunk_out.T @ d_logits,
            "heads_b": d_logits.sum(axis=0),
        }
        d_out = d_logits @ p["heads_w"].T
        if cache.trunk_out_keep is not None:
            d_out *= cache.trunk_out_keep
        d_pre = d_out * (cache.trunk_pre > 0)
        grads["trunk_w"] = cache.trunk_input.T @ d_pre
        grads["trunk_b"] = d_pre.sum(axis=0)
        d_input = d_pre @ p["trunk_w"].T
        if cache.trunk_input_keep is not None:
            d_input *= cache.trunk_input_keep

        d_projected = d_input[:, :k]
        grads["projection_w"] = cache.reports.T @ d_projected
        grads["projection_b"] = d_projected.sum(axis=0)
        if cache.projected_context is not None and cache.context is not None:
            batch, kinds = len(d_input), self.kinds
            offset = k + kinds * k
            d_context = d_input[:, k:offset].reshape(batch, kinds, k)
            d_product = d_input[:, offset : offset + kinds * k].reshape(batch, kinds, k)
            d_context = d_context + d_product * cache.projected[:, None, :]
            d_projected_from_product = (d_product * cache.projected_context).sum(axis=1)
            grads["projection_w"] += cache.reports.T @ d_projected_from_product
            grads["projection_b"] += d_projected_from_product.sum(axis=0)
            flat_context = cache.context.reshape(batch * kinds, -1)
            flat_d_context = d_context.reshape(batch * kinds, k)
            grads["projection_w"] += flat_context.T @ flat_d_context
            grads["projection_b"] += flat_d_context.sum(axis=0)
        return grads

    def _step(self, grads: dict[str, np.ndarray]) -> None:
        config = self.config
        beta1, beta2, epsilon = 0.9, 0.999, 1e-8
        self._steps += 1
        for name, grad in grads.items():
            self._first_moment[name] = beta1 * self._first_moment[name] + (1 - beta1) * grad
            self._second_moment[name] = beta2 * self._second_moment[name] + (1 - beta2) * grad * grad
            first = self._first_moment[name] / (1 - beta1**self._steps)
            second = self._second_moment[name] / (1 - beta2**self._steps)
            update = first / (np.sqrt(second) + epsilon)
            # Biases are not decayed: shrinking a head's bias pulls its base rate away from the label rate.
            if name.endswith("_w"):
                update = update + config.weight_decay * self.params[name]
            self.params[name] = (self.params[name] - config.learning_rate * update).astype(np.float32)

    def fit(self, inputs: NetworkInputs, labels: np.ndarray, rows: np.ndarray) -> list[float]:
        """Train on `rows` for the configured epochs; returns the mean loss per epoch."""
        history: list[float] = []
        for _ in range(self.config.epochs):
            losses = []
            for batch in self._batches(rows, shuffle=True):
                loss, grads = self.loss_and_gradients(inputs, labels, batch)
                self._step(grads)
                losses.append(loss)
            history.append(float(np.mean(losses)) if losses else float("nan"))
        return history

    def predict(self, inputs: NetworkInputs, rows: np.ndarray) -> np.ndarray:
        """(len(rows), heads) probabilities, without dropout."""
        if len(rows) == 0:
            return np.zeros((0, self.heads), dtype=np.float32)
        return np.concatenate(
            [_sigmoid(self._forward(inputs, batch, train=False)[0]) for batch in self._batches(rows, shuffle=False)]
        )

    def _batches(self, rows: np.ndarray, *, shuffle: bool) -> Iterator[np.ndarray]:
        order = self._rng.permutation(rows) if shuffle else rows
        size = self.config.batch_size
        for start in range(0, len(order), size):
            yield order[start : start + size]


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, -values))
