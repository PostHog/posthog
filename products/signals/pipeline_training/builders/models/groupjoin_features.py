"""Build serving-parity report-candidate features for the elected GroupJoin line.

The input frame is produced by ``build_groupjoin_frame.py``. Embeddings and signal
metadata come from the materialized train corpus, which is also what the Rust
replayer consumes. The 26 engineered features and the optional neural tensors
mirror ``engine/src/classifier.rs::gj_score``.

Run from lab/2:
    python models/groupjoin_features.py --build data/groupjoin/<build-id> --neural
"""

# ruff: noqa: T201

from __future__ import annotations

import sys
import json
import math
import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB2 = HERE.parent
sys.path.insert(0, str(LAB2))
from core.features import extract_identifiers  # noqa: E402
from core.signatures import GROUP_SIG_FEATURE_NAMES, group_signature_features  # noqa: E402

MEMBER_CAP = 40
RELATION_CHANNELS = 12

ENGINEERED_FEATURE_NAMES = [
    "cos_max",
    "cos_2nd",
    "cos_mean",
    "cos_centroid",
    "coherence",
    "coherence_delta",
    "log_size",
    "rank_best",
    "n_retrieved",
    "frac_same_product",
    "frac_same_type",
    "log_gap_hours",
    "log_span_hours",
    "id_shared",
    "id_conflict",
    *GROUP_SIG_FEATURE_NAMES,
]


@dataclass(frozen=True)
class Signal:
    document_id: str
    timestamp: float
    content: str
    product: str
    source_type: str


@dataclass(frozen=True)
class Signature:
    tokens: dict[str, object]
    embedding: np.ndarray


class CorpusContext:
    def __init__(self, corpus_dir: Path) -> None:
        raw_signals = [json.loads(line) for line in (corpus_dir / "signals.jsonl").open() if line.strip()]
        self.signals = {
            str(value["id"]): Signal(
                document_id=str(value["id"]),
                timestamp=float(value["ts"]),
                content=str(value.get("content") or ""),
                product=str(value.get("product") or ""),
                source_type=str(value.get("type") or ""),
            )
            for value in raw_signals
        }
        self.ids = [str(value["id"]) for value in raw_signals]
        self.index = {document_id: row for row, document_id in enumerate(self.ids)}

        raw_embeddings = np.load(corpus_dir / "embeddings.npy").astype(np.float32, copy=False)
        if len(raw_embeddings) != len(self.ids):
            raise ValueError(f"embedding rows {len(raw_embeddings)} != signal rows {len(self.ids)}")
        norms = np.sqrt(np.sum(raw_embeddings.astype(np.float64) ** 2, axis=1, keepdims=True))
        self.embeddings = (raw_embeddings.astype(np.float64) / np.maximum(norms, 1e-12)).astype(np.float32)
        prefix64 = self.embeddings[:, :64].astype(np.float64)
        prefix256 = self.embeddings[:, :256].astype(np.float64)
        self.embeddings64 = (prefix64 / np.maximum(np.linalg.norm(prefix64, axis=1, keepdims=True), 1e-9)).astype(
            np.float32
        )
        self.embeddings256 = (prefix256 / np.maximum(np.linalg.norm(prefix256, axis=1, keepdims=True), 1e-9)).astype(
            np.float32
        )

        self.signatures: dict[str, Signature] = {}
        sig_path = corpus_dir / "sigs.jsonl"
        if sig_path.exists():
            for line in sig_path.open():
                if not line.strip():
                    continue
                value = json.loads(line)
                embedding = np.asarray(value.get("emb") or [], dtype=np.float32)
                self.signatures[str(value["document_id"])] = Signature(
                    tokens={
                        "polarity": str(value.get("polarity") or "neutral"),
                        "surface": list(value.get("surface") or []),
                        "failmode": list(value.get("failmode") or []),
                        "tags": list(value.get("tags") or []),
                        "anchor": list(value.get("anchor") or []),
                        "oneliner": list(value.get("oneliner") or []),
                        "has_failmode": bool(value.get("has_failmode")),
                        "has_anchor": bool(value.get("has_anchor")),
                    },
                    embedding=embedding,
                )
        self.identifier_cache: dict[str, dict[str, set[str]]] = {}

    def identifiers(self, document_id: str) -> dict[str, set[str]]:
        if document_id not in self.identifier_cache:
            self.identifier_cache[document_id] = extract_identifiers(self.signals[document_id].content)
        return self.identifier_cache[document_id]

    def signature_side(
        self, document_ids: list[str]
    ) -> list[tuple[dict[str, object] | None, np.ndarray | None, tuple[str, str]]]:
        result = []
        for document_id in document_ids:
            signal = self.signals[document_id]
            signature = self.signatures.get(document_id)
            result.append(
                (
                    signature.tokens if signature else None,
                    signature.embedding if signature is not None and len(signature.embedding) else None,
                    (signal.product, signal.source_type),
                )
            )
        return result


def _dot(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.sum(left.astype(np.float64) * right.astype(np.float64)))


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set, right_set = set(left), set(right)
    return len(left_set & right_set) / max(len(left_set | right_set), 1)


def compute_row(
    context: CorpusContext,
    query: str,
    members: list[str],
    n_members: int,
    rank_best: int,
    n_retrieved: int,
    include_neural: bool,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if query not in context.index:
        raise KeyError(f"query {query} is absent from the corpus")
    members = [member for member in members[-MEMBER_CAP:] if member in context.index]
    if not members:
        raise ValueError(f"query {query} has no corpus members")

    query_row = context.index[query]
    member_rows = np.asarray([context.index[member] for member in members], dtype=np.int64)
    query_embedding = context.embeddings[query_row]
    member_embeddings = context.embeddings[member_rows]
    similarities = np.asarray([_dot(query_embedding, member) for member in member_embeddings], dtype=np.float64)
    sorted_similarities = np.sort(similarities)[::-1]

    accumulator = np.sum(member_embeddings.astype(np.float64), axis=0)
    mean_embedding = accumulator / len(members)
    coherence = float(np.linalg.norm(mean_embedding))
    centroid = mean_embedding / max(coherence, 1e-9)
    cos_centroid = float(np.sum(query_embedding.astype(np.float64) * centroid))
    with_query_norm = float(np.linalg.norm((accumulator + query_embedding.astype(np.float64)) / (len(members) + 1)))

    query_signal = context.signals[query]
    member_signals = [context.signals[member] for member in members]
    timestamps = np.asarray([signal.timestamp for signal in member_signals], dtype=np.float64)
    same_product = sum(signal.product == query_signal.product for signal in member_signals)
    same_type = sum(signal.source_type == query_signal.source_type for signal in member_signals)

    query_ids = context.identifiers(query)
    shared = 0.0
    conflict = 0.0
    for member in members[:10]:
        member_ids = context.identifiers(member)
        for category, query_values in query_ids.items():
            if not query_values:
                continue
            member_values = member_ids.get(category)
            if member_values:
                intersection = query_values & member_values
                shared += len(intersection)
                if not intersection:
                    conflict += 1.0

    signature_features = group_signature_features(context.signature_side([query]), context.signature_side(members[:10]))
    engineered = np.asarray(
        [
            sorted_similarities[0],
            sorted_similarities[1] if len(sorted_similarities) > 1 else 0.0,
            float(np.mean(similarities)),
            cos_centroid,
            coherence,
            with_query_norm - coherence,
            math.log1p(n_members),
            min(rank_best, 25) / 25.0,
            min(n_retrieved, 10) / 10.0,
            same_product / len(members),
            same_type / len(members),
            math.log1p(abs(query_signal.timestamp - float(timestamps.max())) / 3600.0),
            math.log1p((float(timestamps.max()) - float(timestamps.min())) / 3600.0),
            min(shared, 10.0) / 10.0,
            min(conflict, 10.0) / 10.0,
            *[signature_features[name] for name in GROUP_SIG_FEATURE_NAMES],
        ],
        dtype=np.float32,
    )
    if not include_neural:
        return engineered, None, None, None

    channels = np.zeros((MEMBER_CAP, RELATION_CHANNELS), dtype=np.float16)
    member_prefix64 = np.zeros((MEMBER_CAP, 64), dtype=np.float16)
    mask = np.zeros(MEMBER_CAP, dtype=bool)
    query_signature = context.signatures.get(query)
    query64 = context.embeddings64[query_row]
    query256 = context.embeddings256[query_row]
    for position, (member, member_row, member_embedding, similarity) in enumerate(
        zip(members, member_rows, member_embeddings, similarities)
    ):
        member_signal = context.signals[member]
        member_signature = context.signatures.get(member)
        if query_signature is not None and member_signature is not None:
            signature_cosine = _dot(query_signature.embedding, member_signature.embedding)
            tag_jaccard = _jaccard(list(query_signature.tokens["tags"]), list(member_signature.tokens["tags"]))
        else:
            signature_cosine = 0.5
            tag_jaccard = 0.5

        member_ids = context.identifiers(member)
        member_shared = 0.0
        member_conflict = 0.0
        for category, query_values in query_ids.items():
            if not query_values:
                continue
            member_values = member_ids.get(category)
            if member_values:
                intersection = query_values & member_values
                member_shared += len(intersection)
                if not intersection:
                    member_conflict += 1.0

        channels[position] = np.asarray(
            [
                similarity,
                _dot(query256, context.embeddings256[member_row]),
                _dot(query64, context.embeddings64[member_row]),
                signature_cosine,
                tag_jaccard,
                float(member_signal.product == query_signal.product),
                float(member_signal.source_type == query_signal.source_type),
                min(member_shared, 5.0) / 5.0,
                min(member_conflict, 5.0) / 5.0,
                math.log1p(abs(query_signal.timestamp - member_signal.timestamp) / 3600.0) / 8.0,
                (len(members) - position) / len(members),
                float(np.sum(member_embedding.astype(np.float64) * centroid)),
            ],
            dtype=np.float16,
        )
        member_prefix64[position] = context.embeddings64[member_row].astype(np.float16)
        mask[position] = True
    return engineered, channels, member_prefix64, mask


def build_features(
    frame: pd.DataFrame,
    corpus_dir: Path,
    include_neural: bool,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    context = CorpusContext(corpus_dir)
    features = np.zeros((len(frame), len(ENGINEERED_FEATURE_NAMES)), dtype=np.float32)
    neural: dict[str, np.ndarray] = {}
    if include_neural:
        neural = {
            "channels": np.zeros((len(frame), MEMBER_CAP, RELATION_CHANNELS), dtype=np.float16),
            "member64": np.zeros((len(frame), MEMBER_CAP, 64), dtype=np.float16),
            "mask": np.zeros((len(frame), MEMBER_CAP), dtype=bool),
        }

    for index, row in enumerate(frame.itertuples(index=False)):
        engineered, channels, member64, mask = compute_row(
            context=context,
            query=str(row.query),
            members=list(json.loads(row.members)),
            n_members=int(row.n_members),
            rank_best=int(row.rank_best),
            n_retrieved=int(row.n_retrieved),
            include_neural=include_neural,
        )
        features[index] = engineered
        if include_neural:
            assert channels is not None and member64 is not None and mask is not None
            neural["channels"][index] = channels
            neural["member64"][index] = member64
            neural["mask"][index] = mask
        if index % 20_000 == 19_999:
            print(f"features {index + 1:,}/{len(frame):,}", flush=True)

    identity_columns = [
        column
        for column in (
            "tuple_id",
            "decision_id",
            "regime",
            "query",
            "candidate_report",
            "label",
            "label_weight",
            "sample_weight",
            "pointer_member",
            "group_single_concern",
        )
        if column in frame.columns
    ]
    output = frame[identity_columns].reset_index(drop=True).copy()
    for column, values in zip(ENGINEERED_FEATURE_NAMES, features.T):
        output[column] = values
    return output, neural


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True)
    parser.add_argument("--corpus", default=str(LAB2 / "data" / "corpora" / "train"))
    parser.add_argument("--all-rows", action="store_true", help="include unknown-label tuples")
    parser.add_argument("--neural", action="store_true", help="also write relation/member tensors")
    parser.add_argument("--feature-output", default="groupjoin_features.parquet")
    parser.add_argument("--neural-output", default="groupjoin_neural.npz")
    args = parser.parse_args()

    build = Path(args.build).resolve()
    frame = pd.read_parquet(build / "groupjoin_frame.parquet")
    if not args.all_rows:
        frame = frame[frame["label_known"]].reset_index(drop=True)
    output, neural = build_features(frame, Path(args.corpus).resolve(), args.neural)
    feature_path = build / args.feature_output
    output.to_parquet(feature_path, index=False)
    print(f"wrote {feature_path}: {len(output):,} rows x {len(ENGINEERED_FEATURE_NAMES)} features", flush=True)
    if args.neural:
        neural_path = build / args.neural_output
        np.savez(neural_path, **neural)
        print(f"wrote {neural_path}: {neural['channels'].shape}", flush=True)


if __name__ == "__main__":
    main()
