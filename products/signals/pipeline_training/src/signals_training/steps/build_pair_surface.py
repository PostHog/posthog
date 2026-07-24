from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd

from ..corpus import Corpus
from ..io import JsonObject, read_jsonl, write_json, write_jsonl
from ..stage import StageContext
from ..surface_evidence import PairEvidence, resolve_pair_evidence, sampled_cross_pairs, sampled_pairs, stable_rank


class BuildPairSurface:
    name = "build_pair_surface"

    def input_paths(self, context: StageContext) -> list[Path]:
        train = context.stage_dir("split_territories") / "train"
        labels = context.stage_dir("prepare_labels") / "train"
        return [
            train / "signals.jsonl",
            train / "reports.jsonl",
            *(labels / name for name in ("pairs.jsonl", "reports.jsonl", "operations.jsonl")),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "frame.parquet",
            directory / "pairs.jsonl",
            directory / "excluded.jsonl",
            directory / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return cast(JsonObject, context.config.surfaces)

    def run(self, context: StageContext) -> None:
        train = context.stage_dir("split_territories") / "train"
        label_directory = context.stage_dir("prepare_labels") / "train"
        corpus = Corpus.load(train / "signals.jsonl", train / "reports.jsonl")
        coherent_limit = self._integer(context, "coherent_pairs_per_report")
        operation_limit = self._integer(context, "operation_pairs_per_operation")
        evidence: list[PairEvidence] = []

        for _line, row in read_jsonl(label_directory / "pairs.jsonl"):
            if bool(row.get("has_conflict")):
                continue
            evidence.append(
                PairEvidence(
                    str(row["signal_a"]),
                    str(row["signal_b"]),
                    bool(row["same_concern"]),
                    float(cast(float, row["confidence"])),
                    f"atomic:{row['provenance']}",
                )
            )

        for _line, row in read_jsonl(label_directory / "reports.jsonl"):
            if not (row.get("coherent") is True or row.get("gold_positive") is True):
                continue
            report_id = str(row["report_id"])
            confidence = float(cast(float, row["confidence"]))
            for left, right in sampled_pairs(corpus.signal_ids(report_id), coherent_limit, report_id):
                evidence.append(PairEvidence(left, right, True, 0.8 * confidence, "coherent_report"))

        for _line, row in read_jsonl(label_directory / "operations.jsonl"):
            if bool(row.get("has_conflict")) or row.get("verdict") == "ambiguous":
                continue
            left_members = corpus.signal_ids(str(row["left_report_id"]))
            right_members = corpus.signal_ids(str(row["right_report_id"]))
            confidence = float(cast(float, row["confidence"]))
            verdict = str(row["verdict"])
            if verdict in {"keep_separate", "whole_merge"}:
                pairs = sampled_cross_pairs(
                    left_members,
                    right_members,
                    operation_limit,
                    str(row["operation_id"]),
                )
                for left, right in pairs:
                    evidence.append(
                        PairEvidence(left, right, verdict == "whole_merge", confidence, f"operation:{verdict}")
                    )
            elif verdict == "subset":
                selected_left = cast(list[str], row.get("selected_left", []))
                selected_right = cast(list[str], row.get("selected_right", []))
                pairs = sampled_cross_pairs(
                    selected_left,
                    selected_right,
                    operation_limit,
                    str(row["operation_id"]),
                )
                for left, right in pairs:
                    evidence.append(PairEvidence(left, right, True, confidence, "operation:subset"))

        resolved, excluded = resolve_pair_evidence(evidence)
        positives = [row for row in resolved if bool(row["y"])]
        negatives = [row for row in resolved if not bool(row["y"])]
        ratio = self._number(context, "pair_negative_to_positive_ratio")
        negative_limit = min(len(negatives), int(round(ratio * len(positives))))
        negatives = sorted(
            negatives,
            key=lambda row: stable_rank("negative", str(row["doc_a"]), str(row["doc_b"])),
        )[:negative_limit]
        frame_rows = sorted([*positives, *negatives], key=lambda row: (str(row["doc_a"]), str(row["doc_b"])))
        if not positives or not negatives:
            raise ValueError("pair training surface requires both positive and negative evidence")
        directory = context.stage_dir(self.name)
        pd.DataFrame(frame_rows).to_parquet(directory / "frame.parquet", index=False)
        write_jsonl(directory / "pairs.jsonl", ({"doc_a": row["doc_a"], "doc_b": row["doc_b"]} for row in frame_rows))
        write_jsonl(directory / "excluded.jsonl", excluded)
        write_json(
            directory / "summary.json",
            {
                "rows": len(frame_rows),
                "positive": len(positives),
                "negative": len(negatives),
                "excluded_conflicts": len(excluded),
                "negative_to_positive_ratio": len(negatives) / len(positives),
                "rule": "Atomic, coherent-report, and exact-operation evidence joined by unordered signal pair.",
            },
        )

    @staticmethod
    def _integer(context: StageContext, name: str) -> int:
        value = context.config.surfaces.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"surfaces.{name} must be an integer")
        return value

    @staticmethod
    def _number(context: StageContext, name: str) -> float:
        value = context.config.surfaces.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"surfaces.{name} must be numeric")
        return float(value)
