from __future__ import annotations

from pathlib import Path

from ..io import JsonObject
from ..lineage import builder_script, python, run_logged, training_engine, write_engine_config
from ..stage import StageContext


class TrainPair:
    name = "train_pair"

    def input_paths(self, context: StageContext) -> list[Path]:
        pair = context.stage_dir("build_pair_surface")
        corpus = context.stage_dir("materialize_corpora") / "train"
        return [
            pair / "frame.parquet",
            pair / "pairs.jsonl",
            corpus,
            training_engine(context),
            builder_script("train_pair.py"),
            builder_script("export_models.py"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "features.jsonl", directory / "pair.pkl", directory / "models-pair.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"recipe": "source-pinned-v19", "cross_fit": "positive-component-disjoint fold pairs"}

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        pair = context.stage_dir("build_pair_surface")
        corpus = context.stage_dir("materialize_corpora") / "train"
        feature_config = directory / "feature-config.json"
        write_engine_config(
            feature_config,
            corpus,
            featurize_pairs=str((pair / "pairs.jsonl").resolve()),
            featurize_out=str((directory / "features.jsonl").resolve()),
        )
        run_logged(
            context,
            self.name,
            [str(training_engine(context)), "featurize-pairs", str(feature_config)],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("train_pair.py")),
                "--features",
                str(directory / "features.jsonl"),
                "--frame",
                str(pair / "frame.parquet"),
                "--out",
                str(directory / "pair.pkl"),
            ],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("export_models.py")),
                "--pair",
                str(directory / "pair.pkl"),
                "--burst-corpus",
                str(corpus),
                "--out",
                str(directory / "models-pair.json"),
            ],
        )
