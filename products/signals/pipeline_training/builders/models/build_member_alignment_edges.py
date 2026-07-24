"""Build sparse cross-report member edges for compatibility scoring."""

# ruff: noqa: T201

from __future__ import annotations

import json
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parent


def top_indices(values: np.ndarray, k: int) -> np.ndarray:
    count = min(k, len(values))
    if count == len(values):
        return np.argsort(-values)
    selected = np.argpartition(-values, count - 1)[:count]
    return selected[np.argsort(-values[selected])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()

    ledger = pd.read_parquet(args.ledger)
    corpus = Path(args.corpus)
    signal_ids = [json.loads(line)["id"] for line in (corpus / "signals.jsonl").read_text().splitlines()]
    signal_index = {str(signal_id): index for index, signal_id in enumerate(signal_ids)}
    embeddings = np.load(corpus / "embeddings.npy", mmap_mode="r")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    edge_rows: list[dict[str, object]] = []
    requests: set[tuple[str, str]] = set()
    for row_index, row in enumerate(ledger.itertuples(index=False)):
        left_ids = [str(value) for value in json.loads(row.left_members)]
        right_ids = [str(value) for value in json.loads(row.right_members)]
        left_embeddings = np.asarray(embeddings[[signal_index[value] for value in left_ids]], dtype=np.float32)
        right_embeddings = np.asarray(embeddings[[signal_index[value] for value in right_ids]], dtype=np.float32)
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            similarities = left_embeddings @ right_embeddings.T
        if not np.isfinite(similarities).all():
            raise ValueError(f"non-finite embedding similarity for {row.merge_id}")
        selected: set[tuple[int, int]] = set()
        left_ranks: dict[tuple[int, int], int] = {}
        right_ranks: dict[tuple[int, int], int] = {}
        for left_index in range(len(left_ids)):
            for rank, right_index in enumerate(top_indices(similarities[left_index], args.top_k), start=1):
                edge = (left_index, int(right_index))
                selected.add(edge)
                left_ranks[edge] = rank
        for right_index in range(len(right_ids)):
            for rank, left_index in enumerate(top_indices(similarities[:, right_index], args.top_k), start=1):
                edge = (int(left_index), right_index)
                selected.add(edge)
                right_ranks[edge] = rank
        for left_index, right_index in sorted(selected):
            left_id = left_ids[left_index]
            right_id = right_ids[right_index]
            doc_a, doc_b = sorted((left_id, right_id))
            requests.add((doc_a, doc_b))
            edge = (left_index, right_index)
            edge_rows.append(
                {
                    "merge_id": str(row.merge_id),
                    "left_member_index": left_index,
                    "right_member_index": right_index,
                    "left_id": left_id,
                    "right_id": right_id,
                    "doc_a": doc_a,
                    "doc_b": doc_b,
                    "embedding_cosine": float(similarities[left_index, right_index]),
                    "left_rank": left_ranks.get(edge),
                    "right_rank": right_ranks.get(edge),
                    "mutual_top_k": edge in left_ranks and edge in right_ranks,
                }
            )
        if (row_index + 1) % 250 == 0:
            print(f"member edges: {row_index + 1}/{len(ledger)}")

    edges = pd.DataFrame(edge_rows)
    edges.to_parquet(output / "member_edges.parquet", index=False)
    with (output / "pair_requests.jsonl").open("w") as destination:
        for doc_a, doc_b in sorted(requests):
            destination.write(json.dumps({"doc_a": doc_a, "doc_b": doc_b}) + "\n")
    summary = {
        "status": "score-independent sparse member candidates; operation targets not used in retrieval",
        "ledger": str(Path(args.ledger).resolve()),
        "corpus": str(corpus.resolve()),
        "report_pairs": len(ledger),
        "member_edges": len(edges),
        "unique_signal_pairs": len(requests),
        "top_k_each_direction": args.top_k,
        "mean_edges_per_report_pair": len(edges) / len(ledger),
    }
    (output / "edge_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
