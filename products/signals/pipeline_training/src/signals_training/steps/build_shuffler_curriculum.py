from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pandas as pd

from ..corpus import Corpus
from ..io import JsonObject, read_jsonl, write_json
from ..stage import StageContext
from ..surface_evidence import stable_rank


class BuildShufflerCurriculum:
    name = "build_shuffler_curriculum"

    def input_paths(self, context: StageContext) -> list[Path]:
        train = context.stage_dir("split_territories") / "train"
        labels = context.stage_dir("prepare_labels") / "train"
        return [train / "signals.jsonl", train / "reports.jsonl", labels / "reports.jsonl", labels / "operations.jsonl"]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "labels.parquet",
            directory / "human_labels.parquet",
            directory / "synthetic_labels.parquet",
            directory / "consensus_labels.parquet",
            directory / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "seed": context.config.seed,
            "within_report_repeats": context.config.surfaces.get("curriculum_within_report_repeats"),
            "max_triplets": context.config.surfaces.get("curriculum_max_triplets"),
        }

    def run(self, context: StageContext) -> None:
        train = context.stage_dir("split_territories") / "train"
        labels_dir = context.stage_dir("prepare_labels") / "train"
        corpus = Corpus.load(train / "signals.jsonl", train / "reports.jsonl")
        human_rows: list[dict[str, object]] = []
        synthetic_rows: list[dict[str, object]] = []
        operations = [row for _line, row in read_jsonl(labels_dir / "operations.jsonl")]
        for operation in operations:
            row = self._explicit_row(corpus, operation)
            if row is not None:
                human_rows.append(row)
        if not human_rows:
            raise ValueError("shuffler fine-tuning requires at least one non-ambiguous human operation")

        coherent_reports: dict[str, float] = {}
        for _line, report in read_jsonl(labels_dir / "reports.jsonl"):
            if report.get("coherent") is True or report.get("gold_positive") is True:
                report_id = str(report["report_id"])
                coherent_reports[report_id] = max(
                    coherent_reports.get(report_id, 0.0), float(cast(float, report["confidence"]))
                )
        repeats_value = context.config.surfaces.get("curriculum_within_report_repeats")
        if isinstance(repeats_value, bool) or not isinstance(repeats_value, int):
            raise ValueError("surfaces.curriculum_within_report_repeats must be an integer")
        for report_id, confidence in sorted(coherent_reports.items()):
            members = corpus.signal_ids(report_id)
            if len(members) < 2:
                continue
            for repeat in range(repeats_value):
                ordered = sorted(members, key=lambda value: stable_rank("whole-merge", report_id, str(repeat), value))
                split = max(1, len(ordered) // 2)
                left, right = ordered[:split], ordered[split:]
                if right:
                    synthetic_rows.append(
                        self._row(
                            merge_id=self._id("within", report_id, str(repeat)),
                            operation_kind="within_report_whole_merge",
                            source_report_ids=[report_id],
                            left_report_id=f"{report_id}:left:{repeat}",
                            right_report_id=f"{report_id}:right:{repeat}",
                            left=left,
                            right=right,
                            selected_left=left,
                            selected_right=right,
                            verdict="merge_all",
                            secondary_selected_left=left,
                            secondary_selected_right=right,
                            secondary_verdict="merge_all",
                            weight=0.5 * confidence,
                            provenance="synthetic_coherent_curriculum_v1",
                        )
                    )

        separate_edges = {
            tuple(sorted((str(row["left_report_id"]), str(row["right_report_id"]))))
            for row in operations
            if row.get("verdict") == "keep_separate" and not bool(row.get("has_conflict"))
        }
        triangles = self._triangles(separate_edges)
        max_triplets = context.config.surfaces.get("curriculum_max_triplets")
        if isinstance(max_triplets, bool) or not isinstance(max_triplets, int):
            raise ValueError("surfaces.curriculum_max_triplets must be an integer")
        selected_triangles = sorted(triangles, key=lambda value: stable_rank("triplet", *value))[:max_triplets]
        for triangle in selected_triangles:
            for target_index, target in enumerate(triangle):
                target_members = corpus.signal_ids(target)
                if len(target_members) < 2:
                    continue
                distractors = [value for value in triangle if value != target]
                ordered = sorted(
                    target_members,
                    key=lambda value: stable_rank("triplet-target", *triangle, target, value),
                )
                split = max(1, len(ordered) // 2)
                target_left, target_right = ordered[:split], ordered[split:]
                if not target_right:
                    continue
                left = [*target_left, *corpus.signal_ids(distractors[0])]
                right = [*target_right, *corpus.signal_ids(distractors[1])]
                synthetic_rows.append(
                    self._row(
                        merge_id=self._id("triplet", *triangle, str(target_index)),
                        operation_kind="three_component_new_report",
                        source_report_ids=list(triangle),
                        left_report_id=f"triplet:{self._id(*triangle)}:left",
                        right_report_id=f"triplet:{self._id(*triangle)}:right",
                        left=left,
                        right=right,
                        selected_left=target_left,
                        selected_right=target_right,
                        verdict="merge_subset",
                        secondary_selected_left=target_left,
                        secondary_selected_right=target_right,
                        secondary_verdict="merge_subset",
                        weight=0.5,
                        provenance="synthetic_coherent_curriculum_v1",
                    )
                )

        rows = [*human_rows, *synthetic_rows]
        if not rows:
            raise ValueError("shuffler curriculum is empty")
        frame = pd.DataFrame(rows).sort_values("merge_id").reset_index(drop=True)
        human_frame = pd.DataFrame(human_rows, columns=frame.columns).sort_values("merge_id").reset_index(drop=True)
        synthetic_frame = (
            pd.DataFrame(synthetic_rows, columns=frame.columns).sort_values("merge_id").reset_index(drop=True)
        )
        consensus_frame = frame.loc[frame["has_secondary_reader"]].reset_index(drop=True)
        consensus_groups = self._component_group_count(consensus_frame)
        if consensus_groups < 5:
            raise ValueError("consensus shuffler curriculum needs at least five independent source-report components")
        exact_consensus = consensus_frame.loc[consensus_frame["strict_consensus_eligible"]]
        component_present = exact_consensus["member_components"].ne("[]")
        if not component_present.any() or component_present.all():
            raise ValueError(
                "consensus shuffler curriculum needs exact-agreement positive and keep-separate operations"
            )
        directory = context.stage_dir(self.name)
        frame.to_parquet(directory / "labels.parquet", index=False)
        human_frame.to_parquet(directory / "human_labels.parquet", index=False)
        synthetic_frame.to_parquet(directory / "synthetic_labels.parquet", index=False)
        consensus_frame.to_parquet(directory / "consensus_labels.parquet", index=False)
        write_json(
            directory / "summary.json",
            {
                "operations": len(frame),
                "human_operations": len(human_frame),
                "synthetic_operations": len(synthetic_frame),
                "consensus_operations": len(consensus_frame),
                "consensus_source_components": consensus_groups,
                "strict_consensus_operations": len(exact_consensus),
                "independent_dual_reader_operations": int(
                    consensus_frame["secondary_reader"].fillna("").ne("synthetic_deterministic").sum()
                ),
                "member_rows": int((frame["left_size"] + frame["right_size"]).sum()),
                "by_kind": {str(key): int(value) for key, value in frame["operation_kind"].value_counts().items()},
                "by_verdict": {str(key): int(value) for key, value in frame["member_verdict"].value_counts().items()},
                "triplet_triangles": len(selected_triangles),
            },
        )

    def _explicit_row(self, corpus: Corpus, operation: JsonObject) -> dict[str, object] | None:
        if bool(operation.get("has_conflict")) or operation.get("verdict") == "ambiguous":
            return None
        left_report = str(operation["left_report_id"])
        right_report = str(operation["right_report_id"])
        left = corpus.signal_ids(left_report)
        right = corpus.signal_ids(right_report)
        verdict = str(operation["verdict"])
        selected_left = cast(list[str], operation.get("selected_left", []))
        selected_right = cast(list[str], operation.get("selected_right", []))
        if verdict == "whole_merge":
            selected_left, selected_right, member_verdict = left, right, "merge_all"
        elif verdict == "subset":
            member_verdict = "merge_subset"
        else:
            selected_left, selected_right, member_verdict = [], [], "keep_separate"
        secondary_verdict_value = operation.get("secondary_verdict")
        secondary_verdict = str(secondary_verdict_value) if secondary_verdict_value not in {None, "ambiguous"} else None
        secondary_selected_left = cast(list[str], operation.get("secondary_selected_left", []))
        secondary_selected_right = cast(list[str], operation.get("secondary_selected_right", []))
        if secondary_verdict == "whole_merge":
            secondary_selected_left, secondary_selected_right, secondary_member_verdict = left, right, "merge_all"
        elif secondary_verdict == "subset":
            secondary_member_verdict = "merge_subset"
        elif secondary_verdict == "keep_separate":
            secondary_selected_left, secondary_selected_right, secondary_member_verdict = [], [], "keep_separate"
        else:
            secondary_member_verdict = None
        return self._row(
            merge_id=str(operation["operation_id"]),
            operation_kind=f"explicit_{verdict}",
            source_report_ids=[left_report, right_report],
            left_report_id=left_report,
            right_report_id=right_report,
            left=left,
            right=right,
            selected_left=selected_left,
            selected_right=selected_right,
            verdict=member_verdict,
            secondary_selected_left=secondary_selected_left,
            secondary_selected_right=secondary_selected_right,
            secondary_verdict=secondary_member_verdict,
            secondary_reader=cast(str | None, operation.get("secondary_reader")),
            weight=float(cast(float, operation["confidence"])),
            provenance=str(operation["provenance"]),
        )

    @staticmethod
    def _row(
        *,
        merge_id: str,
        operation_kind: str,
        source_report_ids: list[str],
        left_report_id: str,
        right_report_id: str,
        left: list[str],
        right: list[str],
        selected_left: list[str],
        selected_right: list[str],
        verdict: str,
        secondary_selected_left: list[str],
        secondary_selected_right: list[str],
        secondary_verdict: str | None,
        secondary_reader: str | None = "synthetic_deterministic",
        weight: float,
        provenance: str,
    ) -> dict[str, object]:
        left_indices, right_indices, components = BuildShufflerCurriculum._components(
            left, right, selected_left, selected_right, operation_kind
        )
        secondary_left_indices, secondary_right_indices, secondary_components = BuildShufflerCurriculum._components(
            left, right, secondary_selected_left, secondary_selected_right, operation_kind
        )
        has_secondary_reader = secondary_verdict is not None and secondary_reader is not None
        primary_pairs = {(left_index, right_index) for left_index in left_indices for right_index in right_indices}
        secondary_pairs = {
            (left_index, right_index)
            for left_index in secondary_left_indices
            for right_index in secondary_right_indices
        }
        union = primary_pairs | secondary_pairs
        pair_jaccard = len(primary_pairs & secondary_pairs) / len(union) if union else 1.0
        verdict_agreement = has_secondary_reader and verdict == secondary_verdict
        exact_agreement = verdict_agreement and components == secondary_components
        return {
            "merge_id": merge_id,
            "policy": provenance,
            "operation_kind": operation_kind,
            "source_report_ids": json.dumps(source_report_ids, separators=(",", ":")),
            "left_report_id": left_report_id,
            "right_report_id": right_report_id,
            "left_members": json.dumps(left, separators=(",", ":")),
            "right_members": json.dumps(right, separators=(",", ":")),
            "left_size": len(left),
            "right_size": len(right),
            "verdict": verdict,
            "whole_merge_safe": verdict == "merge_all",
            "subset_rescue": verdict == "merge_subset",
            "reports_related": verdict != "keep_separate",
            "left_matching_share": len(left_indices) / max(len(left), 1),
            "right_matching_share": len(right_indices) / max(len(right), 1),
            "shared_concern": operation_kind if verdict != "keep_separate" else "",
            "label_reason": operation_kind,
            "label_confidence": "numeric",
            "label_source": provenance,
            "training_weight": weight,
            "member_verdict": verdict,
            "member_components": json.dumps(components, separators=(",", ":")),
            "sonnet_member_components": json.dumps(secondary_components, separators=(",", ":")),
            "secondary_member_verdict": secondary_verdict,
            "secondary_reader": secondary_reader if has_secondary_reader else None,
            "has_secondary_reader": has_secondary_reader,
            "exact_left_matching_share": len(left_indices) / max(len(left), 1),
            "exact_right_matching_share": len(right_indices) / max(len(right), 1),
            "member_component_count": len(components),
            "member_label_reason": operation_kind,
            "member_label_confidence": "numeric",
            "member_label_source": provenance,
            "member_labels_known": True,
            "member_label_tier": "deterministic_pair_operation",
            "strict_consensus_eligible": exact_agreement,
            "stable_overlap_eligible": verdict_agreement,
            "reader_verdict_agreement": verdict_agreement,
            "reader_exact_component_agreement": exact_agreement,
            "reader_cross_pair_jaccard": pair_jaccard if has_secondary_reader else None,
        }

    @staticmethod
    def _components(
        left: list[str],
        right: list[str],
        selected_left: list[str],
        selected_right: list[str],
        concern: str,
    ) -> tuple[list[int], list[int], list[dict[str, object]]]:
        selected_left_set = set(selected_left)
        selected_right_set = set(selected_right)
        left_indices = [index for index, member in enumerate(left) if member in selected_left_set]
        right_indices = [index for index, member in enumerate(right) if member in selected_right_set]
        if not left_indices or not right_indices:
            return left_indices, right_indices, []
        return (
            left_indices,
            right_indices,
            [
                {
                    "concern": concern,
                    "left_indices": left_indices,
                    "right_indices": right_indices,
                    "left_ids": [left[index] for index in left_indices],
                    "right_ids": [right[index] for index in right_indices],
                }
            ],
        )

    @staticmethod
    def _triangles(edges: set[tuple[str, str]]) -> set[tuple[str, str, str]]:
        adjacency: dict[str, set[str]] = {}
        for left, right in edges:
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)
        triangles: set[tuple[str, str, str]] = set()
        for left in sorted(adjacency):
            for middle in sorted(value for value in adjacency[left] if value > left):
                for right in sorted(value for value in adjacency[left] & adjacency[middle] if value > middle):
                    triangles.add((left, middle, right))
        return triangles

    @staticmethod
    def _component_group_count(frame: pd.DataFrame) -> int:
        parent: dict[str, str] = {}

        def find(value: str) -> str:
            parent.setdefault(value, value)
            if parent[value] != value:
                parent[value] = find(parent[value])
            return parent[value]

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        sources: list[list[str]] = []
        for value in frame["source_report_ids"]:
            source_ids = [str(source_id) for source_id in json.loads(str(value))]
            if not source_ids:
                continue
            sources.append(source_ids)
            for source_id in source_ids[1:]:
                union(source_ids[0], source_id)
        return len({find(source_ids[0]) for source_ids in sources})

    @staticmethod
    def _id(*values: str) -> str:
        return hashlib.blake2b("\x1f".join(values).encode(), digest_size=12).hexdigest()
