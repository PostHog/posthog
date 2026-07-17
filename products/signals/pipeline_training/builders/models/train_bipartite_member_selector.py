"""Train an edge-aware bipartite neural selector for exact subset members."""

# ruff: noqa: T201

from __future__ import annotations

import json
import random
import argparse
from pathlib import Path
from typing import Any

import numpy as np
import torch
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from torch import nn
from torch.utils.data import DataLoader, Dataset
from train_member_selector import add_targets, build_member_features
from train_merge_proposer_safety import component_groups

SEED = 19
HIDDEN = 64
LAYERS = 2
EPOCHS = 35
BATCH_SIZE = 4

EDGE_FEATURES = (
    "probability:direct-logistic",
    "probability:direct-hgb-d2",
    "probability:direct-hgb-d3",
    "probability:context-logistic",
    "probability:context-hgb-d2",
    "probability:context-hgb-d3",
    "probability:rich-direct-hgb-d2",
    "probability:rich-direct-hgb-d3",
    "probability:rich-context-logistic",
    "pair_raw",
    "pair_cal",
    "embedding_cosine",
    "left_rank_filled",
    "right_rank_filled",
    "mutual_top_k_float",
)


class BipartiteBlock(nn.Module):
    def __init__(self, edge_features: int) -> None:
        super().__init__()
        self.query = nn.Linear(HIDDEN, HIDDEN)
        self.key = nn.Linear(HIDDEN, HIDDEN)
        self.value = nn.Linear(HIDDEN, HIDDEN)
        self.edge_bias = nn.Sequential(nn.Linear(edge_features, 32), nn.GELU(), nn.Linear(32, 1))
        self.left_norm = nn.LayerNorm(HIDDEN)
        self.right_norm = nn.LayerNorm(HIDDEN)
        self.left_ff = nn.Sequential(nn.Linear(HIDDEN, HIDDEN * 2), nn.GELU(), nn.Linear(HIDDEN * 2, HIDDEN))
        self.right_ff = nn.Sequential(nn.Linear(HIDDEN, HIDDEN * 2), nn.GELU(), nn.Linear(HIDDEN * 2, HIDDEN))
        self.left_ff_norm = nn.LayerNorm(HIDDEN)
        self.right_ff_norm = nn.LayerNorm(HIDDEN)

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
        scores = torch.einsum("blh,brh->blr", self.query(left), self.key(right)) / HIDDEN**0.5
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


class BipartiteMemberSelector(nn.Module):
    def __init__(self, node_features: int, edge_features: int) -> None:
        super().__init__()
        self.node_projection = nn.Linear(node_features, HIDDEN)
        self.side_embedding = nn.Embedding(2, HIDDEN)
        self.blocks = nn.ModuleList(BipartiteBlock(edge_features) for _ in range(LAYERS))
        self.output = nn.Sequential(nn.LayerNorm(HIDDEN), nn.Linear(HIDDEN, 1))

    def forward(
        self,
        left_features: torch.Tensor,
        right_features: torch.Tensor,
        edge_features: torch.Tensor,
        edge_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        left = self.node_projection(left_features) + self.side_embedding.weight[1]
        right = self.node_projection(right_features) + self.side_embedding.weight[0]
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


def collate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    batch = len(samples)
    max_left = max(len(sample["left_target"]) for sample in samples)
    max_right = max(len(sample["right_target"]) for sample in samples)
    node_count = samples[0]["left_features"].shape[1]
    edge_count = samples[0]["edge_features"].shape[2]
    left_features = np.zeros((batch, max_left, node_count), dtype=np.float32)
    right_features = np.zeros((batch, max_right, node_count), dtype=np.float32)
    edge_features = np.zeros((batch, max_left, max_right, edge_count), dtype=np.float32)
    edge_mask = np.zeros((batch, max_left, max_right), dtype=bool)
    left_target = np.zeros((batch, max_left), dtype=np.float32)
    right_target = np.zeros((batch, max_right), dtype=np.float32)
    left_mask = np.zeros((batch, max_left), dtype=bool)
    right_mask = np.zeros((batch, max_right), dtype=bool)
    for index, sample in enumerate(samples):
        left_count = len(sample["left_target"])
        right_count = len(sample["right_target"])
        left_features[index, :left_count] = sample["left_features"]
        right_features[index, :right_count] = sample["right_features"]
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
        "edge_features": torch.from_numpy(edge_features),
        "edge_mask": torch.from_numpy(edge_mask),
        "left_target": torch.from_numpy(left_target),
        "right_target": torch.from_numpy(right_target),
        "left_mask": torch.from_numpy(left_mask),
        "right_mask": torch.from_numpy(right_mask),
    }


def prepare_edges(member_predictions: pd.DataFrame, edge_context: pd.DataFrame) -> pd.DataFrame:
    context = edge_context[
        [
            "merge_id",
            "left_member_index",
            "right_member_index",
            "pair_raw",
            "pair_cal",
            "embedding_cosine",
            "left_rank",
            "right_rank",
            "mutual_top_k",
        ]
    ]
    edges = member_predictions.merge(
        context,
        on=["merge_id", "left_member_index", "right_member_index"],
        how="left",
        validate="one_to_one",
    )
    edges["left_rank_filled"] = edges["left_rank"].fillna(25).astype(float)
    edges["right_rank_filled"] = edges["right_rank"].fillna(25).astype(float)
    edges["mutual_top_k_float"] = edges["mutual_top_k"].fillna(False).astype(float)
    return edges


def make_samples(
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
        matrix[mask] = (matrix[mask] - edge_mean) / edge_std
        samples.append(
            {
                "merge_id": merge_id,
                "fold": fold_by_id[merge_id],
                "member_verdict": str(group["member_verdict"].iloc[0]),
                "left_features": ((left[node_columns].to_numpy(np.float32) - node_mean) / node_std).astype(np.float32),
                "right_features": ((right[node_columns].to_numpy(np.float32) - node_mean) / node_std).astype(
                    np.float32
                ),
                "left_indices": left["member_index"].to_numpy(np.int64),
                "right_indices": right["member_index"].to_numpy(np.int64),
                "left_target": left["target"].to_numpy(np.float32),
                "right_target": right["target"].to_numpy(np.float32),
                "edge_features": matrix,
                "edge_mask": mask,
            }
        )
    return samples


def train_model(samples: list[dict[str, Any]], node_count: int, device: torch.device) -> BipartiteMemberSelector:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    model = BipartiteMemberSelector(node_count, len(EDGE_FEATURES)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=8.0e-4, weight_decay=2.0e-4)
    positive = sum(float(sample["left_target"].sum() + sample["right_target"].sum()) for sample in samples)
    total = sum(len(sample["left_target"]) + len(sample["right_target"]) for sample in samples)
    positive_weight = torch.tensor((total - positive) / max(positive, 1.0), device=device)
    loader = DataLoader(SampleDataset(samples), batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
    for epoch in range(EPOCHS):
        losses: list[float] = []
        model.train()
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            left_logits, right_logits = model(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            logits = torch.cat(
                [left_logits[batch["left_mask"].to(device)], right_logits[batch["right_mask"].to(device)]]
            )
            targets = torch.cat(
                [
                    batch["left_target"].to(device)[batch["left_mask"].to(device)],
                    batch["right_target"].to(device)[batch["right_mask"].to(device)],
                ]
            )
            bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=positive_weight)
            probabilities = torch.sigmoid(logits)
            dice = 1.0 - (2.0 * (probabilities * targets).sum() + 1.0) / (probabilities.sum() + targets.sum() + 1.0)
            loss = bce + 0.25 * dice
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch in {0, 9, 19, 29, EPOCHS - 1}:
            print(f"epoch {epoch + 1}/{EPOCHS}: loss={np.mean(losses):.5f}", flush=True)
    return model


def predict(
    model: BipartiteMemberSelector, samples: list[dict[str, Any]], device: torch.device
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    loader = DataLoader(SampleDataset(samples), batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate)
    sample_by_id = {sample["merge_id"]: sample for sample in samples}
    model.eval()
    with torch.no_grad():
        for batch in loader:
            left_logits, right_logits = model(
                batch["left_features"].to(device),
                batch["right_features"].to(device),
                batch["edge_features"].to(device),
                batch["edge_mask"].to(device),
            )
            for batch_index, merge_id in enumerate(batch["merge_ids"]):
                sample = sample_by_id[merge_id]
                for side_left, indices, targets, logits in (
                    (1.0, sample["left_indices"], sample["left_target"], left_logits[batch_index]),
                    (0.0, sample["right_indices"], sample["right_target"], right_logits[batch_index]),
                ):
                    probabilities = torch.sigmoid(logits[: len(indices)]).cpu().numpy()
                    for member_index, target, probability in zip(indices, targets, probabilities, strict=True):
                        rows.append(
                            {
                                "merge_id": merge_id,
                                "side_left": side_left,
                                "member_index": int(member_index),
                                "target": int(target),
                                "probability:bipartite-neural": float(probability),
                            }
                        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True)
    parser.add_argument("--member-predictions", required=True)
    parser.add_argument("--edge-context", required=True)
    parser.add_argument("--report-predictions", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    device = torch.device("mps" if args.device == "auto" and torch.backends.mps.is_available() else "cpu")
    if args.device not in {"auto", "cpu"}:
        device = torch.device(args.device)
    print(f"device: {device}", flush=True)

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
    edges = prepare_edges(pd.read_parquet(args.member_predictions), pd.read_parquet(args.edge_context))
    excluded = {"merge_id", "member_index", "target", "member_verdict"}
    node_columns = [column for column in frame if column not in excluded]
    groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    for fold, (_, test_indices) in enumerate(GroupKFold(5).split(labels, labels["member_verdict"], groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    subset_ids = set(labels.loc[labels["member_verdict"] == "merge_subset", "merge_id"].astype(str))
    oof_rows: list[dict[str, Any]] = []
    for fold in range(5):
        train_ids = {merge_id for merge_id in subset_ids if fold_by_id[merge_id] != fold}
        node_train = frame.loc[frame["merge_id"].astype(str).isin(train_ids), node_columns]
        edge_train = edges.loc[edges["merge_id"].astype(str).isin(train_ids), list(EDGE_FEATURES)]
        node_mean = node_train.mean().to_numpy(np.float32)
        node_std = node_train.std().clip(lower=1e-5).to_numpy(np.float32)
        edge_mean = edge_train.mean().to_numpy(np.float32)
        edge_std = edge_train.std().clip(lower=1e-5).to_numpy(np.float32)
        samples = make_samples(frame, edges, node_columns, node_mean, node_std, edge_mean, edge_std, fold_by_id)
        train_samples = [sample for sample in samples if sample["merge_id"] in train_ids]
        test_samples = [sample for sample in samples if sample["fold"] == fold]
        print(f"fold {fold}: train={len(train_samples)} score={len(test_samples)}", flush=True)
        model = train_model(train_samples, len(node_columns), device)
        oof_rows.extend(predict(model, test_samples, device))

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    oof = pd.DataFrame(oof_rows)
    oof.to_parquet(output / "bipartite_member_selector_oof.parquet", index=False)
    subset_oof = oof.loc[oof["merge_id"].isin(subset_ids)]
    metrics = {
        "status": "five-fold edge-aware bipartite member selector; exact subset rows train",
        "architecture": {"hidden": HIDDEN, "layers": LAYERS, "epochs": EPOCHS},
        "subset_member_rows": len(subset_oof),
        "auc": float(roc_auc_score(subset_oof["target"], subset_oof["probability:bipartite-neural"])),
        "average_precision": float(
            average_precision_score(subset_oof["target"], subset_oof["probability:bipartite-neural"])
        ),
    }
    (output / "bipartite_member_selector_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    node_train = frame.loc[frame["merge_id"].astype(str).isin(subset_ids), node_columns]
    edge_train = edges.loc[edges["merge_id"].astype(str).isin(subset_ids), list(EDGE_FEATURES)]
    node_mean = node_train.mean().to_numpy(np.float32)
    node_std = node_train.std().clip(lower=1e-5).to_numpy(np.float32)
    edge_mean = edge_train.mean().to_numpy(np.float32)
    edge_std = edge_train.std().clip(lower=1e-5).to_numpy(np.float32)
    samples = make_samples(frame, edges, node_columns, node_mean, node_std, edge_mean, edge_std, fold_by_id)
    final_train = [sample for sample in samples if sample["merge_id"] in subset_ids]
    print(f"final model: train={len(final_train)}", flush=True)
    final_model = train_model(final_train, len(node_columns), device)
    torch.save(
        {
            "state_dict": final_model.state_dict(),
            "node_columns": node_columns,
            "node_mean": node_mean,
            "node_std": node_std,
            "edge_mean": edge_mean,
            "edge_std": edge_std,
            "architecture": metrics["architecture"],
        },
        output / "bipartite_member_selector.pt",
    )
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()
