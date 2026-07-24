from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import cast

import numpy as np

from ..corpus import BAND_ORDER, Corpus, has_scout_bypass, report_statistics
from ..io import JsonObject, write_json, write_jsonl
from ..stage import StageContext


class CleanCorpus:
    name = "clean_corpus"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("validate_inputs") / "audit.json",
            context.config.inputs["signals"],
            context.config.inputs["reports"],
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "signals.jsonl", directory / "reports.jsonl", directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return cast(JsonObject, context.config.cleaning)

    def run(self, context: StageContext) -> None:
        cleaning = context.config.cleaning
        sampling_seed = self._integer(cleaning, "sampling_seed")
        monster_cap = self._integer(cleaning, "monster_cap")
        target = self._integer(cleaning, "error_tracking_signal_target")
        error_tracking_product = self._string(cleaning, "error_tracking_product")
        exclude_scout = cleaning.get("exclude_scout_bypass_reports")
        if not isinstance(exclude_scout, bool):
            raise ValueError("cleaning.exclude_scout_bypass_reports must be boolean")

        corpus = Corpus.load(context.config.inputs["signals"], context.config.inputs["reports"])
        statistics = {
            report_id: report_statistics(corpus, report_id, error_tracking_product)
            for report_id in sorted(corpus.reports)
        }
        monster_ids = {report_id for report_id, row in statistics.items() if int(cast(int, row["n"])) > monster_cap}
        eligible = set(corpus.reports) - monster_ids
        scout_ids = (
            {report_id for report_id in eligible if has_scout_bypass(corpus, report_id)} if exclude_scout else set()
        )
        eligible -= scout_ids

        non_error_tracking = {
            report_id for report_id in eligible if not bool(statistics[report_id]["error_tracking_only"])
        }
        error_tracking_by_band: dict[str, list[str]] = defaultdict(list)
        for report_id in sorted(eligible - non_error_tracking):
            error_tracking_by_band[str(statistics[report_id]["band"])].append(report_id)

        rng = np.random.default_rng(sampling_seed)
        shuffled: dict[str, list[str]] = {}
        for band in BAND_ORDER:
            values = error_tracking_by_band[band]
            permutation = rng.permutation(len(values))
            shuffled[band] = [values[int(index)] for index in permutation]

        maximum = max((len(values) for values in shuffled.values()), default=0)

        def sampled_signal_count(count: int) -> int:
            return sum(int(statistics[report_id]["n"]) for band in BAND_ORDER for report_id in shuffled[band][:count])

        reports_per_band = min(range(maximum + 1), key=lambda count: abs(sampled_signal_count(count) - target))
        sampled = {report_id for band in BAND_ORDER for report_id in shuffled[band][:reports_per_band]}
        selected_ids = non_error_tracking | sampled
        selected = corpus.selected(selected_ids)

        enriched_reports: list[JsonObject] = []
        for report_id in sorted(selected.reports):
            enriched_reports.append({**selected.reports[report_id], **statistics[report_id]})

        directory = context.stage_dir(self.name)
        write_jsonl(directory / "signals.jsonl", selected.sorted_signals())
        write_jsonl(directory / "reports.jsonl", enriched_reports)
        write_json(
            directory / "summary.json",
            {
                "source_reports": len(corpus.reports),
                "source_signals": len(corpus.signals),
                "selected_reports": len(selected.reports),
                "selected_signals": len(selected.signals),
                "excluded_monster_reports": {
                    report_id: int(statistics[report_id]["n"]) for report_id in sorted(monster_ids)
                },
                "excluded_scout_bypass_reports": len(scout_ids),
                "all_non_error_tracking_reports_retained": len(non_error_tracking),
                "error_tracking_sampling": {
                    "seed": sampling_seed,
                    "target_signals": target,
                    "reports_per_band": reports_per_band,
                    "achieved_signals": sampled_signal_count(reports_per_band),
                    "bands": {
                        band: {
                            "available_reports": len(shuffled[band]),
                            "sampled_reports": min(reports_per_band, len(shuffled[band])),
                            "sampled_signals": sum(
                                int(statistics[report_id]["n"]) for report_id in shuffled[band][:reports_per_band]
                            ),
                        }
                        for band in BAND_ORDER
                    },
                },
            },
        )

    @staticmethod
    def _integer(values: dict[str, object], name: str) -> int:
        value = values.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"cleaning.{name} must be an integer")
        return value

    @staticmethod
    def _string(values: dict[str, object], name: str) -> str:
        value = values.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"cleaning.{name} must be a non-empty string")
        return value
