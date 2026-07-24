"""Train a shallow set transformer to select exact subset members jointly."""

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

SEED = 17
HIDDEN = 64
HEADS = 4
LAYERS = 2
EPOCHS = 35
BATCH_SIZE = 8


class MemberSetSelector(nn.Module):
    def __init__(self, input_features: int) -> None:
        super().__init__()
        self.input_projection = nn.Linear(input_features, HIDDEN)
        self.side_embedding = nn.Embedding(2, HIDDEN)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=HIDDEN,
            nhead=HEADS,
            dim_feedforward=HIDDEN * 2,
            dropout=0.10,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=LAYERS, enable_nested_tensor=False)
        self.output = nn.Sequential(nn.LayerNorm(HIDDEN), nn.Linear(HIDDEN, 1))

    def forward(self, features: torch.Tensor, sides: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        hidden = self.input_projection(features) + self.side_embedding(sides)
        hidden = self.encoder(hidden, src_key_padding_mask=~mask)
        return self.output(hidden).squeeze(-1)


class ReportDataset(Dataset[dict[str, Any]]):
    def __init__(self, samples: list[dict[str, Any]]) -> None:
        self.samples = samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.samples[index]


def collate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    max_members = max(len(sample["target"]) for sample in samples)
    feature_count = samples[0]["features"].shape[1]
    features = np.zeros((len(samples), max_members, feature_count), dtype=np.float32)
    sides = np.zeros((len(samples), max_members), dtype=np.int64)
    targets = np.zeros((len(samples), max_members), dtype=np.float32)
    mask = np.zeros((len(samples), max_members), dtype=bool)
    for index, sample in enumerate(samples):
        count = len(sample["target"])
        features[index, :count] = sample["features"]
        sides[index, :count] = sample["sides"]
        targets[index, :count] = sample["target"]
        mask[index, :count] = True
    return {
        "merge_ids": [sample["merge_id"] for sample in samples],
        "features": torch.from_numpy(features),
        "sides": torch.from_numpy(sides),
        "targets": torch.from_numpy(targets),
        "mask": torch.from_numpy(mask),
    }


def make_samples(
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
                "sides": ordered["side_left"].to_numpy(dtype=np.int64),
                "member_indices": ordered["member_index"].to_numpy(dtype=np.int64),
                "target": ordered["target"].to_numpy(dtype=np.float32),
                "member_verdict": str(ordered["member_verdict"].iloc[0]),
            }
        )
    return samples


def train_model(samples: list[dict[str, Any]], feature_count: int, device: torch.device) -> MemberSetSelector:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    model = MemberSetSelector(feature_count).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.0e-3, weight_decay=2.0e-4)
    positive = sum(float(sample["target"].sum()) for sample in samples)
    total = sum(len(sample["target"]) for sample in samples)
    positive_weight = torch.tensor((total - positive) / max(positive, 1.0), device=device)
    loader = DataLoader(ReportDataset(samples), batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
    model.train()
    for epoch in range(EPOCHS):
        losses: list[float] = []
        for batch in loader:
            features = batch["features"].to(device)
            sides = batch["sides"].to(device)
            targets = batch["targets"].to(device)
            mask = batch["mask"].to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features, sides, mask)
            active_logits = logits[mask]
            active_targets = targets[mask]
            bce = nn.functional.binary_cross_entropy_with_logits(
                active_logits,
                active_targets,
                pos_weight=positive_weight,
            )
            probabilities = torch.sigmoid(active_logits)
            dice = 1.0 - (2.0 * (probabilities * active_targets).sum() + 1.0) / (
                probabilities.sum() + active_targets.sum() + 1.0
            )
            loss = bce + 0.25 * dice
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        if epoch in {0, 9, 19, 29, EPOCHS - 1}:
            print(f"epoch {epoch + 1}/{EPOCHS}: loss={np.mean(losses):.5f}", flush=True)
    return model


def predict_samples(
    model: MemberSetSelector, samples: list[dict[str, Any]], device: torch.device
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    loader = DataLoader(ReportDataset(samples), batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate)
    sample_by_id = {sample["merge_id"]: sample for sample in samples}
    model.eval()
    with torch.no_grad():
        for batch in loader:
            logits = model(
                batch["features"].to(device),
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
                            "probability:contextual-set": float(probability),
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
    if args.device == "auto":
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    else:
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
    label_by_id = labels.set_index("merge_id")
    frame["member_verdict"] = frame["merge_id"].map(label_by_id["member_verdict"])
    excluded = {"merge_id", "member_index", "target", "member_verdict"}
    feature_columns = [column for column in frame if column not in excluded]

    groups = component_groups(labels)
    fold_by_id: dict[str, int] = {}
    splitter = GroupKFold(n_splits=5)
    for fold, (_, test_indices) in enumerate(splitter.split(labels, labels["member_verdict"], groups)):
        for merge_id in labels.iloc[test_indices]["merge_id"]:
            fold_by_id[str(merge_id)] = fold
    eligible = frame["member_verdict"] == "merge_subset"
    oof_rows: list[dict[str, Any]] = []
    for fold in range(5):
        train_members = frame.loc[eligible & (frame["merge_id"].astype(str).map(fold_by_id) != fold), feature_columns]
        mean = train_members.mean().to_numpy(dtype=np.float32)
        std = train_members.std().clip(lower=1e-5).to_numpy(dtype=np.float32)
        samples = make_samples(frame, feature_columns, mean, std, fold_by_id)
        train_samples = [
            sample for sample in samples if sample["member_verdict"] == "merge_subset" and sample["fold"] != fold
        ]
        test_samples = [sample for sample in samples if sample["fold"] == fold]
        print(f"fold {fold}: train={len(train_samples)} score={len(test_samples)}", flush=True)
        model = train_model(train_samples, len(feature_columns), device)
        oof_rows.extend(predict_samples(model, test_samples, device))

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    oof = pd.DataFrame(oof_rows)
    oof.to_parquet(output / "contextual_member_selector_oof.parquet", index=False)
    subset_ids = set(labels.loc[labels["member_verdict"] == "merge_subset", "merge_id"].astype(str))
    subset_oof = oof.loc[oof["merge_id"].isin(subset_ids)]
    metrics = {
        "status": "five-fold contextual set member selector; exact subset rows train, all held-component rows score",
        "architecture": {"hidden": HIDDEN, "heads": HEADS, "layers": LAYERS, "epochs": EPOCHS},
        "subset_member_rows": len(subset_oof),
        "auc": float(roc_auc_score(subset_oof["target"], subset_oof["probability:contextual-set"])),
        "average_precision": float(
            average_precision_score(subset_oof["target"], subset_oof["probability:contextual-set"])
        ),
    }
    (output / "contextual_member_selector_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    final_members = frame.loc[eligible, feature_columns]
    final_mean = final_members.mean().to_numpy(dtype=np.float32)
    final_std = final_members.std().clip(lower=1e-5).to_numpy(dtype=np.float32)
    final_samples = make_samples(frame, feature_columns, final_mean, final_std, fold_by_id)
    final_train = [sample for sample in final_samples if sample["member_verdict"] == "merge_subset"]
    print(f"final model: train={len(final_train)}", flush=True)
    final_model = train_model(final_train, len(feature_columns), device)
    torch.save(
        {
            "state_dict": final_model.state_dict(),
            "feature_columns": feature_columns,
            "mean": final_mean,
            "std": final_std,
            "architecture": metrics["architecture"],
        },
        output / "contextual_member_selector.pt",
    )
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()
