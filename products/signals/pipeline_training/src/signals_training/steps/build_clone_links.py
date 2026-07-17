from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import cast

import numpy as np

from ..corpus import Corpus
from ..io import JsonObject, write_json, write_jsonl
from ..stage import StageContext


class BuildCloneLinks:
    name = "build_clone_links"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("enrich_concerns") / "signals.jsonl",
            context.stage_dir("import_export") / "reports.jsonl",
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "report_links.jsonl", directory / "member_links.jsonl", directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "minimum_cosine": min(
                self._number(context.config.territories, "clone_link_cosine"),
                self._number(context.config.territories, "residual_link_cosine"),
            ),
            "batch_size": self._integer(context.config.labeling, "clone_scan_batch_size"),
            "scan": "exact all-pairs content-embedding cosine",
        }

    def run(self, context: StageContext) -> None:
        signals_path, reports_path = self.input_paths(context)
        corpus = Corpus.load(signals_path, reports_path)
        document_ids = sorted(corpus.signals)
        if not document_ids:
            raise ValueError("export contains no signals")
        vectors = np.asarray(
            [corpus.signals[document_id]["embedding"] for document_id in document_ids], dtype=np.float32
        )
        if vectors.ndim != 2 or vectors.shape[1] != 1536 or not np.isfinite(vectors).all():
            raise ValueError("every exported signal embedding must contain 1,536 finite numbers")
        norms = np.linalg.norm(vectors, axis=1)
        if np.any(norms <= 1e-12):
            raise ValueError("exported signal embeddings must be nonzero")
        vectors /= norms[:, None]

        threshold = min(
            self._number(context.config.territories, "clone_link_cosine"),
            self._number(context.config.territories, "residual_link_cosine"),
        )
        batch_size = self._integer(context.config.labeling, "clone_scan_batch_size")
        report_members: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
        report_max: dict[tuple[str, str], float] = defaultdict(lambda: -1.0)
        member_links: list[JsonObject] = []
        for start in range(0, len(document_ids), batch_size):
            stop = min(start + batch_size, len(document_ids))
            similarities = vectors[start:stop] @ vectors.T
            for local_index, scores in enumerate(similarities):
                left_index = start + local_index
                for right_index in np.flatnonzero(scores >= threshold):
                    right = int(right_index)
                    if right <= left_index:
                        continue
                    signal_a = document_ids[left_index]
                    signal_b = document_ids[right]
                    source_report_a = corpus.report_of[signal_a]
                    source_report_b = corpus.report_of[signal_b]
                    if source_report_a == source_report_b:
                        continue
                    cosine = min(float(scores[right]), 1.0)
                    report_a, report_b = sorted((source_report_a, source_report_b))
                    if source_report_a == report_a:
                        member_a, member_b = signal_a, signal_b
                    else:
                        member_a, member_b = signal_b, signal_a
                    key = (report_a, report_b)
                    sides = report_members.setdefault(key, (set(), set()))
                    sides[0].add(member_a)
                    sides[1].add(member_b)
                    report_max[key] = max(report_max[key], cosine)
                    member_links.append(
                        {
                            "signal_a": member_a,
                            "signal_b": member_b,
                            "report_a": report_a,
                            "report_b": report_b,
                            "cosine": cosine,
                        }
                    )

        report_links = [
            {
                "report_a": report_a,
                "report_b": report_b,
                "max_cosine": report_max[(report_a, report_b)],
                "overlap_a": len(report_members[(report_a, report_b)][0]),
                "overlap_b": len(report_members[(report_a, report_b)][1]),
            }
            for report_a, report_b in sorted(report_members)
        ]
        member_links.sort(
            key=lambda row: (
                str(row["report_a"]),
                str(row["report_b"]),
                -cast(float, row["cosine"]),
                str(row["signal_a"]),
                str(row["signal_b"]),
            )
        )
        directory = context.stage_dir(self.name)
        write_jsonl(directory / "report_links.jsonl", report_links)
        write_jsonl(directory / "member_links.jsonl", member_links)
        write_json(
            directory / "summary.json",
            {
                "signals": len(document_ids),
                "embedding_width": int(vectors.shape[1]),
                "minimum_cosine": threshold,
                "member_links": len(member_links),
                "report_links": len(report_links),
                "scan": "exact all-pairs; no nearest-neighbor cap",
            },
        )

    @staticmethod
    def _integer(values: dict[str, object], name: str) -> int:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"labeling.{name} must be a positive integer")
        return value

    @staticmethod
    def _number(values: dict[str, object], name: str) -> float:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"territories.{name} must be numeric")
        return float(value)
