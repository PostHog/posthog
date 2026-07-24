from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import cast

import numpy as np

from .corpus import Corpus, band_of, month_of
from .io import JsonObject, parse_epoch


@dataclass(frozen=True)
class LinkageGroup:
    group_id: str
    report_ids: tuple[str, ...]
    features: dict[str, float]
    band: str

    @property
    def signal_count(self) -> int:
        return int(self.features["n_signals"])


class UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        self.parent[second] = first


def build_linkage_groups(
    corpus: Corpus,
    links: list[JsonObject],
    *,
    cosine_threshold: float,
    minimum_smaller_overlap: float,
) -> list[LinkageGroup]:
    report_ids = sorted(corpus.reports)
    union_find = UnionFind(report_ids)
    sizes = {report_id: len(corpus.signal_ids(report_id)) for report_id in report_ids}
    for link in links:
        left = str(link["report_a"])
        right = str(link["report_b"])
        if left not in sizes or right not in sizes or float(link["max_cosine"]) < cosine_threshold:
            continue
        overlap = int(link["overlap_a"]) if sizes[left] <= sizes[right] else int(link["overlap_b"])
        if overlap >= 1 and overlap / min(sizes[left], sizes[right]) >= minimum_smaller_overlap:
            union_find.union(left, right)

    members: dict[str, list[str]] = defaultdict(list)
    for report_id in report_ids:
        members[union_find.find(report_id)].append(report_id)

    groups: list[LinkageGroup] = []
    for report_group in sorted(tuple(sorted(value)) for value in members.values()):
        digest = hashlib.sha256("\n".join(report_group).encode()).hexdigest()[:16]
        features = group_features(corpus, report_group)
        groups.append(
            LinkageGroup(
                group_id=f"link-{digest}",
                report_ids=report_group,
                features=features,
                band=band_of(int(features["n_signals"])),
            )
        )
    return groups


def group_features(corpus: Corpus, report_ids: tuple[str, ...]) -> dict[str, float]:
    signals = [corpus.signals[member] for report_id in report_ids for member in corpus.signal_ids(report_id)]
    sources = Counter(str(signal["source_product"]) for signal in signals)
    months = Counter(month_of(parse_epoch(signal.get("timestamp"), "signal.timestamp")) for signal in signals)
    report_sizes = [len(corpus.signal_ids(report_id)) for report_id in report_ids]
    report_bands = Counter()
    heterogeneous = 0
    error_tracking_only = 0
    for report_id, size in zip(report_ids, report_sizes, strict=True):
        row = corpus.reports[report_id]
        report_bands[str(row.get("band", band_of(size)))] += size
        heterogeneous += int(bool(row.get("heterogeneous", False)))
        error_tracking_only += int(bool(row.get("error_tracking_only", False)))
    result: dict[str, float] = {
        "n_signals": float(len(signals)),
        "n_reports": float(len(report_ids)),
        "n_heterogeneous": float(heterogeneous),
        "n_error_tracking_only": float(error_tracking_only),
        "n_multi": float(sum(size > 1 for size in report_sizes)),
    }
    result.update({f"source:{name}": float(count) for name, count in sorted(sources.items())})
    result.update({f"month:{name}": float(count) for name, count in sorted(months.items())})
    result.update({f"band_mass:{name}": float(count) for name, count in sorted(report_bands.items())})
    return result


def deal_groups(
    groups: list[LinkageGroup],
    territory_names: tuple[str, str, str],
    *,
    seed: int,
    swap_iterations: int,
) -> dict[str, str]:
    if not groups:
        return {}
    feature_names = sorted({name for group in groups for name in group.features})
    feature_matrix = np.array(
        [[group.features.get(name, 0.0) for name in feature_names] for group in groups], dtype=np.float64
    )
    scale = feature_matrix.sum(axis=0)
    scale[scale == 0] = 1.0
    normalized = feature_matrix / scale
    weights = np.array([3.0 if name == "n_signals" else 1.0 for name in feature_names], dtype=np.float64)
    report_index = feature_names.index("n_reports")
    weights[report_index] = 1.0
    totals = np.zeros((3, len(feature_names)), dtype=np.float64)
    assignments = np.full(len(groups), -1, dtype=np.int64)
    rng = np.random.default_rng(seed)

    def cost(values: np.ndarray) -> float:
        return float((weights * values.var(axis=0)).sum())

    band_values = sorted({group.band for group in groups}, key=lambda value: -(999 if value == "128+" else int(value)))
    for band in band_values:
        indices = np.array([index for index, group in enumerate(groups) if group.band == band], dtype=np.int64)
        ties = rng.random(len(indices))
        indices = indices[np.lexsort((ties, -feature_matrix[indices, 0]))]
        for index_value in indices:
            index = int(index_value)
            best_territory = 0
            best_cost: float | None = None
            for territory in range(3):
                totals[territory] += normalized[index]
                candidate_cost = cost(totals)
                totals[territory] -= normalized[index]
                if best_cost is None or candidate_cost < best_cost:
                    best_territory = territory
                    best_cost = candidate_cost
            totals[best_territory] += normalized[index]
            assignments[index] = best_territory

    current_cost = cost(totals)
    for _iteration in range(swap_iterations):
        left = int(rng.integers(len(groups)))
        right = int(rng.integers(len(groups)))
        left_territory = int(assignments[left])
        right_territory = int(assignments[right])
        if left_territory == right_territory or groups[left].band != groups[right].band:
            continue
        delta = normalized[right] - normalized[left]
        totals[left_territory] += delta
        totals[right_territory] -= delta
        candidate_cost = cost(totals)
        if candidate_cost < current_cost:
            assignments[left], assignments[right] = right_territory, left_territory
            current_cost = candidate_cost
        else:
            totals[left_territory] -= delta
            totals[right_territory] += delta

    return {group.group_id: territory_names[int(assignments[index])] for index, group in enumerate(groups)}


def territory_profile(corpus: Corpus, report_ids: set[str]) -> JsonObject:
    selected = corpus.selected(report_ids)
    sources = Counter(str(row["source_product"]) for row in selected.signals.values())
    bands = Counter(str(selected.reports[report_id].get("band")) for report_id in selected.reports)
    return cast(
        JsonObject,
        {
            "reports": len(selected.reports),
            "signals": len(selected.signals),
            "heterogeneous_reports": sum(
                bool(selected.reports[report_id].get("heterogeneous", False)) for report_id in selected.reports
            ),
            "multi_signal_reports": sum(len(selected.signal_ids(report_id)) > 1 for report_id in selected.reports),
            "source_share": {name: count / max(len(selected.signals), 1) for name, count in sorted(sources.items())},
            "report_bands": dict(sorted(bands.items())),
        },
    )
