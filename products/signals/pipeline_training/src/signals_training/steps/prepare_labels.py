from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ..corpus import Corpus
from ..io import JsonObject, canonical_json, read_jsonl, write_json, write_jsonl
from ..stage import StageContext

LABEL_FILES = ("pairs.jsonl", "reports.jsonl", "operations.jsonl")


class PrepareLabels:
    name = "prepare_labels"

    def input_paths(self, context: StageContext) -> list[Path]:
        split = context.stage_dir("split_territories")
        clean = context.stage_dir("clean_corpus")
        return [
            split / "assignments.jsonl",
            clean / "signals.jsonl",
            clean / "reports.jsonl",
            context.config.inputs["pair_labels"],
            context.config.inputs["report_labels"],
            context.config.inputs["operation_labels"],
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        names = self._names(context)
        return [
            *(directory / name / filename for name in names for filename in LABEL_FILES),
            directory / "excluded.jsonl",
            directory / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"territories": list(self._names(context)), "unknowns_become_negatives": False}

    def run(self, context: StageContext) -> None:
        clean = context.stage_dir("clean_corpus")
        corpus = Corpus.load(clean / "signals.jsonl", clean / "reports.jsonl")
        assignment_rows = [
            row for _line, row in read_jsonl(context.stage_dir("split_territories") / "assignments.jsonl")
        ]
        territory_of_report = {str(row["report_id"]): str(row["territory"]) for row in assignment_rows}
        output: dict[str, dict[str, list[JsonObject]]] = {
            name: {filename: [] for filename in LABEL_FILES} for name in self._names(context)
        }
        excluded: list[JsonObject] = []

        pairs = self._normalize_pairs(context.config.inputs["pair_labels"])
        self._mark_conflicts(pairs, key_fields=("signal_a", "signal_b"), value_fields=("same_concern",))
        for row in pairs:
            left = str(row["signal_a"])
            right = str(row["signal_b"])
            if left not in corpus.report_of or right not in corpus.report_of:
                excluded.append({"label_kind": "pair", "reason": "outside_clean_corpus", "label": row})
                continue
            left_territory = territory_of_report[corpus.report_of[left]]
            right_territory = territory_of_report[corpus.report_of[right]]
            if left_territory != right_territory:
                excluded.append(
                    {
                        "label_kind": "pair",
                        "reason": "cross_territory",
                        "territories": [left_territory, right_territory],
                        "label": row,
                    }
                )
                continue
            output[left_territory]["pairs.jsonl"].append(row)

        reports = self._deduplicate(context.config.inputs["report_labels"], self._identity)
        self._mark_conflicts(
            reports,
            key_fields=("report_id",),
            value_fields=("coherent", "gold_positive", "known_overgroup", "outcome"),
        )
        for row in reports:
            report_id = str(row["report_id"])
            territory = territory_of_report.get(report_id)
            if territory is None:
                excluded.append({"label_kind": "report", "reason": "outside_clean_corpus", "label": row})
                continue
            output[territory]["reports.jsonl"].append(row)

        operations = self._normalize_operations(context.config.inputs["operation_labels"])
        self._mark_conflicts(
            operations,
            key_fields=("left_report_id", "right_report_id"),
            value_fields=("verdict", "selected_left", "selected_right"),
        )
        for row in operations:
            left = str(row["left_report_id"])
            right = str(row["right_report_id"])
            if left not in territory_of_report or right not in territory_of_report:
                excluded.append({"label_kind": "operation", "reason": "outside_clean_corpus", "label": row})
                continue
            left_territory = territory_of_report[left]
            right_territory = territory_of_report[right]
            if left_territory != right_territory:
                excluded.append(
                    {
                        "label_kind": "operation",
                        "reason": "cross_territory",
                        "territories": [left_territory, right_territory],
                        "label": row,
                    }
                )
                continue
            output[left_territory]["operations.jsonl"].append(row)

        directory = context.stage_dir(self.name)
        counts: dict[str, dict[str, int]] = {}
        for territory, files in output.items():
            counts[territory] = {}
            for filename, rows in files.items():
                ordered = sorted(rows, key=lambda row: str(row["label_id"]))
                write_jsonl(directory / territory / filename, ordered)
                counts[territory][filename] = len(ordered)
        write_jsonl(directory / "excluded.jsonl", excluded)
        excluded_reasons = Counter(str(row["reason"]) for row in excluded)
        write_json(
            directory / "summary.json",
            {
                "counts": counts,
                "excluded": len(excluded),
                "excluded_reasons": dict(sorted(excluded_reasons.items())),
                "conflicting_judgments_preserved": sum(
                    bool(row.get("has_conflict"))
                    for territory in output.values()
                    for rows in territory.values()
                    for row in rows
                ),
                "firewall": "No validation label is copied into the train territory.",
            },
        )

    @staticmethod
    def _identity(row: JsonObject) -> JsonObject:
        return dict(row)

    def _normalize_pairs(self, path: Path) -> list[JsonObject]:
        def normalize(row: JsonObject) -> JsonObject:
            result = dict(row)
            left = str(result["signal_a"])
            right = str(result["signal_b"])
            result["signal_a"], result["signal_b"] = sorted((left, right))
            return result

        return self._deduplicate(path, normalize)

    def _normalize_operations(self, path: Path) -> list[JsonObject]:
        def normalize(row: JsonObject) -> JsonObject:
            result = dict(row)
            left = str(result["left_report_id"])
            right = str(result["right_report_id"])
            if left > right:
                result["left_report_id"], result["right_report_id"] = right, left
                result["selected_left"], result["selected_right"] = (
                    result.get("selected_right", []),
                    result.get("selected_left", []),
                )
                result["secondary_selected_left"], result["secondary_selected_right"] = (
                    result.get("secondary_selected_right", []),
                    result.get("secondary_selected_left", []),
                )
            for field in (
                "selected_left",
                "selected_right",
                "secondary_selected_left",
                "secondary_selected_right",
            ):
                if isinstance(result.get(field), list):
                    result[field] = sorted(cast(list[str], result[field]))
            return result

        return self._deduplicate(path, normalize)

    @staticmethod
    def _deduplicate(path: Path, normalizer: Callable[[JsonObject], JsonObject]) -> list[JsonObject]:
        unique: dict[str, JsonObject] = {}
        for _line, source in read_jsonl(path):
            row = normalizer(source)
            content = canonical_json(row)
            label_id = hashlib.sha256(content.encode()).hexdigest()
            row["label_id"] = label_id
            unique[label_id] = row
        return [unique[label_id] for label_id in sorted(unique)]

    @staticmethod
    def _mark_conflicts(rows: list[JsonObject], *, key_fields: tuple[str, ...], value_fields: tuple[str, ...]) -> None:
        grouped: dict[tuple[str, ...], list[JsonObject]] = defaultdict(list)
        for row in rows:
            grouped[tuple(canonical_json(row.get(field)) for field in key_fields)].append(row)
        for key, group in grouped.items():
            verdicts = {tuple(canonical_json(row.get(field)) for field in value_fields) for row in group}
            conflict_id = hashlib.sha256(canonical_json([*key]).encode()).hexdigest()[:16]
            for row in group:
                row["has_conflict"] = len(verdicts) > 1
                row["conflict_group_id"] = conflict_id if len(verdicts) > 1 else None

    @staticmethod
    def _names(context: StageContext) -> tuple[str, str, str]:
        value = context.config.territories.get("names")
        if not isinstance(value, list) or len(value) != 3 or any(not isinstance(item, str) for item in value):
            raise ValueError("territories.names must contain exactly three strings")
        names = cast(list[str], value)
        return names[0], names[1], names[2]
