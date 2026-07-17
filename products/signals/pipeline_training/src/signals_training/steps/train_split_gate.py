from __future__ import annotations

from pathlib import Path

from ..io import JsonObject
from ..lineage import builder_script, python, run_logged, training_engine, write_engine_config
from ..stage import StageContext


class TrainSplitGate:
    name = "train_split_gate"

    def input_paths(self, context: StageContext) -> list[Path]:
        cuts = context.stage_dir("build_cut_surface")
        return [
            cuts / "cuts.jsonl",
            cuts / "labels.parquet",
            context.stage_dir("materialize_corpora") / "train",
            context.stage_dir("train_pair") / "models-pair.json",
            context.stage_dir("train_pair") / "pair.pkl",
            context.stage_dir("train_groupjoin") / "groupjoin_stack.pkl",
            training_engine(context),
            builder_script("train_gate.py"),
            builder_script("export_models.py"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "cut-features.jsonl", directory / "concern.pkl", directory / "models-stack.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "recipe": "depth-3 HistGradientBoosting plus report-disjoint isotonic cross-fit",
            "target": "coherence, where one means do not cut",
        }

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        cuts = context.stage_dir("build_cut_surface")
        corpus = context.stage_dir("materialize_corpora") / "train"
        feature_config = directory / "feature-config.json"
        write_engine_config(
            feature_config,
            corpus,
            models=str((context.stage_dir("train_pair") / "models-pair.json").resolve()),
            cuts_in=str((cuts / "cuts.jsonl").resolve()),
            cuts_out=str((directory / "cut-features.jsonl").resolve()),
        )
        run_logged(
            context,
            self.name,
            [str(training_engine(context)), "featurize-cuts", str(feature_config)],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("train_gate.py")),
                "--features",
                str(directory / "cut-features.jsonl"),
                "--labels",
                str(cuts / "labels.parquet"),
                "--out",
                str(directory / "concern.pkl"),
            ],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("export_models.py")),
                "--pair",
                str(context.stage_dir("train_pair") / "pair.pkl"),
                "--groupjoin",
                str(context.stage_dir("train_groupjoin") / "groupjoin_stack.pkl"),
                "--concern",
                str(directory / "concern.pkl"),
                "--burst-corpus",
                str(corpus),
                "--out",
                str(directory / "models-stack.json"),
            ],
        )
