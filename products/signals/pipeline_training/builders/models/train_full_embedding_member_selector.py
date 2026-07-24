"""Train full-vector Report 13 contextual and bipartite member selectors.

The repaired Report 13 models see 51 engineered node summaries. This challenger
keeps those summaries and adds a shared supervised projection of every complete
1,536-coordinate signal embedding. Embeddings remain de-duplicated in the
corpus table and are gathered only for the active minibatch.
"""

# ruff: noqa: T201

from __future__ import annotations

import json
import random
import argparse
from pathlib import Path
from typing import Any, Literal

import numpy as np
import torch
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from torch import nn
from torch.utils.data import DataLoader, Dataset
from train_bipartite_member_selector import EDGE_FEATURES, prepare_edges
from train_member_selector import add_targets, build_member_features
from train_merge_proposer_safety import component_groups

SEED = 47
EMBEDDING_DIMS = 1536
HIDDEN = 128
HEADS = 4
LAYERS = 2
EPOCHS = 35
Architecture = Literal["contextual", "bipartite"]
Variant = Literal["wide", "compact-gated"]


class FullEmbeddingCorpus:
    def __init__(self, corpus: Path) -> None:
        signals = [json.loads(line) for line in (corpus / "signals.jsonl").open() if line.strip()]
        self.index = {str(signal["id"]): row for row, signal in enumerate(signals)}
        raw = np.load(corpus / "embeddings.npy").astype(np.float32, copy=False)
        if len(raw) != len(signals) or raw.shape[1] != EMBEDDING_DIMS:
            raise ValueError(f"unexpected embedding table shape: {raw.shape}")
        norms = np.linalg.norm(raw.astype(np.float64), axis=1, keepdims=True)
        self.embeddings = (raw.astype(np.float64) / np.maximum(norms, 1.0e-12)).astype(np.float32)


class FullMemberSetSelector(nn.Module):
    def __init__(self, input_features: int, variant: Variant = "wide") -> None:
        super().__init__()
        self.variant = variant
        hidden = HIDDEN if variant == "wide" else 64
        self.hidden = hidden
        self.feature_projection = nn.Linear(input_features, hidden)
        self.embedding_projection = nn.Sequential(
            nn.Linear(EMBEDDING_DIMS, hidden, bias=False),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(0.10),
        )
        self.embedding_gate = nn.Parameter(torch.zeros(())) if variant == "compact-gated" else None
        self.side_embedding = nn.Embedding(2, hidden)
        self.input_norm = nn.LayerNorm(hidden) if variant == "wide" else nn.Identity()
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden,
            nhead=HEADS,
            dim_feedforward=hidden * 2,
            dropout=0.10,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=LAYERS, enable_nested_tensor=False)
        self.output = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 1))

    def forward(
        self,
        features: torch.Tensor,
        embeddings: torch.Tensor,
        sides: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        embedding_hidden = self.embedding_projection(embeddings)
        if self.embedding_gate is not None:
            embedding_hidden = self.embedding_gate * embedding_hidden
        hidden = self.input_norm(self.feature_projection(features) + embedding_hidden + self.side_embedding(sides))
        hidden = self.encoder(hidden, src_key_padding_mask=~mask)
        return self.output(hidden).squeeze(-1)


class FullBipartiteBlock(nn.Module):
    def __init__(self, edge_features: int, hidden: int) -> None:
        super().__init__()
        self.hidden = hidden
        self.query = nn.Linear(hidden, hidden)
        self.key = nn.Linear(hidden, hidden)
        self.value = nn.Linear(hidden, hidden)
        edge_hidden = 64 if hidden == HIDDEN else 32
        self.edge_bias = nn.Sequential(nn.Linear(edge_features, edge_hidden), nn.GELU(), nn.Linear(edge_hidden, 1))
        self.left_norm = nn.LayerNorm(hidden)
        self.right_norm = nn.LayerNorm(hidden)
        self.left_ff = nn.Sequential(nn.Linear(hidden, hidden * 2), nn.GELU(), nn.Linear(hidden * 2, hidden))
        self.right_ff = nn.Sequential(nn.Linear(hidden, hidden * 2), nn.GELU(), nn.Linear(hidden * 2, hidden))
        self.left_ff_norm = nn.LayerNorm(hidden)
        self.right_ff_norm = nn.LayerNorm(hidden)

    @staticmethod
    def masked_softmax(scores: torch.Tensor, mask: torch.Tensor, dimension: int) -> torch.Tensor:
        weights = torch.softmax(scores.masked_fill(~mask, -1.0e4), dim=dimension)
        weights = weights * mask
        return weights / weights.sum(dim=dimension, keepdim=True).clamp_min(1.0e-6)

    def forward(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        scores = torch.einsum("blh,brh->blr", self.query(left), self.key(right)) / self.hidden**0.5
        scores = scores + self.edge_bias(edge_features).squeeze(-1)
        left_weights = self.masked_softmax(scores, edge_mask, 2)
        right_weights = self.masked_softmax(scores, edge_mask, 1)
        left_message = torch.einsum("blr,brh->blh", left_weights, self.value(right))
        right_message = torch.einsum("blr,blh->brh", right_weights, self.value(left))
        left = self.left_norm(left + left_message)
        right = self.right_norm(right + right_message)
        left = self.left_ff_norm(left + self.left_ff(left))
        right = self.right_ff_norm(right + self.right_ff(right))
        return left, right


class FullBipartiteMemberSelector(nn.Module):
    def __init__(self, node_features: int, edge_features: int, variant: Variant = "wide") -> None:
        super().__init__()
        self.variant = variant
        hidden = HIDDEN if variant == "wide" else 64
        self.hidden = hidden
        self.node_projection = nn.Linear(node_features, hidden)
        self.embedding_projection = nn.Sequential(
            nn.Linear(EMBEDDING_DIMS, hidden, bias=False),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(0.10),
        )
        self.embedding_gate = nn.Parameter(torch.zeros(())) if variant == "compact-gated" else None
        self.side_embedding = nn.Embedding(2, hidden)
        self.input_norm = nn.LayerNorm(hidden) if variant == "wide" else nn.Identity()
        self.blocks = nn.ModuleList(FullBipartiteBlock(edge_features, hidden) for _ in range(LAYERS))
        self.output = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 1))

    def forward(
        self,
        left_features: torch.Tensor,
        right_features: torch.Tensor,
        left_embeddings: torch.Tensor,
        right_embeddings: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        left_embedding_hidden = self.embedding_projection(left_embeddings)
        right_embedding_hidden = self.embedding_projection(right_embeddings)
        if self.embedding_gate is not None:
            left_embedding_hidden = self.embedding_gate * left_embedding_hidden
            right_embedding_hidden = self.embedding_gate * right_embedding_hidden
        left = self.input_norm(
            self.node_projection(left_features) + left_embedding_hidden + self.side_embedding.weight[1]
        )
        right = self.input_norm(
            self.node_projection(right_features) + right_embedding_hidden + self.side_embedding.weight[0]
        )
        for block in self.blocks:
            left, right = block(left, right, edge_features, edge_mask)
        return self.output(left).squeeze(-1), self.output(right).squeeze(-1)


class SampleDataset(Dataset[dict[str, Any]]):
    def __init__(self, samples: list[dict[str, Any]]) -> None:
        self.samples = samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.samples[index]


def attach_embedding_rows(
    frame: pd.DataFrame,
    labels: pd.DataFrame,
    corpus: FullEmbeddingCorpus,
) -> pd.DataFrame:
    inventories = {
        str(row.merge_id): (
            [str(value) for value in json.loads(row.left_members)],
            [str(value) for value in json.loads(row.right_members)],
        )
        for row in labels.itertuples(index=False)
    }
    embedding_rows = []
    for row in frame.itertuples(index=False):
        inventory = inventories[str(row.merge_id)][0 if float(row.side_left) == 1.0 else 1]
        document_id = inventory[int(row.member_index)]
        if document_id not in corpus.index:
            raise KeyError(f"member {document_id} is absent from the embedding corpus")
        embedding_rows.append(corpus.index[document_id])
    output = frame.copy()
    output["embedding_row"] = np.asarray(embedding_rows, dtype=np.int32)
    return output


def make_contextual_samples(
    frame: pd.DataFrame,
    feature_columns: list[str],
    mean: np.ndarray,
    std: np.ndarray,
    fold_by_id: dict[str, int],
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for merge_id, group in frame.groupby("merge_id", sort=False):
        ordered = group.sort_values(["side_left", "member_index"], ascending=[False, True])
        values = ordered[feature_columns].to_numpy(dtype=np.float32)
        samples.append(
            {
                "merge_id": str(merge_id),
                "fold": fold_by_id[str(merge_id)],
                "features": ((values - mean) / std).astype(np.float32),
                "embedding_rows": ordered["embedding_row"].to_numpy(dtype=np.int32),
                "sides": ordered["side_left"].to_numpy(dtype=np.int64),
                "member_indices": ordered["member_index"].to_numpy(dtype=np.int64),
                "target": ordered["target"].to_numpy(dtype=np.float32),
                "member_verdict": str(ordered["member_verdict"].iloc[0]),
            }
        )
    return samples


def collate_contextual(samples: list[dict[str, Any]], embeddings: np.ndarray) -> dict[str, Any]:
    maximum = max(len(sample["target"]) for sample in samples)
    features = np.zeros((len(samples), maximum, samples[0]["features"].shape[1]), dtype=np.float32)
    content = np.zeros((len(samples), maximum, EMBEDDING_DIMS), dtype=np.float32)
    sides = np.zeros((len(samples), maximum), dtype=np.int64)
    targets = np.zeros((len(samples), maximum), dtype=np.float32)
    mask = np.zeros((len(samples), maximum), dtype=bool)
    for index, sample in enumerate(samples):
        count = len(sample["target"])
        features[index, :count] = sample["features"]
        content[index, :count] = embeddings[sample["embedding_rows"]]
        sides[index, :count] = sample["sides"]
        targets[index, :count] = sample["target"]
        mask[index, :count] = True
    return {
        "merge_ids": [sample["merge_id"] for sample in samples],
        "features": torch.from_numpy(features),
        "embeddings": torch.from_numpy(content),
        "sides": torch.from_numpy(sides),
        "targets": torch.from_numpy(targets),
        "mask": torch.from_numpy(mask),
    }


def make_bipartite_samples(
    frame: pd.DataFrame,
    edges: pd.DataFrame,
    node_columns: list[str],
    node_mean: np.ndarray,
    node_std: np.ndarray,
    edge_mean: np.ndarray,
    edge_std: np.ndarray,
    fold_by_id: dict[str, int],
) -> list[dict[str, Any]]:
    edge_groups = {str(merge_id): group for merge_id, group in edges.groupby("merge_id", sort=False)}
    samples: list[dict[str, Any]] = []
    for merge_id, group in frame.groupby("merge_id", sort=False):
        merge_id = str(merge_id)
        left = group.loc[group["side_left"] == 1.0].sort_values("member_index")
        right = group.loc[group["side_left"] == 0.0].sort_values("member_index")
        left_positions = {int(value): index for index, value in enumerate(left["member_index"])}
        right_positions = {int(value): index for index, value in enumerate(right["member_index"])}
        matrix = np.zeros((len(left), len(right), len(EDGE_FEATURES)), dtype=np.float32)
        mask = np.zeros((len(left), len(right)), dtype=bool)
        edge_columns = ["left_member_index", "right_member_index", *EDGE_FEATURES]
        for values in edge_groups[merge_id][edge_columns].itertuples(index=False, name=None):
            left_position = left_positions[int(values[0])]
            right_position = right_positions[int(values[1])]
            matrix[left_position, right_position] = values[2:]
            mask[left_position, right_position] = True
        normalized = np.zeros_like(matrix)
        normalized[mask] = ((matrix[mask] - edge_mean) / edge_std).astype(np.float32)
        samples.append(
            {
                "merge_id": merge_id,
                "fold": fold_by_id[merge_id],
                "left_features": ((left[node_columns].to_numpy(np.float32) - node_mean) / node_std).astype(np.float32),
                "right_features": ((right[node_columns].to_numpy(np.float32) - node_mean) / node_std).astype(
                    np.float32
                ),
                "left_embedding_rows": left["embedding_row"].to_numpy(dtype=np.int32),
                "right_embedding_rows": right["embedding_row"].to_numpy(dtype=np.int32),
                "edge_features": normalized,
                "edge_mask": mask,
                "left_indices": left["member_index"].to_numpy(np.int64),
                "right_indices": right["member_index"].to_numpy(np.int64),
                "left_target": left["target"].to_numpy(np.float32),
                "right_target": right["target"].to_numpy(np.float32),
                "member_verdict": str(left["member_verdict"].iloc[0]),
            }
        )
    return samples


def collate_bipartite(samples: list[dict[str, Any]], embeddings: np.ndarray) -> dict[str, Any]:
    batch = len(samples)
    maximum_left = max(len(sample["left_target"]) for sample in samples)
    maximum_right = max(len(sample["right_target"]) for sample in samples)
    node_count = samples[0]["left_features"].shape[1]
    edge_count = samples[0]["edge_features"].shape[2]
    left_features = np.zeros((batch, maximum_left, node_count), dtype=np.float32)
    right_features = np.zeros((batch, maximum_right, node_count), dtype=np.float32)
    left_embeddings = np.zeros((batch, maximum_left, EMBEDDING_DIMS), dtype=np.float32)
    right_embeddings = np.zeros((batch, maximum_right, EMBEDDING_DIMS), dtype=np.float32)
    edge_features = np.zeros((batch, maximum_left, maximum_right, edge_count), dtype=np.float32)
    edge_mask = np.zeros((batch, maximum_left, maximum_right), dtype=bool)
    left_target = np.zeros((batch, maximum_left), dtype=np.float32)
    right_target = np.zeros((batch, maximum_right), dtype=np.float32)
    left_mask = np.zeros((batch, maximum_left), dtype=bool)
    right_mask = np.zeros((batch, maximum_right), dtype=bool)
    for index, sample in enumerate(samples):
        left_count = len(sample["left_target"])
        right_count = len(sample["right_target"])
        left_features[index, :left_count] = sample["left_features"]
        right_features[index, :right_count] = sample["right_features"]
        left_embeddings[index, :left_count] = embeddings[sample["left_embedding_rows"]]
        right_embeddings[index, :right_count] = embeddings[sample["right_embedding_rows"]]
        edge_features[index, :left_count, :right_count] = sample["edge_features"]
        edge_mask[index, :left_count, :right_count] = sample["edge_mask"]
        left_target[index, :left_count] = sample["left_target"]
        right_target[index, :right_count] = sample["right_target"]
        left_mask[index, :left_count] = True
        right_mask[index, :right_count] = True
    return {
        "merge_ids": [sample["merge_id"] for sample in samples],
        "left_features": torch.from_numpy(left_features),
        "right_features": torch.from_numpy(right_features),
        "left_embeddings": torch.from_numpy(left_embeddings),
        "right_embeddings": torch.from_numpy(right_embeddings),
        "edge_features": torch.from_numpy(edge_features),
        "edge_mask": torch.from_numpy(edge_mask),
        "left_target": torch.from_numpy(left_target),
        "right_target": torch.from_numpy(right_target),
        "left_mask": torch.from_numpy(left_mask),
        "right_mask": torch.from_numpy(right_mask),
    }


def contextual_loader(
    samples: list[dict[str, Any]], embeddings: np.ndarray, shuffle: bool, batch_size: int = 4
) -> DataLoader[dict[str, Any]]:
    return DataLoader(
        SampleDataset(samples),
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=lambda batch: collate_contextual(batch, embeddings),
    )


def bipartite_loader(
    samples: list[dict[str, Any]], embeddings: np.ndarray, shuffle: bool, batch_size: int = 2
) -> DataLoader[dict[str, Any]]:
    return DataLoader(
        SampleDataset(samples),
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=lambda batch: collate_bipartite(batch, embeddings),
    )


def train_contextual(
    samples: list[dict[str, Any]],
    feature_count: int,
    embeddings: np.ndarray,
    device: torch.device,
    variant: Variant = "wide",
) -> FullMemberSetSelector:
    seed = SEED if variant == "wide" else 17
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = FullMemberSetSelector(feature_count, variant).to(device)
    learning_rate = 8.0e-4 if variant == "wide" else 1.0e-3
    weight_decay = 5.0e-4 if variant == "wide" else 2.0e-4
    batch_size = 4 if variant == "wide" else 8
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    positive = sum(float(sample["target"].sum()) for sample in samples)
    total = sum(len(sample["target"]) for sample in samples)
    positive_weight = torch.tensor((total - positive) / max(positive, 1.0), device=device)
    for epoch in range(EPOCHS):
        losses = []
        model.train()
        for batch in contextual_loader(samples, embeddings, True, batch_size):
            features = batch["features"].to(device)
            content = batch["embeddings"].to(device)
            sides = batch["sides"].to(device)
            targets = batch["targets"].to(device)
            mask = batch["mask"].to(device)
            logits = model(features, content, sides, mask)
            active_logits = logits[mask]
            active_targets = targets[mask]
            bce = nn.functional.binary_cross_entropy_with_logits(
                active_logits, active_targets, pos_weight=positive_weight
            )
            probabilities = torch.sigmoid(active_logits)
            dice = 1.0 - (2.0 * (probabilities * active_targets).sum() + 1.0) / (
                probabilities.sum() + active_targets.sum() + 1.0
            )
            loss = bce + 0.25 * dice
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch in {0, 9, 19, 29, EPOCHS - 1}:
            print(f"epoch {epoch + 1}/{EPOCHS}: loss={np.mean(losses):.5f}", flush=True)
    return model


def predict_contextual(
    model: FullMemberSetSelector,
    samples: list[dict[str, Any]],
    embeddings: np.ndarray,
    device: torch.device,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sample_by_id = {sample["merge_id"]: sample for sample in samples}
    model.eval()
    with torch.no_grad():
        for batch in contextual_loader(samples, embeddings, False):
            logits = model(
                batch["features"].to(device),
                batch["embeddings"].to(device),
                batch["sides"].to(device),
                batch["mask"].to(device),
            ).cpu()
            for batch_index, merge_id in enumerate(batch["merge_ids"]):
                sample = sample_by_id[merge_id]
                count = len(sample["target"])
                probabilities = torch.sigmoid(logits[batch_index, :count]).numpy()
                for member_index, side, target, probability in zip(
                    sample["member_indices"],
                    sample["sides"],
                    sample["target"],
                    probabilities,
                    strict=True,
                ):
                    rows.append(
                        {
                            "merge_id": merge_id,
                            "side_left": float(side),
                            "member_index": int(member_index),
                            "target": int(target),
                            f"probability:contextual-full-embedding-{model.variant}": float(probability),
                        }
                    )
    return rows


def train_bipartite(
    samples: list[dict[str, Any]],
    node_count: int,
    embeddings: np.ndarray,
    device: torch.device,
    variant: Variant = "wide",
) -> FullBipartiteMemberSelector:
    seed = SEED if variant == "wide" else 19
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = FullBipartiteMemberSelector(node_count, len(EDGE_FEATURES), variant).to(device)
    weight_decay = 5.0e-4 if variant == "wide" else 2.0e-4
    batch_size = 2 if variant == "wide" else 4
    optimizer = torch.optim.AdamW(model.parameters(), lr=8.0e-4, weight_decay=weight_decay)
    positive = sum(float(sample["left_target"].sum() + sample["right_target"].sum()) for sample in samples)
    total = sum(len(sample["left_target"]) + len(sample["right_target"]) for sample in samples)
    positive_weight = torch.tensor((total - positive) / max(positive, 1.0), device=device)
    for epoch in range(EPOCHS):
        losses = []
        model.train()
        for batch in bipartite_loader(samples, embeddings, True, batch_size):
            left_logits, right_logits = model(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["left_embeddings"].to(device),
                batch["right_embeddings"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            logits = torch.cat(
                [left_logits[batch["left_mask"].to(device)], right_logits[batch["right_mask"].to(device)]]
            )
            targets = torch.cat(
                [
                    batch["left_target"][batch["left_mask"]],
                    batch["right_target"][batch["right_mask"]],
                ]
            ).to(device)
            bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=positive_weight)
            probabilities = torch.sigmoid(logits)
            dice = 1.0 - (2.0 * (probabilities * targets).sum() + 1.0) / (probabilities.sum() + targets.sum() + 1.0)
            loss = bce + 0.25 * dice
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch in {0, 9, 19, 29, EPOCHS - 1}:
            print(f"epoch {epoch + 1}/{EPOCHS}: loss={np.mean(losses):.5f}", flush=True)
    return model


def predict_bipartite(
    model: FullBipartiteMemberSelector,
    samples: list[dict[str, Any]],
    embeddings: np.ndarray,
    device: torch.device,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sample_by_id = {sample["merge_id"]: sample for sample in samples}
    model.eval()
    with torch.no_grad():
        for batch in bipartite_loader(samples, embeddings, False):
            left_logits, right_logits = model(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["left_embeddings"].to(device),
                batch["right_embeddings"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            left_probabilities = torch.sigmoid(left_logits).cpu().numpy()
            right_probabilities = torch.sigmoid(right_logits).cpu().numpy()
            for batch_index, merge_id in enumerate(batch["merge_ids"]):
                sample = sample_by_id[merge_id]
                for side_left, indices, targets, probabilities in (
                    (1.0, sample["left_indices"], sample["left_target"], left_probabilities[batch_index]),
                    (0.0, sample["right_indices"], sample["right_target"], right_probabilities[batch_index]),
                ):
                    for member_index, target, probability in zip(indices, targets, probabilities, strict=False):
                        rows.append(
                            {
                                "merge_id": merge_id,
                                "side_left": side_left,
                                "member_index": int(member_index),
                                "target": int(target),
                                f"probability:bipartite-full-embedding-{model.variant}": float(probability),
                            }
                        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=("contextual", "bipartite"), required=True)
    parser.add_argument("--variant", choices=("wide", "compact-gated"), default="wide")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--member-predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--report-predictions", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    architecture: Architecture = args.architecture
    variant: Variant = args.variant
    device = torch.device("mps" if args.device == "auto" and torch.backends.mps.is_available() else "cpu")
    if args.device not in {"auto", "cpu"}:
        device = torch.device(args.device)
    print(f"architecture={architecture}, variant={variant}, device={device}", flush=True)

    labels = pd.read_parquet(args.labels)
    frame = add_targets(
        build_member_features(
            labels,
            pd.read_parquet(args.member_predictions),
            pd.read_parquet(args.edge_context),
            pd.read_parquet(args.report_predictions),
        ),
        labels,
    )
    frame["member_verdict"] = frame["merge_id"].map(labels.set_index("merge_id")["member_verdict"])
    corpus = FullEmbeddingCorpus(Path(args.corpus).resolve())
    frame = attach_embedding_rows(frame, labels, corpus)
    excluded = {"merge_id", "member_index", "embedding_row", "target", "member_verdict"}
    node_columns = [column for column in frame if column not in excluded]

    groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    for fold, (_, test_indices) in enumerate(GroupKFold(5).split(labels, labels["member_verdict"], groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    subset_ids = set(labels.loc[labels["member_verdict"] == "merge_subset", "merge_id"].astype(str))
    edges = prepare_edges(pd.read_parquet(args.member_predictions), pd.read_parquet(args.edge_context))
    oof_rows: list[dict[str, Any]] = []

    for fold in range(5):
        train_ids = {merge_id for merge_id in subset_ids if fold_by_id[merge_id] != fold}
        node_train = frame.loc[frame["merge_id"].astype(str).isin(train_ids), node_columns]
        node_mean = node_train.mean().to_numpy(np.float32)
        node_std = node_train.std().clip(lower=1.0e-5).to_numpy(np.float32)
        if architecture == "contextual":
            samples = make_contextual_samples(frame, node_columns, node_mean, node_std, fold_by_id)
            train_samples = [sample for sample in samples if sample["merge_id"] in train_ids]
            test_samples = [sample for sample in samples if sample["fold"] == fold]
            print(f"fold {fold}: train={len(train_samples)} score={len(test_samples)}", flush=True)
            model = train_contextual(train_samples, len(node_columns), corpus.embeddings, device, variant)
            oof_rows.extend(predict_contextual(model, test_samples, corpus.embeddings, device))
        else:
            edge_train = edges.loc[edges["merge_id"].astype(str).isin(train_ids), list(EDGE_FEATURES)]
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
            train_samples = [sample for sample in samples if sample["merge_id"] in train_ids]
            test_samples = [sample for sample in samples if sample["fold"] == fold]
            print(f"fold {fold}: train={len(train_samples)} score={len(test_samples)}", flush=True)
            model = train_bipartite(train_samples, len(node_columns), corpus.embeddings, device, variant)
            oof_rows.extend(predict_bipartite(model, test_samples, corpus.embeddings, device))

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    oof = pd.DataFrame(oof_rows)
    probability = (
        f"probability:contextual-full-embedding-{variant}"
        if architecture == "contextual"
        else f"probability:bipartite-full-embedding-{variant}"
    )
    oof.to_parquet(output / f"{architecture}_full_embedding_{variant}_oof.parquet", index=False)
    subset_oof = oof.loc[oof["merge_id"].isin(subset_ids)]
    metrics = {
        "status": "five-fold full-embedding member selector; exact subset rows train",
        "architecture": {
            "family": architecture,
            "variant": variant,
            "embedding_dims": EMBEDDING_DIMS,
            "hidden": model.hidden,
            "heads": HEADS if architecture == "contextual" else None,
            "layers": LAYERS,
            "epochs": EPOCHS,
        },
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "subset_member_rows": len(subset_oof),
        "auc": float(roc_auc_score(subset_oof["target"], subset_oof[probability])),
        "average_precision": float(average_precision_score(subset_oof["target"], subset_oof[probability])),
        "train_test_policy": "train labels only; validation A and B not read",
    }

    node_train = frame.loc[frame["merge_id"].astype(str).isin(subset_ids), node_columns]
    node_mean = node_train.mean().to_numpy(np.float32)
    node_std = node_train.std().clip(lower=1.0e-5).to_numpy(np.float32)
    if architecture == "contextual":
        final_samples = make_contextual_samples(frame, node_columns, node_mean, node_std, fold_by_id)
        final_train = [sample for sample in final_samples if sample["merge_id"] in subset_ids]
        final_model = train_contextual(final_train, len(node_columns), corpus.embeddings, device, variant)
        state = {
            "state_dict": final_model.state_dict(),
            "node_columns": node_columns,
            "node_mean": node_mean,
            "node_std": node_std,
            "architecture": metrics["architecture"],
        }
    else:
        edge_train = edges.loc[edges["merge_id"].astype(str).isin(subset_ids), list(EDGE_FEATURES)]
        edge_mean = edge_train.mean().to_numpy(np.float32)
        edge_std = edge_train.std().clip(lower=1.0e-5).to_numpy(np.float32)
        final_samples = make_bipartite_samples(
            frame,
            edges,
            node_columns,
            node_mean,
            node_std,
            edge_mean,
            edge_std,
            fold_by_id,
        )
        final_train = [sample for sample in final_samples if sample["merge_id"] in subset_ids]
        final_model = train_bipartite(final_train, len(node_columns), corpus.embeddings, device, variant)
        state = {
            "state_dict": final_model.state_dict(),
            "node_columns": node_columns,
            "node_mean": node_mean,
            "node_std": node_std,
            "edge_mean": edge_mean,
            "edge_std": edge_std,
            "architecture": metrics["architecture"],
        }
    torch.save(state, output / f"{architecture}_full_embedding_{variant}.pt")
    (output / f"{architecture}_full_embedding_{variant}_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(metrics, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
