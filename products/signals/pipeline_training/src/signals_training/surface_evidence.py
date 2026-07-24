from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .io import JsonObject


@dataclass(frozen=True)
class PairEvidence:
    left: str
    right: str
    label: bool
    weight: float
    source: str

    @property
    def key(self) -> tuple[str, str]:
        values = sorted((self.left, self.right))
        return values[0], values[1]


def stable_rank(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def sampled_pairs(values: list[str], maximum: int, namespace: str) -> list[tuple[str, str]]:
    pairs = [(left, right) for index, left in enumerate(values) for right in values[index + 1 :]]
    return sorted(pairs, key=lambda pair: stable_rank(namespace, *pair))[:maximum]


def sampled_cross_pairs(left: list[str], right: list[str], maximum: int, namespace: str) -> list[tuple[str, str]]:
    pairs = [(left_value, right_value) for left_value in left for right_value in right]
    return sorted(pairs, key=lambda pair: stable_rank(namespace, *pair))[:maximum]


def resolve_pair_evidence(rows: list[PairEvidence]) -> tuple[list[JsonObject], list[JsonObject]]:
    grouped: dict[tuple[str, str], list[PairEvidence]] = {}
    for row in rows:
        grouped.setdefault(row.key, []).append(row)
    resolved: list[JsonObject] = []
    excluded: list[JsonObject] = []
    for key, evidence in sorted(grouped.items()):
        positive = max((item.weight for item in evidence if item.label), default=0.0)
        negative = max((item.weight for item in evidence if not item.label), default=0.0)
        if positive > 0 and negative > 0 and abs(positive - negative) < 0.2:
            excluded.append(
                {
                    "doc_a": key[0],
                    "doc_b": key[1],
                    "reason": "unresolved_label_conflict",
                    "positive_weight": positive,
                    "negative_weight": negative,
                    "sources": sorted({item.source for item in evidence}),
                }
            )
            continue
        label = positive > negative
        resolved.append(
            {
                "doc_a": key[0],
                "doc_b": key[1],
                "y": label,
                "weight": max(positive, negative),
                "source": "+".join(sorted({item.source for item in evidence if item.label == label})),
            }
        )
    return resolved, excluded
