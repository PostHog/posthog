from __future__ import annotations

from pathlib import Path

from ..io import JsonObject, write_json
from ..lineage import run_logged, training_engine, write_engine_config
from ..stage import StageContext

REGIMES = (
    ("raw082-id10", 0.82, 10),
    ("raw086-id10", 0.86, 10),
    ("raw090-id10", 0.90, 10),
    ("raw086-id0", 0.86, 0),
)


class HarvestGroupJoin:
    name = "harvest_groupjoin"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("materialize_corpora") / "train",
            context.stage_dir("train_pair") / "models-pair.json",
            training_engine(context),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            *(directory / "harvest" / name / "decisions.jsonl" for name, _threshold, _lane in REGIMES),
            directory / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "regimes": [
                {"name": name, "classifier_raw_tau": threshold, "id_lane_limit": lane}
                for name, threshold, lane in REGIMES
            ],
            "candidate_state_contract": "exact decision-time report membership",
        }

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        corpus = context.stage_dir("materialize_corpora") / "train"
        models = context.stage_dir("train_pair") / "models-pair.json"
        summaries: list[JsonObject] = []
        for name, threshold, lane in REGIMES:
            output = directory / "harvest" / name
            configuration = directory / "configs" / f"{name}.json"
            write_engine_config(
                configuration,
                corpus,
                models=str(models.resolve()),
                classifier_raw_tau=threshold,
                id_lane_limit=lane,
                use_groupjoin=False,
                use_concern=False,
                emit_candidate_report_states=True,
            )
            run_logged(
                context,
                self.name,
                [str(training_engine(context)), "replay", str(configuration), str(output)],
            )
            decisions = sum(1 for line in (output / "decisions.jsonl").open() if line.strip())
            summaries.append(
                {
                    "name": name,
                    "classifier_raw_tau": threshold,
                    "id_lane_limit": lane,
                    "decisions": decisions,
                }
            )
        write_json(directory / "summary.json", {"regimes": summaries})
