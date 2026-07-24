"""Train an integrated bipartite report-shuffling model.

The model keeps member assignment, report-pair action, and proposed-operation
safety as separate outputs of one neural artifact. The early-projection control
matches the existing full-embedding member selector. The late-interaction
challenger computes cross-report embedding relations at all 1,536 dimensions
before projecting them into the 128-dimensional hidden space.

Only the train shard is read. Component-linked report pairs stay in one fold.
"""

# ruff: noqa: T201

from __future__ import annotations

import gc
import json
import time
import random
import argparse
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import numpy as np
import torch
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from torch import nn
from train_bipartite_member_selector import EDGE_FEATURES, prepare_edges
from train_full_embedding_member_selector import (
    EMBEDDING_DIMS,
    EPOCHS,
    HIDDEN,
    LAYERS,
    FullBipartiteBlock,
    FullEmbeddingCorpus,
    attach_embedding_rows,
    collate_bipartite,
    make_bipartite_samples,
)
from train_member_operation_risk import MEMBER_THRESHOLDS, TRUST_WEIGHTS, safe_target
from train_member_selector import add_targets, build_member_features
from train_merge_proposer_safety import component_groups

SEED = 59
HEAD_EPOCHS = 80
SAFETY_EPOCHS = 50
JOINT_EPOCHS = 0
SAFETY_SCALARS = 17
InteractionMode = Literal["early_projection", "late_interaction"]
MemberLossReduction = Literal["member", "operation"]


class IntegratedReportShuffler(nn.Module):
    """Encode a report pair once and expose member, action, and safety logits."""

    def __init__(self, node_features: int, edge_features: int, interaction: InteractionMode) -> None:
        super().__init__()
        self.interaction = interaction
        self.hidden = HIDDEN
        self.node_projection = nn.Linear(node_features, HIDDEN)
        if interaction == "early_projection":
            self.embedding_projection = nn.Sequential(
                nn.Linear(EMBEDDING_DIMS, HIDDEN, bias=False),
                nn.LayerNorm(HIDDEN),
                nn.GELU(),
                nn.Dropout(0.10),
            )
            self.relation_projection = None
        else:
            self.embedding_projection = None
            self.relation_projection = nn.Sequential(
                nn.Linear(EMBEDDING_DIMS * 4, HIDDEN, bias=False),
                nn.LayerNorm(HIDDEN),
                nn.GELU(),
                nn.Dropout(0.10),
            )
        self.side_embedding = nn.Embedding(2, HIDDEN)
        self.input_norm = nn.LayerNorm(HIDDEN)
        self.blocks = nn.ModuleList(FullBipartiteBlock(edge_features, HIDDEN) for _ in range(LAYERS))
        self.member_head = nn.Sequential(nn.LayerNorm(HIDDEN), nn.Linear(HIDDEN, 1))
        self.action_head = nn.Sequential(
            nn.LayerNorm(HIDDEN * 4),
            nn.Linear(HIDDEN * 4, HIDDEN),
            nn.GELU(),
            nn.Dropout(0.10),
            nn.Linear(HIDDEN, 1),
        )
        self.safety_head = nn.Sequential(
            nn.LayerNorm(HIDDEN * 5 + SAFETY_SCALARS),
            nn.Linear(HIDDEN * 5 + SAFETY_SCALARS, HIDDEN),
            nn.GELU(),
            nn.Dropout(0.10),
            nn.Linear(HIDDEN, 1),
        )

    @staticmethod
    def _masked_mean(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
        return (values * weights.unsqueeze(-1)).sum(dim=1) / weights.sum(dim=1, keepdim=True).clamp_min(1.0e-6)

    @staticmethod
    def _masked_max(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        maximum = values.masked_fill(~mask.unsqueeze(-1), -1.0e4).max(dim=1).values
        return torch.where(mask.any(dim=1, keepdim=True), maximum, torch.zeros_like(maximum))

    @staticmethod
    def _member_masks(edge_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return edge_mask.any(dim=2), edge_mask.any(dim=1)

    def _embedding_inputs(
        self,
        left_embeddings: torch.Tensor,
        right_embeddings: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.interaction == "early_projection":
            assert self.embedding_projection is not None
            return self.embedding_projection(left_embeddings), self.embedding_projection(right_embeddings)

        assert self.relation_projection is not None
        weights = edge_mask.to(dtype=left_embeddings.dtype)
        left_weights = weights / weights.sum(dim=2, keepdim=True).clamp_min(1.0)
        right_weights = weights / weights.sum(dim=1, keepdim=True).clamp_min(1.0)
        left_context = torch.einsum("blr,brd->bld", left_weights, right_embeddings)
        right_context = torch.einsum("blr,bld->brd", right_weights, left_embeddings)
        left_relation = torch.cat(
            [
                left_embeddings,
                left_context,
                left_embeddings * left_context,
                torch.abs(left_embeddings - left_context),
            ],
            dim=-1,
        )
        right_relation = torch.cat(
            [
                right_embeddings,
                right_context,
                right_embeddings * right_context,
                torch.abs(right_embeddings - right_context),
            ],
            dim=-1,
        )
        return self.relation_projection(left_relation), self.relation_projection(right_relation)

    def encode(
        self,
        left_features: torch.Tensor,
        right_features: torch.Tensor,
        left_embeddings: torch.Tensor,
        right_embeddings: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        left_embedding_hidden, right_embedding_hidden = self._embedding_inputs(
            left_embeddings, right_embeddings, edge_mask
        )
        left = self.input_norm(
            self.node_projection(left_features) + left_embedding_hidden + self.side_embedding.weight[1]
        )
        right = self.input_norm(
            self.node_projection(right_features) + right_embedding_hidden + self.side_embedding.weight[0]
        )
        for block in self.blocks:
            left, right = block(left, right, edge_features, edge_mask)
        left_mask, right_mask = self._member_masks(edge_mask)
        return left, right, left_mask, right_mask

    def action_features(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        left_mask: torch.Tensor,
        right_mask: torch.Tensor,
    ) -> torch.Tensor:
        left_weights = left_mask.to(dtype=left.dtype)
        right_weights = right_mask.to(dtype=right.dtype)
        left_mean = self._masked_mean(left, left_weights)
        right_mean = self._masked_mean(right, right_weights)
        left_max = self._masked_max(left, left_mask)
        right_max = self._masked_max(right, right_mask)
        return torch.cat(
            [
                left_mean + right_mean,
                torch.abs(left_mean - right_mean),
                left_max + right_max,
                torch.abs(left_max - right_max),
            ],
            dim=-1,
        )

    def safety_features(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        left_mask: torch.Tensor,
        right_mask: torch.Tensor,
        left_logits: torch.Tensor,
        right_logits: torch.Tensor,
        action_logit: torch.Tensor,
        member_threshold: torch.Tensor,
    ) -> torch.Tensor:
        threshold = member_threshold.reshape(-1, 1)
        left_probability = torch.sigmoid(left_logits)
        right_probability = torch.sigmoid(right_logits)
        left_selected = torch.sigmoid((left_probability - threshold) / 0.05) * left_mask
        right_selected = torch.sigmoid((right_probability - threshold) / 0.05) * right_mask
        left_unselected = (1.0 - left_selected) * left_mask
        right_unselected = (1.0 - right_selected) * right_mask

        left_selected_pool = self._masked_mean(left, left_selected)
        right_selected_pool = self._masked_mean(right, right_selected)
        left_unselected_pool = self._masked_mean(left, left_unselected)
        right_unselected_pool = self._masked_mean(right, right_unselected)

        left_count = left_mask.to(dtype=left.dtype).sum(dim=1, keepdim=True).clamp_min(1.0)
        right_count = right_mask.to(dtype=right.dtype).sum(dim=1, keepdim=True).clamp_min(1.0)
        left_share = left_selected.sum(dim=1, keepdim=True) / left_count
        right_share = right_selected.sum(dim=1, keepdim=True) / right_count
        left_selected_count = left_selected.sum(dim=1, keepdim=True)
        right_selected_count = right_selected.sum(dim=1, keepdim=True)
        selected_count = left_selected_count + right_selected_count
        combined_count = left_count + right_count
        left_selected_probability = (left_probability * left_selected).sum(dim=1, keepdim=True) / left_selected.sum(
            dim=1, keepdim=True
        ).clamp_min(1.0e-6)
        right_selected_probability = (right_probability * right_selected).sum(dim=1, keepdim=True) / right_selected.sum(
            dim=1, keepdim=True
        ).clamp_min(1.0e-6)
        scalars = torch.cat(
            [
                threshold,
                left_share + right_share,
                torch.abs(left_share - right_share),
                torch.minimum(left_share, right_share),
                left_selected_probability + right_selected_probability,
                torch.abs(left_selected_probability - right_selected_probability),
                torch.sigmoid(action_logit).reshape(-1, 1),
                torch.log1p(left_count),
                torch.log1p(right_count),
                torch.log1p(combined_count),
                torch.log1p(left_selected_count),
                torch.log1p(right_selected_count),
                torch.log1p(selected_count),
                torch.log1p((combined_count - selected_count).clamp_min(0.0)),
                left_share * right_share,
                torch.maximum(left_share, right_share),
                (1.0 - left_share) * (1.0 - right_share),
            ],
            dim=-1,
        )
        return torch.cat(
            [
                left_selected_pool + right_selected_pool,
                torch.abs(left_selected_pool - right_selected_pool),
                left_selected_pool * right_selected_pool,
                left_unselected_pool + right_unselected_pool,
                torch.abs(left_unselected_pool - right_unselected_pool),
                scalars,
            ],
            dim=-1,
        )

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
        left, right, left_mask, right_mask = self.encode(
            left_features,
            right_features,
            left_embeddings,
            right_embeddings,
            edge_features,
            edge_mask,
        )
        left_logits = self.member_head(left).squeeze(-1)
        right_logits = self.member_head(right).squeeze(-1)
        action_logit = self.action_head(self.action_features(left, right, left_mask, right_mask)).squeeze(-1)
        safety_logit = self.safety_head(
            self.safety_features(
                left,
                right,
                left_mask,
                right_mask,
                left_logits,
                right_logits,
                action_logit,
                member_threshold,
            )
        ).squeeze(-1)
        return left_logits, right_logits, action_logit, safety_logit


def load_compatible_state_dict(model: IntegratedReportShuffler, state_dict: dict[str, torch.Tensor]) -> None:
    """Load a staged model while allowing appended safety scalar features."""

    target = model.state_dict()
    expandable = {"safety_head.0.weight", "safety_head.0.bias", "safety_head.1.weight"}
    for name, value in state_dict.items():
        if name not in target:
            raise ValueError(f"unexpected checkpoint parameter: {name}")
        if target[name].shape == value.shape:
            target[name] = value
            continue
        if name not in expandable or target[name].shape[:-1] != value.shape[:-1]:
            raise ValueError(
                f"incompatible checkpoint parameter {name}: checkpoint={tuple(value.shape)} "
                f"model={tuple(target[name].shape)}"
            )
        if target[name].shape[-1] < value.shape[-1]:
            raise ValueError(f"checkpoint parameter {name} is wider than the model")
        target[name][..., : value.shape[-1]] = value
    model.load_state_dict(target)


def member_class_balance(
    samples: list[dict[str, Any]],
    sample_weights: dict[str, float],
    reduction: MemberLossReduction,
) -> tuple[float, float]:
    positive = negative = 0.0
    for sample in samples:
        merge_id = str(sample["merge_id"])
        weight = sample_weights[merge_id]
        selected = float(sample["left_target"].sum() + sample["right_target"].sum())
        total = len(sample["left_target"]) + len(sample["right_target"])
        if reduction == "operation":
            positive += weight * selected / total
            negative += weight * (total - selected) / total
        else:
            positive += weight * selected
            negative += weight * (total - selected)
    return positive, negative


def member_training_loss(
    left_logits: torch.Tensor,
    right_logits: torch.Tensor,
    left_targets: torch.Tensor,
    right_targets: torch.Tensor,
    left_active: torch.Tensor,
    right_active: torch.Tensor,
    operation_weights: torch.Tensor,
    positive_weight: torch.Tensor,
    reduction: MemberLossReduction,
) -> torch.Tensor:
    if reduction == "member":
        logits = torch.cat([left_logits[left_active], right_logits[right_active]])
        targets = torch.cat([left_targets[left_active], right_targets[right_active]])
        member_weights = torch.cat(
            [
                operation_weights[:, None].expand_as(left_logits)[left_active],
                operation_weights[:, None].expand_as(right_logits)[right_active],
            ]
        )
        bce_values = nn.functional.binary_cross_entropy_with_logits(
            logits,
            targets,
            reduction="none",
            pos_weight=positive_weight,
        )
        bce = (bce_values * member_weights).sum() / member_weights.sum().clamp_min(1.0e-9)
        probabilities = torch.sigmoid(logits)
        dice = 1.0 - (2.0 * (member_weights * probabilities * targets).sum() + 1.0) / (
            (member_weights * probabilities).sum() + (member_weights * targets).sum() + 1.0
        )
        return bce + 0.25 * dice

    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for position in range(len(left_logits)):
        logits = torch.cat(
            [
                left_logits[position][left_active[position]],
                right_logits[position][right_active[position]],
            ]
        )
        if not len(logits):
            continue
        targets = torch.cat(
            [
                left_targets[position][left_active[position]],
                right_targets[position][right_active[position]],
            ]
        )
        bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=positive_weight)
        probabilities = torch.sigmoid(logits)
        dice = 1.0 - (2.0 * (probabilities * targets).sum() + 1.0) / (
            probabilities.sum() + targets.sum() + 1.0
        )
        losses.append(bce + 0.25 * dice)
        weights.append(operation_weights[position])
    if not losses:
        return left_logits.sum() * 0.0
    stacked_weights = torch.stack(weights)
    return (torch.stack(losses) * stacked_weights).sum() / stacked_weights.sum().clamp_min(1.0e-9)


def train_member_encoder(
    model: IntegratedReportShuffler,
    samples: list[dict[str, Any]],
    sample_weights: dict[str, float],
    embeddings: np.ndarray,
    device: torch.device,
    epochs: int,
    batch_size: int,
    seed: int,
    reduction: MemberLossReduction,
    learning_rate: float,
) -> list[float]:
    model.to(device)
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=5.0e-4)
    positive, negative = member_class_balance(samples, sample_weights, reduction)
    positive_weight = torch.tensor(negative / max(positive, 1.0e-9), device=device)
    curve: list[float] = []
    for epoch in range(epochs):
        losses: list[torch.Tensor] = []
        for batch in bucketed_bipartite_batches(samples, embeddings, batch_size, seed + epoch):
            left, right, _left_mask, _right_mask = model.encode(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["left_embeddings"].to(device),
                batch["right_embeddings"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            left_logits = model.member_head(left).squeeze(-1)
            right_logits = model.member_head(right).squeeze(-1)
            left_active = batch["left_mask"].to(device)
            right_active = batch["right_mask"].to(device)
            operation_weights = torch.tensor(
                [sample_weights[str(merge_id)] for merge_id in batch["merge_ids"]],
                dtype=torch.float32,
                device=device,
            )
            loss = member_training_loss(
                left_logits,
                right_logits,
                batch["left_target"].to(device),
                batch["right_target"].to(device),
                left_active,
                right_active,
                operation_weights,
                positive_weight,
                reduction,
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(loss.detach())
        epoch_loss = float(torch.stack(losses).mean().cpu())
        curve.append(epoch_loss)
        if epoch in {0, 9, 19, 29, epochs - 1}:
            print(f"member epoch {epoch + 1}/{epochs}: loss={epoch_loss:.5f}", flush=True)
    return curve


def encode_samples(
    model: IntegratedReportShuffler,
    samples: list[dict[str, Any]],
    embeddings: np.ndarray,
    device: torch.device,
    batch_size: int,
    seed: int,
) -> dict[str, dict[str, Any]]:
    encoded: dict[str, dict[str, Any]] = {}
    sample_by_id = {str(sample["merge_id"]): sample for sample in samples}
    model.eval()
    with torch.no_grad():
        for batch in bucketed_bipartite_batches(samples, embeddings, batch_size, seed):
            left, right, left_mask, right_mask = model.encode(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["left_embeddings"].to(device),
                batch["right_embeddings"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            left_logits = model.member_head(left).squeeze(-1)
            right_logits = model.member_head(right).squeeze(-1)
            action_features = model.action_features(left, right, left_mask, right_mask)
            for position, merge_id in enumerate(batch["merge_ids"]):
                sample = sample_by_id[str(merge_id)]
                left_count = len(sample["left_target"])
                right_count = len(sample["right_target"])
                encoded[str(merge_id)] = {
                    "left": left[position : position + 1, :left_count].cpu(),
                    "right": right[position : position + 1, :right_count].cpu(),
                    "left_mask": left_mask[position : position + 1, :left_count].cpu(),
                    "right_mask": right_mask[position : position + 1, :right_count].cpu(),
                    "left_logits": left_logits[position : position + 1, :left_count].cpu(),
                    "right_logits": right_logits[position : position + 1, :right_count].cpu(),
                    "action_features": action_features[position].cpu(),
                }
    return encoded


def train_cached_head(
    head: nn.Module,
    values: torch.Tensor,
    targets: torch.Tensor,
    weights: torch.Tensor,
    device: torch.device,
    epochs: int,
    seed: int,
) -> list[float]:
    head.to(device)
    generator = torch.Generator().manual_seed(seed)
    positive = float(weights[targets == 1].sum())
    negative = float(weights[targets == 0].sum())
    positive_weight = torch.tensor(negative / max(positive, 1.0e-9), device=device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1.0e-3, weight_decay=3.0e-4)
    curve: list[float] = []
    for epoch in range(epochs):
        permutation = torch.randperm(len(values), generator=generator)
        losses: list[torch.Tensor] = []
        head.train()
        for start in range(0, len(values), 256):
            selected = permutation[start : start + 256]
            logits = head(values[selected].to(device)).squeeze(-1)
            batch_targets = targets[selected].to(device)
            batch_weights = weights[selected].to(device)
            loss_values = nn.functional.binary_cross_entropy_with_logits(
                logits, batch_targets, reduction="none", pos_weight=positive_weight
            )
            loss = (loss_values * batch_weights).sum() / batch_weights.sum().clamp_min(1.0e-9)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(loss.detach())
        epoch_loss = float(torch.stack(losses).mean().cpu())
        curve.append(epoch_loss)
        if epoch in {0, epochs - 1}:
            print(f"head epoch {epoch + 1}/{epochs}: loss={epoch_loss:.5f}", flush=True)
    return curve


def action_data(
    labels: pd.DataFrame,
    encoded: dict[str, dict[str, Any]],
    selected_ids: set[str],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[str]]:
    rows = labels.loc[labels["merge_id"].astype(str).isin(selected_ids)]
    ids = rows["merge_id"].astype(str).tolist()
    values = torch.stack([encoded[merge_id]["action_features"] for merge_id in ids])
    targets = torch.tensor((rows["member_verdict"] != "keep_separate").to_numpy(np.float32))
    weights = torch.tensor(
        [
            float(row.training_weight) * TRUST_WEIGHTS[str(row.member_label_tier)]
            for row in rows.itertuples(index=False)
        ],
        dtype=torch.float32,
    )
    return values, targets, weights, ids


def action_probabilities(
    model: IntegratedReportShuffler,
    encoded: dict[str, dict[str, Any]],
    device: torch.device,
) -> dict[str, float]:
    ids = list(encoded)
    values = torch.stack([encoded[merge_id]["action_features"] for merge_id in ids])
    probabilities: list[np.ndarray] = []
    model.action_head.eval()
    with torch.no_grad():
        for start in range(0, len(values), 512):
            probabilities.append(torch.sigmoid(model.action_head(values[start : start + 512].to(device))).cpu().numpy())
    flattened = np.concatenate(probabilities).reshape(-1)
    return dict(zip(ids, flattened.astype(float), strict=True))


def safety_feature(
    model: IntegratedReportShuffler,
    row: dict[str, Any],
    action_probability: float,
    threshold: float,
) -> torch.Tensor:
    action_logit = torch.logit(torch.tensor([action_probability], dtype=torch.float32).clamp(1.0e-6, 1.0 - 1.0e-6))
    return model.safety_features(
        row["left"],
        row["right"],
        row["left_mask"],
        row["right_mask"],
        row["left_logits"],
        row["right_logits"],
        action_logit,
        torch.tensor([[threshold]], dtype=torch.float32),
    ).squeeze(0)


def proposal_target(sample: dict[str, Any], row: dict[str, Any], threshold: float) -> tuple[int, bool]:
    left_probabilities = torch.sigmoid(row["left_logits"]).numpy().reshape(-1)
    right_probabilities = torch.sigmoid(row["right_logits"]).numpy().reshape(-1)
    selected_left = {
        int(index)
        for index, probability in zip(sample["left_indices"], left_probabilities, strict=True)
        if probability >= threshold
    }
    selected_right = {
        int(index)
        for index, probability in zip(sample["right_indices"], right_probabilities, strict=True)
        if probability >= threshold
    }
    label = pd.Series({"member_components": sample["member_components"]})
    return safe_target(label, selected_left, selected_right), bool(selected_left and selected_right)


def weighted_bce_with_logits(
    logits: torch.Tensor,
    targets: torch.Tensor,
    weights: torch.Tensor,
    positive_weight: torch.Tensor,
) -> torch.Tensor:
    losses = nn.functional.binary_cross_entropy_with_logits(
        logits,
        targets,
        reduction="none",
        pos_weight=positive_weight,
    )
    return (losses * weights).sum() / weights.sum().clamp_min(1.0e-9)


def weighted_probability_bce(
    probabilities: torch.Tensor,
    targets: torch.Tensor,
    weights: torch.Tensor,
    positive_weight: torch.Tensor,
) -> torch.Tensor:
    losses = nn.functional.binary_cross_entropy(
        probabilities.clamp(1.0e-6, 1.0 - 1.0e-6),
        targets,
        reduction="none",
    )
    class_weights = torch.where(targets == 1.0, positive_weight, torch.ones_like(targets))
    return (losses * class_weights * weights).sum() / weights.sum().clamp_min(1.0e-9)


def bucketed_bipartite_batches(
    samples: list[dict[str, Any]],
    embeddings: np.ndarray,
    batch_size: int,
    seed: int,
) -> Iterator[dict[str, Any]]:
    """Batch report pairs by both dimensions to limit padding and MPS work."""

    rng = np.random.default_rng(seed)
    shape_buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
    log_base = np.log(1.5)
    for sample in samples:
        left_size = max(len(sample["left_target"]), 1)
        right_size = max(len(sample["right_target"]), 1)
        shape = (
            int(np.floor(np.log(left_size) / log_base)),
            int(np.floor(np.log(right_size) / log_base)),
        )
        shape_buckets.setdefault(shape, []).append(sample)

    batches: list[list[dict[str, Any]]] = []
    for bucket in shape_buckets.values():
        rng.shuffle(bucket)
        batches.extend(bucket[offset : offset + batch_size] for offset in range(0, len(bucket), batch_size))
    rng.shuffle(batches)
    for batch in batches:
        yield collate_bipartite(batch, embeddings)


def joint_finetune(
    model: IntegratedReportShuffler,
    labels: pd.DataFrame,
    samples: list[dict[str, Any]],
    embeddings: np.ndarray,
    encoded: dict[str, dict[str, Any]],
    train_ids: set[str],
    device: torch.device,
    epochs: int,
    learning_rate: float,
    member_weight: float,
    action_weight: float,
    safety_weight: float,
    operation_weight: float,
    member_scope: Literal["subset", "all"],
    member_loss_reduction: MemberLossReduction,
    batch_size: int,
    seed: int,
) -> list[dict[str, float]]:
    """Fine-tune the shared representation against all serving decisions.

    Safety labels are frozen from the staged model's on-policy masks. Each
    operation visits one threshold per epoch, rotating across the fixed grid.
    This avoids a discontinuous target changing inside the gradient step while
    the differentiable soft mask still lets safety update the member encoder.
    """

    train_samples = [sample for sample in samples if str(sample["merge_id"]) in train_ids]
    sample_by_id = {str(sample["merge_id"]): sample for sample in train_samples}
    label_by_id = {
        str(row.merge_id): row
        for row in labels.loc[labels["merge_id"].astype(str).isin(train_ids)].itertuples(index=False)
    }
    subset_ids = {merge_id for merge_id, row in label_by_id.items() if str(row.member_verdict) == "merge_subset"}
    member_supervised_ids = subset_ids if member_scope == "subset" else train_ids
    sample_weights = {
        merge_id: float(row.training_weight) * TRUST_WEIGHTS[str(row.member_label_tier)]
        for merge_id, row in label_by_id.items()
    }
    action_targets = {
        merge_id: float(str(row.member_verdict) != "keep_separate") for merge_id, row in label_by_id.items()
    }
    proposal_targets = {
        (merge_id, threshold): proposal_target(sample_by_id[merge_id], encoded[merge_id], threshold)
        for merge_id in sorted(train_ids)
        for threshold in MEMBER_THRESHOLDS
    }

    member_samples = [
        sample for sample in train_samples if str(sample["merge_id"]) in member_supervised_ids
    ]
    member_positive, member_negative = member_class_balance(
        member_samples,
        sample_weights,
        member_loss_reduction,
    )
    action_positive = sum(sample_weights[merge_id] for merge_id, target in action_targets.items() if target == 1.0)
    action_negative = sum(sample_weights[merge_id] for merge_id, target in action_targets.items() if target == 0.0)
    safety_positive = sum(
        sample_weights[merge_id]
        for (merge_id, _threshold), (target, two_sided) in proposal_targets.items()
        if two_sided and target == 1
    )
    safety_negative = sum(
        sample_weights[merge_id]
        for (merge_id, _threshold), (target, two_sided) in proposal_targets.items()
        if two_sided and target == 0
    )
    member_positive_weight = torch.tensor(member_negative / max(member_positive, 1.0e-9), device=device)
    action_positive_weight = torch.tensor(action_negative / max(action_positive, 1.0e-9), device=device)
    safety_positive_weight = torch.tensor(safety_negative / max(safety_positive, 1.0e-9), device=device)

    ordered_ids = {merge_id: position for position, merge_id in enumerate(sorted(train_ids))}
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1.0e-4)
    curve: list[dict[str, float]] = []
    for epoch in range(epochs):
        model.train()
        epoch_losses: dict[str, list[torch.Tensor]] = {
            "total": [],
            "member": [],
            "action": [],
            "safety": [],
            "operation": [],
        }
        for batch in bucketed_bipartite_batches(train_samples, embeddings, batch_size, seed + epoch):
            merge_ids = [str(merge_id) for merge_id in batch["merge_ids"]]
            thresholds = [
                MEMBER_THRESHOLDS[(ordered_ids[merge_id] + epoch) % len(MEMBER_THRESHOLDS)] for merge_id in merge_ids
            ]
            threshold_tensor = torch.tensor(thresholds, dtype=torch.float32, device=device).reshape(-1, 1)
            left_logits, right_logits, action_logits, safety_logits = model(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["left_embeddings"].to(device),
                batch["right_embeddings"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
                threshold_tensor,
            )
            batch_weights = torch.tensor(
                [sample_weights[merge_id] for merge_id in merge_ids], dtype=torch.float32, device=device
            )
            action_target_tensor = torch.tensor(
                [action_targets[merge_id] for merge_id in merge_ids], dtype=torch.float32, device=device
            )
            action_loss = weighted_bce_with_logits(
                action_logits,
                action_target_tensor,
                batch_weights,
                action_positive_weight,
            )

            member_position_values = [merge_id in member_supervised_ids for merge_id in merge_ids]
            member_positions = torch.tensor(member_position_values, dtype=torch.bool, device=device)
            left_active = batch["left_mask"].to(device) & member_positions.unsqueeze(1)
            right_active = batch["right_mask"].to(device) & member_positions.unsqueeze(1)
            if any(member_position_values):
                member_loss = member_training_loss(
                    left_logits,
                    right_logits,
                    batch["left_target"].to(device),
                    batch["right_target"].to(device),
                    left_active,
                    right_active,
                    batch_weights,
                    member_positive_weight,
                    member_loss_reduction,
                )
            else:
                member_loss = action_logits.sum() * 0.0

            safety_target_values: list[float] = []
            two_sided_values: list[bool] = []
            for merge_id, threshold in zip(merge_ids, thresholds, strict=True):
                target, two_sided = proposal_targets[(merge_id, threshold)]
                safety_target_values.append(float(target))
                two_sided_values.append(two_sided)
            safety_target_tensor = torch.tensor(safety_target_values, dtype=torch.float32, device=device)
            two_sided = torch.tensor(two_sided_values, dtype=torch.bool, device=device)
            if any(two_sided_values):
                safety_loss = weighted_bce_with_logits(
                    safety_logits[two_sided],
                    safety_target_tensor[two_sided],
                    batch_weights[two_sided],
                    safety_positive_weight,
                )
                operation_probability = torch.sigmoid(action_logits[two_sided]) * torch.sigmoid(
                    safety_logits[two_sided]
                )
                operation_loss = weighted_probability_bce(
                    operation_probability,
                    safety_target_tensor[two_sided],
                    batch_weights[two_sided],
                    safety_positive_weight,
                )
            else:
                safety_loss = action_logits.sum() * 0.0
                operation_loss = action_logits.sum() * 0.0

            loss = (
                member_weight * member_loss
                + action_weight * action_loss
                + safety_weight * safety_loss
                + operation_weight * operation_loss
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            for name, value in (
                ("total", loss),
                ("member", member_loss),
                ("action", action_loss),
                ("safety", safety_loss),
                ("operation", operation_loss),
            ):
                epoch_losses[name].append(value.detach())
        epoch_summary = {name: float(torch.stack(values).mean().cpu()) for name, values in epoch_losses.items()}
        curve.append(epoch_summary)
        summary = " ".join(f"{name}={value:.5f}" for name, value in epoch_summary.items())
        print(f"joint epoch {epoch + 1}/{epochs}: {summary}", flush=True)
    return curve


def safety_data(
    labels: pd.DataFrame,
    samples: list[dict[str, Any]],
    encoded: dict[str, dict[str, Any]],
    action_scores: dict[str, float],
    selected_ids: set[str],
    model: IntegratedReportShuffler,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[tuple[str, float]]]:
    label_by_id = labels.set_index(labels["merge_id"].astype(str), drop=False)
    sample_by_id = {str(sample["merge_id"]): sample for sample in samples}
    values: list[torch.Tensor] = []
    targets: list[float] = []
    weights: list[float] = []
    keys: list[tuple[str, float]] = []
    for merge_id in sorted(selected_ids):
        sample = sample_by_id[merge_id]
        label = label_by_id.loc[merge_id]
        for threshold in MEMBER_THRESHOLDS:
            target, two_sided = proposal_target(sample, encoded[merge_id], threshold)
            if not two_sided:
                continue
            values.append(safety_feature(model, encoded[merge_id], action_scores[merge_id], threshold))
            targets.append(float(target))
            weights.append(float(label["training_weight"]) * TRUST_WEIGHTS[str(label["member_label_tier"])])
            keys.append((merge_id, threshold))
    return (
        torch.stack(values),
        torch.tensor(targets, dtype=torch.float32),
        torch.tensor(weights, dtype=torch.float32),
        keys,
    )


def score_fold(
    model: IntegratedReportShuffler,
    labels: pd.DataFrame,
    samples: list[dict[str, Any]],
    encoded: dict[str, dict[str, Any]],
    action_scores: dict[str, float],
    selected_ids: set[str],
    fold: int,
    device: torch.device,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sample_by_id = {str(sample["merge_id"]): sample for sample in samples}
    label_by_id = labels.set_index(labels["merge_id"].astype(str), drop=False)
    member_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    model.safety_head.eval()
    with torch.no_grad():
        for merge_id in sorted(selected_ids):
            sample = sample_by_id[merge_id]
            row = encoded[merge_id]
            label = label_by_id.loc[merge_id]
            left_probabilities = torch.sigmoid(row["left_logits"]).numpy().reshape(-1)
            right_probabilities = torch.sigmoid(row["right_logits"]).numpy().reshape(-1)
            for side_left, indices, targets, probabilities in (
                (1.0, sample["left_indices"], sample["left_target"], left_probabilities),
                (0.0, sample["right_indices"], sample["right_target"], right_probabilities),
            ):
                for member_index, target, probability in zip(indices, targets, probabilities, strict=True):
                    member_rows.append(
                        {
                            "merge_id": merge_id,
                            "component_fold": fold,
                            "side_left": side_left,
                            "member_index": int(member_index),
                            "target": int(target),
                            "probability:member": float(probability),
                        }
                    )
            action_rows.append(
                {
                    "merge_id": merge_id,
                    "component_fold": fold,
                    "member_verdict": str(label["member_verdict"]),
                    "target": int(label["member_verdict"] != "keep_separate"),
                    "probability:action": action_scores[merge_id],
                }
            )
            for threshold in MEMBER_THRESHOLDS:
                target, two_sided = proposal_target(sample, row, threshold)
                probability = np.nan
                if two_sided:
                    features = safety_feature(model, row, action_scores[merge_id], threshold)
                    probability = float(torch.sigmoid(model.safety_head(features.to(device))).cpu().item())
                safety_rows.append(
                    {
                        "merge_id": merge_id,
                        "component_fold": fold,
                        "member_threshold": threshold,
                        "target": target,
                        "two_sided": two_sided,
                        "probability:safety": probability,
                    }
                )
    return member_rows, action_rows, safety_rows


def train_fold(
    interaction: InteractionMode,
    labels: pd.DataFrame,
    frame: pd.DataFrame,
    edges: pd.DataFrame,
    corpus: FullEmbeddingCorpus,
    fold_by_id: dict[str, int],
    held_fold: int | None,
    device: torch.device,
    member_epochs: int,
    member_batch_size: int,
    member_loss_reduction: MemberLossReduction,
    member_learning_rate: float,
    head_epochs: int,
    safety_epochs: int,
    joint_epochs: int,
    joint_learning_rate: float,
    joint_member_weight: float,
    joint_action_weight: float,
    joint_safety_weight: float,
    joint_operation_weight: float,
    joint_member_scope: Literal["subset", "all"],
    joint_batch_size: int,
    staged_checkpoint_dir: Path | None,
    staged_final_state: Path | None,
    member_initial_state: Path | None,
    fine_tune_member_initial_state: bool,
) -> tuple[
    IntegratedReportShuffler,
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[str, float],
    dict[str, Any],
    dict[str, Any],
]:
    all_ids = set(labels["merge_id"].astype(str))
    train_ids = (
        all_ids if held_fold is None else {merge_id for merge_id in all_ids if fold_by_id[merge_id] != held_fold}
    )
    subset_ids = set(labels.loc[labels["member_verdict"] == "merge_subset", "merge_id"].astype(str))
    member_train_ids = train_ids & subset_ids

    member_initial_payload: dict[str, Any] | None = None
    if member_initial_state is not None:
        member_initial_payload = torch.load(member_initial_state, map_location="cpu", weights_only=False)
        if member_initial_payload.get("model_family") != "integrated_bipartite_report_shuffler":
            raise ValueError("unsupported member-initial-state model family")
        if member_initial_payload.get("interaction") != interaction:
            raise ValueError("member-initial-state interaction does not match requested interaction")
        node_columns = list(member_initial_payload["node_columns"])
        missing_node_columns = set(node_columns) - set(frame.columns)
        if missing_node_columns:
            raise ValueError(f"member-initial-state node columns are missing: {sorted(missing_node_columns)}")
        node_mean = np.asarray(member_initial_payload["node_mean"], dtype=np.float32)
        node_std = np.asarray(member_initial_payload["node_std"], dtype=np.float32)
        edge_mean = np.asarray(member_initial_payload["edge_mean"], dtype=np.float32)
        edge_std = np.asarray(member_initial_payload["edge_std"], dtype=np.float32)
    else:
        excluded = {"merge_id", "member_index", "embedding_row", "target", "member_verdict"}
        node_columns = [column for column in frame if column not in excluded and not column.startswith("report_gate_")]
        node_train = frame.loc[frame["merge_id"].astype(str).isin(member_train_ids), node_columns]
        node_mean = node_train.mean().to_numpy(np.float32)
        node_std = node_train.std().clip(lower=1.0e-5).to_numpy(np.float32)
        edge_train = edges.loc[edges["merge_id"].astype(str).isin(member_train_ids), list(EDGE_FEATURES)]
        edge_mean = edge_train.mean().to_numpy(np.float32)
        edge_std = edge_train.std().clip(lower=1.0e-5).to_numpy(np.float32)
    samples = make_bipartite_samples(
        frame,
        edges,
        node_columns,
        node_mean,
        node_std,
        edge_mean,
        edge_std,
        fold_by_id,
    )
    components = labels.set_index(labels["merge_id"].astype(str))["member_components"].astype(str).to_dict()
    for sample in samples:
        sample["member_components"] = components[str(sample["merge_id"])]
    member_train = [sample for sample in samples if str(sample["merge_id"]) in member_train_ids]
    member_sample_weights = {
        str(row.merge_id): float(row.training_weight) * TRUST_WEIGHTS[str(row.member_label_tier)]
        for row in labels.loc[labels["merge_id"].astype(str).isin(member_train_ids)].itertuples(index=False)
    }
    print(
        f"fold={held_fold if held_fold is not None else 'final'} interaction={interaction} "
        f"member_train={len(member_train)} head_train={len(train_ids)}",
        flush=True,
    )

    seed = SEED + (held_fold if held_fold is not None else 5)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = IntegratedReportShuffler(len(node_columns), len(EDGE_FEATURES), interaction).to(device)
    training_curves: dict[str, Any] = {"member": [], "action": [], "safety": [], "joint": []}
    checkpoint_name = f"fold-{held_fold if held_fold is not None else 'final'}.pt"
    staged_checkpoint = (
        staged_final_state
        if held_fold is None and staged_final_state is not None
        else staged_checkpoint_dir / checkpoint_name
        if staged_checkpoint_dir
        else None
    )
    if staged_checkpoint is not None and staged_checkpoint.exists():
        checkpoint_payload = torch.load(staged_checkpoint, map_location="cpu", weights_only=False)
        state_dict = checkpoint_payload.get("state_dict", checkpoint_payload)
        load_compatible_state_dict(model, state_dict)
        print(f"loaded staged checkpoint {staged_checkpoint}", flush=True)
        encoded = encode_samples(model, samples, corpus.embeddings, device, member_batch_size, seed)
    else:
        if member_initial_payload is not None:
            initial_state_dict = member_initial_payload["state_dict"]
            target_state_dict = model.state_dict()
            for name, target in target_state_dict.items():
                if name.startswith(("action_head.", "safety_head.")):
                    continue
                if name not in initial_state_dict or initial_state_dict[name].shape != target.shape:
                    raise ValueError(f"member-initial-state parameter is missing or incompatible: {name}")
                target_state_dict[name] = initial_state_dict[name]
            model.load_state_dict(target_state_dict)
            print(f"loaded member initializer {member_initial_state}", flush=True)
            if fine_tune_member_initial_state:
                training_curves["member"] = train_member_encoder(
                    model,
                    member_train,
                    member_sample_weights,
                    corpus.embeddings,
                    device,
                    member_epochs,
                    member_batch_size,
                    seed,
                    member_loss_reduction,
                    member_learning_rate,
                )
        else:
            training_curves["member"] = train_member_encoder(
                model,
                member_train,
                member_sample_weights,
                corpus.embeddings,
                device,
                member_epochs,
                member_batch_size,
                seed,
                member_loss_reduction,
                member_learning_rate,
            )
        encoded = encode_samples(model, samples, corpus.embeddings, device, member_batch_size, seed)

        action_values, action_targets, action_weights, _action_ids = action_data(labels, encoded, train_ids)
        training_curves["action"] = train_cached_head(
            model.action_head,
            action_values,
            action_targets,
            action_weights,
            device,
            head_epochs,
            seed + 100,
        )
        action_scores = action_probabilities(model, encoded, device)
        safety_values, safety_targets, safety_weights, _safety_keys = safety_data(
            labels,
            samples,
            encoded,
            action_scores,
            train_ids,
            model,
        )
        training_curves["safety"] = train_cached_head(
            model.safety_head,
            safety_values,
            safety_targets,
            safety_weights,
            device,
            safety_epochs,
            seed + 200,
        )
        if staged_checkpoint is not None:
            staged_checkpoint.parent.mkdir(parents=True, exist_ok=True)
            torch.save(
                {name: parameter.detach().cpu() for name, parameter in model.state_dict().items()},
                staged_checkpoint,
            )
            print(f"saved staged checkpoint {staged_checkpoint}", flush=True)

    action_scores = action_probabilities(model, encoded, device)
    if joint_epochs:
        training_curves["joint"] = joint_finetune(
            model,
            labels,
            samples,
            corpus.embeddings,
            encoded,
            train_ids,
            device,
            joint_epochs,
            joint_learning_rate,
            joint_member_weight,
            joint_action_weight,
            joint_safety_weight,
            joint_operation_weight,
            joint_member_scope,
            member_loss_reduction,
            joint_batch_size,
            seed + 300,
        )
        encoded = encode_samples(model, samples, corpus.embeddings, device, member_batch_size, seed)
        action_scores = action_probabilities(model, encoded, device)
    contract = {
        "node_columns": node_columns,
        "node_mean": node_mean,
        "node_std": node_std,
        "edge_mean": edge_mean,
        "edge_std": edge_std,
    }
    return model, encoded, samples, action_scores, contract, training_curves


def binary_metrics(target: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    return {
        "auc": float(roc_auc_score(target, probability)),
        "average_precision": float(average_precision_score(target, probability)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interaction", choices=("early_projection", "late_interaction"), required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--member-predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--report-predictions", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prepared-cache-dir")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--member-epochs", type=int, default=EPOCHS)
    parser.add_argument("--member-batch-size", type=int, default=2)
    parser.add_argument("--member-loss-reduction", choices=("member", "operation"), default="member")
    parser.add_argument("--member-learning-rate", type=float, default=8.0e-4)
    parser.add_argument("--head-epochs", type=int, default=HEAD_EPOCHS)
    parser.add_argument("--safety-epochs", type=int, default=SAFETY_EPOCHS)
    parser.add_argument("--joint-epochs", type=int, default=JOINT_EPOCHS)
    parser.add_argument("--joint-learning-rate", type=float, default=1.0e-4)
    parser.add_argument("--joint-member-weight", type=float, default=1.0)
    parser.add_argument("--joint-action-weight", type=float, default=0.5)
    parser.add_argument("--joint-safety-weight", type=float, default=0.5)
    parser.add_argument("--joint-operation-weight", type=float, default=1.0)
    parser.add_argument("--joint-member-scope", choices=("subset", "all"), default="subset")
    parser.add_argument("--joint-batch-size", type=int, default=4)
    parser.add_argument("--staged-checkpoint-dir")
    parser.add_argument("--staged-final-state")
    parser.add_argument("--member-initial-state")
    parser.add_argument("--fine-tune-member-initial-state", action="store_true")
    parser.add_argument("--exclude-member-label-tier", action="append", default=[])
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()
    if args.folds not in range(6):
        parser.error("--folds must be between 0 and 5")
    if args.joint_epochs < 0:
        parser.error("--joint-epochs must be non-negative")
    if args.joint_batch_size < 1:
        parser.error("--joint-batch-size must be positive")
    if args.member_batch_size < 1:
        parser.error("--member-batch-size must be positive")
    if args.member_learning_rate <= 0.0:
        parser.error("--member-learning-rate must be positive")
    if args.fine_tune_member_initial_state and not args.member_initial_state:
        parser.error("--fine-tune-member-initial-state requires --member-initial-state")
    if args.member_initial_state and args.folds:
        parser.error("--member-initial-state is an all-train initializer and requires --folds 0")
    if args.member_initial_state and args.staged_final_state:
        parser.error("--member-initial-state and --staged-final-state are mutually exclusive")

    interaction: InteractionMode = args.interaction
    if args.device == "auto":
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    print(f"interaction={interaction} device={device}", flush=True)

    prepared_started = time.monotonic()
    labels = pd.read_parquet(args.labels)
    if args.exclude_member_label_tier:
        labels = labels.loc[~labels["member_label_tier"].isin(args.exclude_member_label_tier)].copy()
        if labels.empty:
            parser.error("--exclude-member-label-tier removed every label")
    corpus = FullEmbeddingCorpus(Path(args.corpus).resolve())
    cache = Path(args.prepared_cache_dir).resolve() if args.prepared_cache_dir else None
    frame_cache = cache / "prepared_nodes.parquet" if cache else None
    edge_cache = cache / "prepared_edges.parquet" if cache else None
    if frame_cache is not None and edge_cache is not None and frame_cache.exists() and edge_cache.exists():
        print(f"loading prepared substrate from {cache}", flush=True)
        frame = pd.read_parquet(frame_cache)
        edges = pd.read_parquet(edge_cache)
    else:
        member_predictions = pd.read_parquet(args.member_predictions)
        edge_context = pd.read_parquet(args.edge_context)
        report_predictions = pd.read_parquet(args.report_predictions)
        frame = add_targets(
            build_member_features(labels, member_predictions, edge_context, report_predictions),
            labels,
        )
        frame["member_verdict"] = frame["merge_id"].map(labels.set_index("merge_id")["member_verdict"])
        frame = attach_embedding_rows(frame, labels, corpus)
        edges = prepare_edges(member_predictions, edge_context)
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(frame_cache, index=False)
            edges.to_parquet(edge_cache, index=False)
            (cache / "README.json").write_text(
                json.dumps(
                    {
                        "status": "explicit shared train-only substrate cache",
                        "labels": str(Path(args.labels).resolve()),
                        "member_predictions": str(Path(args.member_predictions).resolve()),
                        "edge_context": str(Path(args.edge_context).resolve()),
                        "report_predictions": str(Path(args.report_predictions).resolve()),
                        "corpus": str(Path(args.corpus).resolve()),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
    active_ids = set(labels["merge_id"].astype(str))
    frame = frame.loc[frame["merge_id"].astype(str).isin(active_ids)].copy()
    edges = edges.loc[edges["merge_id"].astype(str).isin(active_ids)].copy()
    if set(frame["merge_id"].astype(str)) != active_ids or set(edges["merge_id"].astype(str)) != active_ids:
        raise ValueError("prepared substrate does not cover every active label")
    print(f"prepared substrate in {time.monotonic() - prepared_started:.1f}s", flush=True)
    if args.prepare_only:
        if cache is None:
            parser.error("--prepare-only requires --prepared-cache-dir")
        print(
            json.dumps(
                {
                    "status": "prepared train-only integrated shuffler substrate",
                    "labels": len(labels),
                    "nodes": len(frame),
                    "edges": len(edges),
                    "cache": str(cache),
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        return

    groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    if args.folds:
        for fold, (_, test_indices) in enumerate(GroupKFold(5).split(labels, labels["member_verdict"], groups)):
            for merge_id in labels.iloc[test_indices]["merge_id"]:
                fold_by_id[str(merge_id)] = fold

    member_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    fold_training_curves: list[dict[str, Any]] = []
    staged_checkpoint_dir = Path(args.staged_checkpoint_dir).resolve() if args.staged_checkpoint_dir else None
    staged_final_state = Path(args.staged_final_state).resolve() if args.staged_final_state else None
    member_initial_state = Path(args.member_initial_state).resolve() if args.member_initial_state else None
    for fold in range(args.folds):
        model, encoded, samples, action_scores, _contract, fold_curves = train_fold(
            interaction,
            labels,
            frame,
            edges,
            corpus,
            fold_by_id,
            fold,
            device,
            args.member_epochs,
            args.member_batch_size,
            args.member_loss_reduction,
            args.member_learning_rate,
            args.head_epochs,
            args.safety_epochs,
            args.joint_epochs,
            args.joint_learning_rate,
            args.joint_member_weight,
            args.joint_action_weight,
            args.joint_safety_weight,
            args.joint_operation_weight,
            args.joint_member_scope,
            args.joint_batch_size,
            staged_checkpoint_dir,
            staged_final_state,
            member_initial_state,
            args.fine_tune_member_initial_state,
        )
        held_ids = {merge_id for merge_id, value in fold_by_id.items() if value == fold}
        fold_member, fold_action, fold_safety = score_fold(
            model,
            labels,
            samples,
            encoded,
            action_scores,
            held_ids,
            fold,
            device,
        )
        member_rows.extend(fold_member)
        action_rows.extend(fold_action)
        safety_rows.extend(fold_safety)
        fold_training_curves.append({"fold": fold, **fold_curves})
        del model, encoded, samples, action_scores, fold_member, fold_action, fold_safety, fold_curves
        gc.collect()
        if device.type == "mps":
            torch.mps.empty_cache()

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metrics: dict[str, Any] = {
        "status": (
            "component-held-out integrated report shuffler; train shard only"
            if args.folds
            else "all-train integrated report shuffler fit; no OOF scoring"
        ),
        "interaction": interaction,
        "folds_scored": args.folds,
        "training_protocol": {
            "member_supervision": (
                "warm-started member initializer fine-tuned on active labels"
                if member_initial_state and args.fine_tune_member_initial_state
                else "frozen member initializer; no member retraining"
                if member_initial_state
                else "merge_subset operations only"
            ),
            "member_epochs": (
                0 if member_initial_state and not args.fine_tune_member_initial_state else args.member_epochs
            ),
            "member_initial_state": str(member_initial_state) if member_initial_state else None,
            "member_normalization": "inherited from member initializer"
            if member_initial_state
            else "active train labels",
            "member_batch_size": args.member_batch_size,
            "member_learning_rate": args.member_learning_rate,
            "member_batching": "two-dimensional log-shape buckets over left and right report sizes",
            "member_weighting": (
                "operation confidence multiplied by member-label-tier trust, then normalized within each operation"
                if args.member_loss_reduction == "operation"
                else "operation confidence multiplied by member-label-tier trust, repeated per member"
            ),
            "member_loss_reduction": args.member_loss_reduction,
            "action_supervision": "all exact operations with frozen member encoder",
            "action_epochs": args.head_epochs,
            "safety_supervision": "two-sided on-policy masks across the fixed member threshold grid",
            "safety_epochs": args.safety_epochs,
            "joint_epochs": args.joint_epochs,
            "joint_learning_rate": args.joint_learning_rate,
            "joint_member_weight": args.joint_member_weight,
            "joint_action_weight": args.joint_action_weight,
            "joint_safety_weight": args.joint_safety_weight,
            "joint_operation_weight": args.joint_operation_weight,
            "joint_member_scope": args.joint_member_scope,
            "joint_batch_size": args.joint_batch_size,
            "joint_safety_targets": "staged on-policy masks, fixed during each fine-tune",
            "joint_threshold_schedule": "one threshold per operation and epoch, rotating over the fixed grid",
            "external_report_gate_features": False,
            "excluded_member_label_tiers": sorted(args.exclude_member_label_tier),
        },
        "train_test_policy": "train labels only; validation A and B not read",
        "metric_scope": (
            "model-local folds; upstream train-operation features can overlap and these metrics are not "
            "end-to-end OOF calibration"
        ),
        "fold_training_curves": fold_training_curves,
    }
    if args.folds:
        member_oof = pd.DataFrame(member_rows)
        action_oof = pd.DataFrame(action_rows)
        safety_oof = pd.DataFrame(safety_rows)
        member_oof.to_parquet(output / "integrated_member_oof.parquet", index=False)
        action_oof.to_parquet(output / "integrated_action_oof.parquet", index=False)
        safety_oof.to_parquet(output / "integrated_safety_oof.parquet", index=False)

        subset_ids = set(labels.loc[labels["member_verdict"] == "merge_subset", "merge_id"].astype(str))
        subset_member = member_oof.loc[member_oof["merge_id"].isin(subset_ids)]
        eligible_safety = safety_oof.loc[safety_oof["two_sided"]]
        metrics.update(
            {
                "member": binary_metrics(
                    subset_member["target"].to_numpy(np.int8),
                    subset_member["probability:member"].to_numpy(np.float64),
                ),
                "action": binary_metrics(
                    action_oof["target"].to_numpy(np.int8),
                    action_oof["probability:action"].to_numpy(np.float64),
                ),
                "safety": binary_metrics(
                    eligible_safety["target"].to_numpy(np.int8),
                    eligible_safety["probability:safety"].to_numpy(np.float64),
                ),
                "counts": {
                    "member_rows": len(member_oof),
                    "subset_member_rows": len(subset_member),
                    "action_rows": len(action_oof),
                    "safety_rows": len(safety_oof),
                    "two_sided_safety_rows": len(eligible_safety),
                },
            }
        )

    if args.folds in {0, 5}:
        final_model, _encoded, _samples, _scores, contract, final_curves = train_fold(
            interaction,
            labels,
            frame,
            edges,
            corpus,
            fold_by_id,
            None,
            device,
            args.member_epochs,
            args.member_batch_size,
            args.member_loss_reduction,
            args.member_learning_rate,
            args.head_epochs,
            args.safety_epochs,
            args.joint_epochs,
            args.joint_learning_rate,
            args.joint_member_weight,
            args.joint_action_weight,
            args.joint_safety_weight,
            args.joint_operation_weight,
            args.joint_member_scope,
            args.joint_batch_size,
            staged_checkpoint_dir,
            staged_final_state,
            member_initial_state,
            args.fine_tune_member_initial_state,
        )
        metrics["final_training_curves"] = final_curves
        metrics["parameters"] = sum(parameter.numel() for parameter in final_model.parameters())
        torch.save(
            {
                "schema_version": 1,
                "model_family": "integrated_bipartite_report_shuffler",
                "interaction": interaction,
                "state_dict": final_model.cpu().state_dict(),
                "architecture": {
                    "embedding_dims": EMBEDDING_DIMS,
                    "hidden": HIDDEN,
                    "layers": LAYERS,
                    "member_thresholds": MEMBER_THRESHOLDS,
                },
                **contract,
            },
            output / "integrated_report_shuffler.pt",
        )
    (output / "integrated_report_shuffler_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
