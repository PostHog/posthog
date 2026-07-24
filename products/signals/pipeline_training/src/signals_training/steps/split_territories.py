from __future__ import annotations

from pathlib import Path
from typing import cast

from ..corpus import Corpus
from ..io import JsonObject, read_jsonl, write_json, write_jsonl
from ..stage import StageContext
from ..territories import build_linkage_groups, deal_groups, territory_profile


class SplitTerritories:
    name = "split_territories"

    def input_paths(self, context: StageContext) -> list[Path]:
        clean = context.stage_dir("clean_corpus")
        return [clean / "signals.jsonl", clean / "reports.jsonl", context.config.inputs["report_links"]]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        names = self._names(context)
        return [
            directory / "assignments.jsonl",
            directory / "cross_territory_links.jsonl",
            directory / "balance.json",
            *(directory / name for name in names),
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"seed": context.config.seed, **cast(JsonObject, context.config.territories)}

    def run(self, context: StageContext) -> None:
        configuration = context.config.territories
        names = self._names(context)
        link_threshold = self._number(configuration, "clone_link_cosine")
        overlap_threshold = self._number(configuration, "clone_link_min_smaller_overlap")
        residual_threshold = self._number(configuration, "residual_link_cosine")
        annex_fraction = self._number(configuration, "annex_fraction")
        swap_iterations = self._integer(configuration, "swap_iterations")

        clean = context.stage_dir("clean_corpus")
        corpus = Corpus.load(clean / "signals.jsonl", clean / "reports.jsonl")
        links = [row for _line, row in read_jsonl(context.config.inputs["report_links"])]
        groups = build_linkage_groups(
            corpus,
            links,
            cosine_threshold=link_threshold,
            minimum_smaller_overlap=overlap_threshold,
        )
        annex_cutoff = annex_fraction * len(corpus.signals)
        annex_groups = [group for group in groups if group.signal_count > annex_cutoff]
        dealt_groups = [group for group in groups if group.signal_count <= annex_cutoff]
        territory_of_group = deal_groups(
            dealt_groups,
            names,
            seed=context.config.seed,
            swap_iterations=swap_iterations,
        )
        territory_of_group.update({group.group_id: names[0] for group in annex_groups})

        assignment_rows: list[JsonObject] = []
        territory_of_report: dict[str, str] = {}
        group_of_report: dict[str, str] = {}
        annex_ids = {group.group_id for group in annex_groups}
        for group in sorted(groups, key=lambda item: item.group_id):
            territory = territory_of_group[group.group_id]
            for report_id in group.report_ids:
                territory_of_report[report_id] = territory
                group_of_report[report_id] = group.group_id
                assignment_rows.append(
                    {
                        "report_id": report_id,
                        "territory": territory,
                        "linkage_group_id": group.group_id,
                        "annex": group.group_id in annex_ids,
                    }
                )

        cross_links: list[JsonObject] = []
        for link in links:
            left = str(link["report_a"])
            right = str(link["report_b"])
            if left not in territory_of_report or right not in territory_of_report:
                continue
            left_territory = territory_of_report[left]
            right_territory = territory_of_report[right]
            if float(link["max_cosine"]) >= residual_threshold and left_territory != right_territory:
                cross_links.append(
                    {
                        **link,
                        "territory_a": left_territory,
                        "territory_b": right_territory,
                    }
                )

        directory = context.stage_dir(self.name)
        write_jsonl(directory / "assignments.jsonl", assignment_rows)
        write_jsonl(
            directory / "cross_territory_links.jsonl",
            sorted(cross_links, key=lambda row: (str(row["report_a"]), str(row["report_b"]))),
        )
        profiles: dict[str, JsonObject] = {}
        for name in names:
            report_ids = {report_id for report_id, territory in territory_of_report.items() if territory == name}
            selected = corpus.selected(report_ids)
            write_jsonl(directory / name / "signals.jsonl", selected.sorted_signals())
            write_jsonl(directory / name / "reports.jsonl", selected.sorted_reports())
            profiles[name] = territory_profile(corpus, report_ids)
        write_json(
            directory / "balance.json",
            {
                "seed": context.config.seed,
                "territories": profiles,
                "linkage": {
                    "groups": len(groups),
                    "multi_report_groups": sum(len(group.report_ids) > 1 for group in groups),
                    "annex_groups": [group.group_id for group in annex_groups],
                    "annex_signals": sum(group.signal_count for group in annex_groups),
                    "residual_cross_territory_links": len(cross_links),
                },
            },
        )

    @staticmethod
    def _names(context: StageContext) -> tuple[str, str, str]:
        value = context.config.territories.get("names")
        if not isinstance(value, list) or len(value) != 3 or any(not isinstance(item, str) for item in value):
            raise ValueError("territories.names must contain exactly three strings")
        names = cast(list[str], value)
        if len(set(names)) != 3 or names[0] != "train":
            raise ValueError("territories.names must contain three unique names with train first")
        return names[0], names[1], names[2]

    @staticmethod
    def _number(values: dict[str, object], name: str) -> float:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"territories.{name} must be numeric")
        return float(value)

    @staticmethod
    def _integer(values: dict[str, object], name: str) -> int:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"territories.{name} must be an integer")
        return value
