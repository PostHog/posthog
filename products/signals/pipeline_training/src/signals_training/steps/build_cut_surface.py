from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd

from ..corpus import Corpus
from ..io import JsonObject, canonical_json, parse_epoch, read_jsonl, write_json, write_jsonl
from ..stage import StageContext
from ..surface_evidence import stable_rank


class BuildCutSurface:
    name = "build_cut_surface"

    def input_paths(self, context: StageContext) -> list[Path]:
        train = context.stage_dir("split_territories") / "train"
        labels = context.stage_dir("prepare_labels") / "train"
        return [
            train / "signals.jsonl",
            train / "reports.jsonl",
            labels / "reports.jsonl",
            context.stage_dir("build_pair_surface") / "frame.parquet",
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "cuts.jsonl", directory / "labels.parquet", directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "coherent_cuts_per_report": context.config.surfaces.get("coherent_cuts_per_report"),
            "cut_weight_cap": 3.0,
        }

    def run(self, context: StageContext) -> None:
        train = context.stage_dir("split_territories") / "train"
        corpus = Corpus.load(train / "signals.jsonl", train / "reports.jsonl")
        report_labels = [
            row for _line, row in read_jsonl(context.stage_dir("prepare_labels") / "train" / "reports.jsonl")
        ]
        pair_frame = pd.read_parquet(context.stage_dir("build_pair_surface") / "frame.parquet")
        positive_pairs = {
            tuple(sorted((str(row.doc_a), str(row.doc_b))))
            for row in pair_frame.loc[pair_frame["y"]].itertuples(index=False)
        }
        negative_pairs = {
            tuple(sorted((str(row.doc_a), str(row.doc_b))))
            for row in pair_frame.loc[~pair_frame["y"]].itertuples(index=False)
        }
        proposals: list[tuple[str, list[str], list[str], bool, float, str]] = []
        seen: set[str] = set()

        def add(
            report_id: str,
            left: list[str],
            right: list[str],
            good_cut: bool,
            weight: float,
            source: str,
        ) -> None:
            if not left or not right:
                return
            canonical_sides = sorted((sorted(left), sorted(right)))
            key = canonical_json([report_id, canonical_sides])
            if key in seen:
                return
            seen.add(key)
            proposals.append((report_id, left, right, good_cut, min(weight, 3.0), source))

        labels_by_report: dict[str, list[JsonObject]] = {}
        for row in report_labels:
            labels_by_report.setdefault(str(row["report_id"]), []).append(row)
            components = row.get("components")
            if row.get("known_overgroup") is True and isinstance(components, list):
                members = set(corpus.signal_ids(str(row["report_id"])))
                for component in cast(list[list[str]], components):
                    selected = set(component)
                    add(
                        str(row["report_id"]),
                        sorted(selected),
                        sorted(members - selected),
                        True,
                        float(cast(float, row["confidence"])),
                        "exact_report_components",
                    )

        for report_id in sorted(corpus.reports):
            members = corpus.signal_ids(report_id)
            if len(members) < 2:
                continue
            member_set = set(members)
            for left, right in sorted(negative_pairs):
                if left not in member_set or right not in member_set:
                    continue
                side = self._positive_component(left, member_set, positive_pairs)
                if right in side or side == member_set:
                    continue
                add(report_id, sorted(side), sorted(member_set - side), True, 1.0, "atomic_pair_projection")

            coherent = [
                row
                for row in labels_by_report.get(report_id, [])
                if row.get("coherent") is True or row.get("gold_positive") is True
            ]
            if coherent:
                count_value = context.config.surfaces.get("coherent_cuts_per_report")
                if isinstance(count_value, bool) or not isinstance(count_value, int):
                    raise ValueError("surfaces.coherent_cuts_per_report must be an integer")
                confidence = max(float(cast(float, row["confidence"])) for row in coherent)
                for repeat in range(count_value):
                    ordered = sorted(
                        members,
                        key=lambda value: stable_rank("coherent-cut", report_id, str(repeat), value),
                    )
                    left = ordered[::2]
                    right = ordered[1::2]
                    add(report_id, left, right, False, 0.8 * confidence, "coherent_report")

        if not proposals or not {value[3] for value in proposals} == {False, True}:
            raise ValueError("cut surface requires both good and bad cut supervision")
        proposals.sort(key=lambda value: (value[0], stable_rank(value[5], *value[1], *value[2])))
        cuts: list[JsonObject] = []
        labels: list[JsonObject] = []
        for index, (report_id, left, right, good, weight, source) in enumerate(proposals):
            members = left + right
            trigger = max(
                members,
                key=lambda member: (
                    parse_epoch(corpus.signals[member].get("timestamp"), f"signal {member}.timestamp"),
                    member,
                ),
            )
            cuts.append(
                {
                    "trigger": trigger,
                    "report_id": report_id,
                    "true_size": len(corpus.signal_ids(report_id)),
                    "members_a": left,
                    "members_b": right,
                    "provenance": [],
                    "label_source": source,
                }
            )
            labels.append(
                {
                    "cut_id": f"cuts.jsonl#{index}",
                    "report_id": report_id,
                    "y": good,
                    "weight": weight,
                    "n_a": len(left),
                    "n_b": len(right),
                    "harvest": "pipeline-training-deterministic",
                    "label_source": source,
                }
            )
        directory = context.stage_dir(self.name)
        write_jsonl(directory / "cuts.jsonl", cuts)
        pd.DataFrame(labels).to_parquet(directory / "labels.parquet", index=False)
        write_json(
            directory / "summary.json",
            {
                "cuts": len(labels),
                "good": sum(bool(row["y"]) for row in labels),
                "bad": sum(not bool(row["y"]) for row in labels),
                "reports": len({str(row["report_id"]) for row in labels}),
                "sources": {
                    str(source): int(count)
                    for source, count in pd.Series([row["label_source"] for row in labels]).value_counts().items()
                },
            },
        )

    @staticmethod
    def _positive_component(start: str, members: set[str], positive_pairs: set[tuple[str, str]]) -> set[str]:
        component = {start}
        changed = True
        while changed:
            changed = False
            for left, right in positive_pairs:
                if left not in members or right not in members:
                    continue
                if (left in component) != (right in component):
                    component.update((left, right))
                    changed = True
        return component
