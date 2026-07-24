"""Train the source-pinned direct DeepSets report join head.

This is an offline lineage candidate, not yet a Rust-served model. Every OOF
encoder excludes the held clone-linkage fold from both query and candidate
members. The final state is trained for the median OOF-selected epoch count and
is the only state eligible for export. A GBM over OOF pooled representations is
reported as an ablation but is deliberately not exported.

Run from lab/2:
    python models/train_groupjoin_neural.py --build data/groupjoin/<build-id> --run-id <run-id>
"""

# ruff: noqa: T201

from __future__ import annotations

import sys
import json
import pickle
import hashlib
import argparse
from pathlib import Path

import numpy as np
import torch
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

HERE = Path(__file__).resolve().parent
LAB2 = HERE.parent
sys.path.insert(0, str(LAB2))
from models.groupjoin_features import ENGINEERED_FEATURE_NAMES  # noqa: E402
from models.train_groupjoin import N_FOLDS, attach_folds  # noqa: E402

SEED = 29
MEMBER_CAP = 40
RELATION_CHANNELS = 12
MEMBER_EMBEDDING_DIMS = 64
TOKEN_DIMS = RELATION_CHANNELS + MEMBER_EMBEDDING_DIMS
POOL_DIMS = 32


class DirectGroupJoin(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.phi = torch.nn.Sequential(
            torch.nn.Linear(TOKEN_DIMS, 64),
            torch.nn.ReLU(),
            torch.nn.Linear(64, 64),
            torch.nn.ReLU(),
        )
        self.rho = torch.nn.Sequential(torch.nn.Linear(128, POOL_DIMS), torch.nn.ReLU())
        self.head = torch.nn.Sequential(
            torch.nn.Linear(POOL_DIMS + len(ENGINEERED_FEATURE_NAMES), 64),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.2),
            torch.nn.Linear(64, 1),
        )
        self.pointer = torch.nn.Linear(64, 1)

    def forward(
        self, tokens: torch.Tensor, mask: torch.Tensor, engineered: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        hidden = self.phi(tokens)
        visible = hidden.masked_fill(~mask.unsqueeze(-1), 0.0)
        member_count = mask.to(dtype=hidden.dtype).sum(dim=1, keepdim=True).clamp(min=1.0)
        mean = visible.sum(dim=1) / member_count
        maximum = hidden.masked_fill(~mask.unsqueeze(-1), -1e4).max(dim=1).values
        pooled = self.rho(torch.cat([mean, maximum], dim=-1))
        join_logit = self.head(torch.cat([pooled, engineered], dim=-1)).squeeze(-1)
        pointer_logits = self.pointer(hidden).squeeze(-1).masked_fill(~mask, -1e4)
        return join_logit, pointer_logits, pooled


def augment(
    tokens: np.ndarray, mask: np.ndarray, pointer: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    augmented = tokens.copy()
    augmented_mask = mask.copy()
    for row in range(len(augmented)):
        present = np.flatnonzero(augmented_mask[row])
        if len(present) <= 2:
            continue
        protected = {int(pointer[row])} if pointer[row] >= 0 else set()
        if rng.random() < 0.3:
            keep = int(rng.integers(2, len(present) + 1))
            drop = [position for position in present[keep:] if position not in protected]
            augmented_mask[row, drop] = False
            present = np.flatnonzero(augmented_mask[row])
        target_count = max(2, int(len(present) * rng.uniform(0.6, 1.0)))
        droppable = np.asarray([position for position in present if position not in protected], dtype=np.int64)
        if target_count < len(present) and len(droppable):
            count = min(len(present) - target_count, len(droppable))
            augmented_mask[row, rng.choice(droppable, count, replace=False)] = False
            present = np.flatnonzero(augmented_mask[row])
        if rng.random() < 0.5 and len(present) > 3:
            maximum_drop = max(1, int(0.15 * len(present)))
            count = int(rng.integers(0, maximum_drop + 1))
            droppable = np.asarray([position for position in present if position not in protected], dtype=np.int64)
            if count and len(droppable):
                augmented_mask[row, rng.choice(droppable, min(count, len(droppable)), replace=False)] = False
    augmented[:, :, RELATION_CHANNELS:] += rng.normal(0.0, 0.01, augmented[:, :, RELATION_CHANNELS:].shape).astype(
        np.float32
    )
    return augmented, augmented_mask


def predict(
    model: DirectGroupJoin,
    tokens: np.ndarray,
    mask: np.ndarray,
    engineered: np.ndarray,
    rows: np.ndarray,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    logits: list[np.ndarray] = []
    pointers: list[np.ndarray] = []
    pools: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            selected = rows[start : start + batch_size]
            outputs = model(
                torch.from_numpy(tokens[selected]).to(device),
                torch.from_numpy(mask[selected]).to(device),
                torch.from_numpy(engineered[selected]).to(device),
            )
            logits.append(outputs[0].cpu().numpy())
            pointers.append(outputs[1].cpu().numpy())
            pools.append(outputs[2].cpu().numpy())
    return np.concatenate(logits), np.concatenate(pointers), np.concatenate(pools)


def train_model(
    tokens: np.ndarray,
    mask: np.ndarray,
    engineered: np.ndarray,
    y: np.ndarray,
    weight: np.ndarray,
    pointer: np.ndarray,
    train_rows: np.ndarray,
    validation_rows: np.ndarray | None,
    device: torch.device,
    seed: int,
    max_epochs: int,
    patience: int,
    batch_size: int,
    decision_groups: list[np.ndarray],
    listwise_weight: float,
    selection_rule: str,
) -> tuple[DirectGroupJoin, int, float]:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = DirectGroupJoin().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.5e-3, weight_decay=3e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, max_epochs)
    positive_mass = float(weight[train_rows & y].sum())
    negative_mass = float(weight[train_rows & ~y].sum())
    positive_weight = max(negative_mass / max(positive_mass, 1e-9), 1e-4)
    positive_weight_tensor = torch.tensor(positive_weight, device=device)

    best_auc = -1.0
    best_selection_metric = -1.0
    best_epoch = max_epochs
    best_state: dict[str, torch.Tensor] | None = None
    stale = 0
    indices = np.flatnonzero(train_rows)
    ranking_groups = []
    if listwise_weight > 0:
        for group in decision_groups:
            selected = group[train_rows[group]]
            labels = y[selected]
            if labels.any() and not labels.all():
                ranking_groups.append(selected)
    validation_position = (
        {int(row): position for position, row in enumerate(validation_rows)} if validation_rows is not None else {}
    )
    validation_ranking_groups = [
        group
        for group in decision_groups
        if validation_position
        and all(int(row) in validation_position for row in group)
        and y[group].any()
        and not y[group].all()
    ]
    for epoch in range(max_epochs):
        model.train()
        permutation = rng.permutation(indices)
        for start in range(0, len(indices), batch_size):
            batch = permutation[start : start + batch_size]
            augmented, augmented_mask = augment(tokens[batch], mask[batch], pointer[batch], rng)
            batch_tokens = torch.from_numpy(augmented).to(device)
            batch_mask = torch.from_numpy(augmented_mask).to(device)
            batch_engineered = torch.from_numpy(engineered[batch]).to(device)
            batch_y = torch.from_numpy(y[batch].astype(np.float32)).to(device)
            batch_weight = torch.from_numpy(weight[batch].astype(np.float32)).to(device)
            join_logit, pointer_logits, _pool = model(batch_tokens, batch_mask, batch_engineered)
            join_loss = torch.nn.functional.binary_cross_entropy_with_logits(
                join_logit,
                batch_y,
                reduction="none",
                pos_weight=positive_weight_tensor,
            )
            loss = (join_loss * batch_weight).sum() / batch_weight.sum().clamp(min=1e-9)
            pointer_target = torch.from_numpy(pointer[batch]).to(device)
            pointer_ok = (pointer_target >= 0) & batch_mask.gather(1, pointer_target.clamp(min=0).unsqueeze(1)).squeeze(
                1
            )
            if pointer_ok.any():
                pointer_loss = torch.nn.functional.cross_entropy(
                    pointer_logits[pointer_ok], pointer_target[pointer_ok], reduction="none"
                )
                pointer_row_weight = batch_weight[pointer_ok]
                loss = loss + 0.25 * (pointer_loss * pointer_row_weight).sum() / pointer_row_weight.sum().clamp(
                    min=1e-9
                )
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        if ranking_groups:
            ranking_order = rng.permutation(len(ranking_groups))
            for start in range(0, len(ranking_order), 128):
                groups = [ranking_groups[index] for index in ranking_order[start : start + 128]]
                flat = np.concatenate(groups)
                join_logit, _pointer_logits, _pool = model(
                    torch.from_numpy(tokens[flat]).to(device),
                    torch.from_numpy(mask[flat]).to(device),
                    torch.from_numpy(engineered[flat]).to(device),
                )
                losses = []
                offset = 0
                for group in groups:
                    length = len(group)
                    group_logits = join_logit[offset : offset + length]
                    group_labels = torch.from_numpy(y[group]).to(device)
                    losses.append(
                        torch.logsumexp(group_logits, dim=0) - torch.logsumexp(group_logits[group_labels], dim=0)
                    )
                    offset += length
                ranking_loss = listwise_weight * torch.stack(losses).mean()
                optimizer.zero_grad()
                ranking_loss.backward()
                optimizer.step()
        scheduler.step()

        if validation_rows is None:
            continue
        validation_logits, _pointers, _pool = predict(
            model, tokens, mask, engineered, validation_rows, device, batch_size * 4
        )
        validation_auc = roc_auc_score(y[validation_rows], validation_logits, sample_weight=weight[validation_rows])
        validation_top1 = []
        for group in validation_ranking_groups:
            labels = y[group]
            group_scores = np.asarray([validation_logits[validation_position[int(row)]] for row in group])
            validation_top1.append(float(labels[int(np.argmax(group_scores))]))
        top1 = float(np.mean(validation_top1)) if validation_top1 else 0.0
        selection_metric = {
            "auc": float(validation_auc),
            "top1": top1,
            "blend": 0.75 * float(validation_auc) + 0.25 * top1,
        }[selection_rule]
        print(f"  epoch {epoch + 1:02d}: val AUC {validation_auc:.4f}, contested top1 {top1:.4f}", flush=True)
        if selection_metric > best_selection_metric + 1e-4:
            best_selection_metric = selection_metric
            best_auc = float(validation_auc)
            best_epoch = epoch + 1
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
        if stale >= patience:
            break

    if validation_rows is not None:
        if best_state is None:
            raise RuntimeError("early stopping did not retain a model")
        model.load_state_dict(best_state)
    else:
        best_auc = float("nan")
    return model, best_epoch, best_auc


def metrics(
    y: np.ndarray, raw: np.ndarray, calibrated: np.ndarray, weight: np.ndarray, selected: np.ndarray
) -> dict[str, float]:
    return {
        "rows": float(selected.sum()),
        "positive_rate": float(np.average(y[selected], weights=weight[selected])),
        "auc_raw": float(roc_auc_score(y[selected], raw[selected], sample_weight=weight[selected])),
        "ap_raw": float(average_precision_score(y[selected], raw[selected], sample_weight=weight[selected])),
        "brier_calibrated": float(brier_score_loss(y[selected], calibrated[selected], sample_weight=weight[selected])),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--document-groups", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--max-epochs", type=int, default=24)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--device", choices=("mps", "cpu"))
    parser.add_argument(
        "--listwise-weight",
        type=float,
        default=0.0,
        help="auxiliary multi-positive report-ranking loss; zero is the binary direct baseline",
    )
    parser.add_argument("--selection-rule", choices=("auc", "top1", "blend"), default="auc")
    args = parser.parse_args()

    build = Path(args.build).resolve()
    frame = pd.read_parquet(build / "groupjoin_frame.parquet")
    frame = frame[frame["label_known"]].reset_index(drop=True)
    features = pd.read_parquet(build / "groupjoin_features.parquet")
    tensors = np.load(build / "groupjoin_neural.npz")
    if len(frame) != len(features) or len(frame) != len(tensors["mask"]):
        raise ValueError("frame, engineered features, and neural tensors are not row-aligned")
    frame = attach_folds(frame, args.document_groups)
    keep = ~frame["mixed_evidence"].to_numpy(bool)
    frame = frame.loc[keep].reset_index(drop=True)
    features = features.loc[keep].reset_index(drop=True)
    channels = tensors["channels"][keep].astype(np.float32)
    member64 = tensors["member64"][keep].astype(np.float32)
    mask = tensors["mask"][keep]
    tokens = np.concatenate([channels, member64], axis=-1)
    raw_engineered = features[ENGINEERED_FEATURE_NAMES].to_numpy(dtype=np.float32)
    y = frame["label"].to_numpy(bool)
    weight = frame["sample_weight"].to_numpy(dtype=np.float64)
    query_fold = frame["query_fold"].to_numpy(dtype=np.int8)
    touched_mask = frame["touched_fold_mask"].to_numpy(dtype=np.int16)
    strict_cold = frame["strict_cold"].to_numpy(bool)
    decision_groups = [
        np.asarray(indices, dtype=np.int64) for indices in frame.groupby("decision_id", sort=False).indices.values()
    ]

    pointer = np.full(len(frame), -1, dtype=np.int64)
    for index, row in enumerate(frame.itertuples(index=False)):
        if not isinstance(row.pointer_member, str) or not row.pointer_member:
            continue
        members = [str(member) for member in json.loads(row.members)]
        if row.pointer_member in members:
            pointer[index] = members.index(row.pointer_member)
    print(
        f"{len(frame):,} no-conflict tuples, {int(y.sum()):,} positive, {int((pointer >= 0).sum()):,} pointer targets",
        flush=True,
    )

    if args.device:
        device = torch.device(args.device)
    else:
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device: {device}", flush=True)
    oof_logit = np.full(len(frame), np.nan, dtype=np.float32)
    oof_pointer = np.full((len(frame), MEMBER_CAP), np.nan, dtype=np.float32)
    oof_pool = np.full((len(frame), POOL_DIMS), np.nan, dtype=np.float32)
    selected_epochs: list[int] = []
    fold_states: list[dict[str, torch.Tensor]] = []
    fold_normalizers: list[tuple[np.ndarray, np.ndarray]] = []
    for fold in range(N_FOLDS):
        train = (touched_mask & (1 << fold)) == 0
        validate = query_fold == fold
        mean = raw_engineered[train].mean(axis=0)
        std = raw_engineered[train].std(axis=0) + 1e-6
        normalized = ((raw_engineered - mean) / std).astype(np.float32)
        print(f"fold {fold}: train {int(train.sum()):,}, validate {int(validate.sum()):,}", flush=True)
        model, epoch, auc = train_model(
            tokens,
            mask,
            normalized,
            y,
            weight,
            pointer,
            train,
            np.flatnonzero(validate),
            device,
            SEED + fold,
            args.max_epochs,
            args.patience,
            args.batch_size,
            decision_groups,
            args.listwise_weight,
            args.selection_rule,
        )
        logits, pointer_logits, pools = predict(
            model, tokens, mask, normalized, np.flatnonzero(validate), device, args.batch_size * 4
        )
        oof_logit[validate] = logits
        oof_pointer[validate] = pointer_logits
        oof_pool[validate] = pools
        selected_epochs.append(epoch)
        fold_states.append({name: value.detach().cpu() for name, value in model.state_dict().items()})
        fold_normalizers.append((mean, std))
        print(f"fold {fold}: selected epoch {epoch}, AUC {auc:.4f}", flush=True)

    if np.isnan(oof_logit).any() or np.isnan(oof_pool).any():
        raise ValueError("neural cross-fit left rows without predictions")
    oof_raw = 1.0 / (1.0 + np.exp(-oof_logit.astype(np.float64)))
    oof_calibrated = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        fit = query_fold != fold
        validate = query_fold == fold
        iso_fold = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso_fold.fit(oof_raw[fit], y[fit], sample_weight=weight[fit])
        oof_calibrated[validate] = iso_fold.predict(oof_raw[validate])
    isotonic = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    isotonic.fit(oof_raw, y, sample_weight=weight)

    all_rows = np.ones(len(frame), dtype=bool)
    direct_metrics: dict[str, dict[str, float] | float] = {
        "all": metrics(y, oof_raw, oof_calibrated, weight, all_rows),
        "strict_cold": metrics(y, oof_raw, oof_calibrated, weight, strict_cold),
    }
    pointer_rows = pointer >= 0
    direct_metrics["pointer_top1"] = float((oof_pointer[pointer_rows].argmax(axis=1) == pointer[pointer_rows]).mean())

    stack_features = np.concatenate([raw_engineered, oof_pool], axis=1)
    stack_raw = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        train = (touched_mask & (1 << fold)) == 0
        validate = query_fold == fold
        stack_model = HistGradientBoostingClassifier(max_depth=3, random_state=SEED + fold)
        stack_model.fit(stack_features[train], y[train], sample_weight=weight[train])
        stack_raw[validate] = stack_model.predict_proba(stack_features[validate])[:, 1]
    stack_calibrated = np.full(len(frame), np.nan, dtype=np.float64)
    for fold in range(N_FOLDS):
        fit = query_fold != fold
        validate = query_fold == fold
        iso_fold = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso_fold.fit(stack_raw[fit], y[fit], sample_weight=weight[fit])
        stack_calibrated[validate] = iso_fold.predict(stack_raw[validate])
    stack_metrics = {
        "all": metrics(y, stack_raw, stack_calibrated, weight, all_rows),
        "strict_cold": metrics(y, stack_raw, stack_calibrated, weight, strict_cold),
        "status": "cross-fit evaluation only; no final stack exported",
    }
    print(json.dumps({"direct": direct_metrics, "stack_ablation": stack_metrics}, indent=2), flush=True)

    final_mean = raw_engineered.mean(axis=0)
    final_std = raw_engineered.std(axis=0) + 1e-6
    final_engineered = ((raw_engineered - final_mean) / final_std).astype(np.float32)
    final_epochs = max(1, int(np.median(selected_epochs)))
    final_model, _epoch, _auc = train_model(
        tokens,
        mask,
        final_engineered,
        y,
        weight,
        pointer,
        np.ones(len(frame), dtype=bool),
        None,
        device,
        SEED + 100,
        final_epochs,
        patience=0,
        batch_size=args.batch_size,
        decision_groups=decision_groups,
        listwise_weight=args.listwise_weight,
        selection_rule=args.selection_rule,
    )
    final_model = final_model.cpu().eval()
    suffix = "_listwise" if args.listwise_weight > 0 else ""
    state_path = build / f"groupjoin_direct{suffix}.pt"
    torch.save(
        {
            "schema_version": 1,
            "model_family": "groupjoin_direct_deepsets",
            "state_dict": final_model.state_dict(),
            "engineered_mean": final_mean,
            "engineered_std": final_std,
            "feature_names": ENGINEERED_FEATURE_NAMES,
            "member_cap": MEMBER_CAP,
            "relation_channels": RELATION_CHANNELS,
            "member_embedding_dims": MEMBER_EMBEDDING_DIMS,
            "pool_dims": POOL_DIMS,
            "selected_epochs": selected_epochs,
            "final_epochs": final_epochs,
            "label_rule": "mixed evidence excluded",
            "listwise_weight": args.listwise_weight,
            "selection_rule": args.selection_rule,
        },
        state_path,
    )
    with (build / f"groupjoin_direct{suffix}_isotonic.pkl").open("wb") as file:
        pickle.dump(isotonic, file)
    np.savez(
        build / f"groupjoin_direct{suffix}_oof.npz",
        join_logit=oof_logit,
        join_raw=oof_raw,
        join_calibrated=oof_calibrated,
        pointer_logits=oof_pointer,
        pooled=oof_pool,
        query_fold=query_fold,
        strict_cold=strict_cold,
    )
    result = {
        "status": "offline candidate; Rust executor and replay parity still required",
        "state": {"path": state_path.name, "bytes": state_path.stat().st_size, "sha256": sha256(state_path)},
        "direct_metrics": direct_metrics,
        "stack_ablation_metrics": stack_metrics,
        "selected_epochs": selected_epochs,
        "final_epochs": final_epochs,
        "oof_strategy": ("five clone-linkage folds; held fold absent from query and candidate members in encoder fit"),
        "serving_review": "NEURAL_SERVING_REVIEW.md",
        "listwise_weight": args.listwise_weight,
        "selection_rule": args.selection_rule,
    }
    (build / f"groupjoin_direct{suffix}_metrics.json").write_text(json.dumps(result, indent=2, sort_keys=True))

    if args.run_id:
        sys.path.insert(0, str(LAB2 / "perf"))
        from perfdb import PerfDB  # noqa: PLC0415

        db = PerfDB()
        member_name = "groupjoin-direct-listwise" if args.listwise_weight > 0 else "groupjoin-direct-neural"
        activity = db.start_activity(
            args.run_id,
            stage="train",
            kind="fit",
            member=member_name,
            params={
                "component": "direct deep sets",
                "final_epochs": final_epochs,
                "state_sha256": sha256(state_path),
                "listwise_weight": args.listwise_weight,
                "selection_rule": args.selection_rule,
            },
        )
        for family, family_metrics in (("direct", direct_metrics), ("stack_ablation", stack_metrics)):
            for slice_name, values in family_metrics.items():
                if not isinstance(values, dict):
                    continue
                for metric_name, value in values.items():
                    db.metric(
                        args.run_id,
                        f"groupjoin_{metric_name}",
                        value,
                        stage="train",
                        member=member_name,
                        slice=f"{family}:{slice_name}",
                        shard="train",
                        layer="train",
                    )
        db.metric(
            args.run_id,
            "groupjoin_pointer_top1",
            direct_metrics["pointer_top1"],
            stage="train",
            member=member_name,
            shard="train",
            layer="train",
        )
        db.finish_activity(activity)


if __name__ == "__main__":
    main()
