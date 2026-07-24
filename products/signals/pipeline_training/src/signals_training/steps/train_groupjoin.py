from __future__ import annotations

from pathlib import Path

from ..io import JsonObject
from ..lineage import builder_script, integer_setting, python, run_logged, string_setting
from ..stage import StageContext
from .build_groupjoin_surface import BuildGroupJoinSurface

BUILDERS = (
    "train_groupjoin.py",
    "train_groupjoin_neural.py",
    "finalize_groupjoin_stack.py",
    "export_groupjoin_onnx.py",
    "export_models.py",
)


class TrainGroupJoin:
    name = "train_groupjoin"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            *BuildGroupJoinSurface().output_paths(context),
            context.stage_dir("train_pair") / "pair.pkl",
            context.stage_dir("materialize_corpora") / "train",
            context.stage_dir("materialize_corpora") / "train" / "document_groups.json",
            *(builder_script(name) for name in BUILDERS),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "groupjoin_stack.pkl",
            directory / "models-stack.json",
            directory / "groupjoin_direct.pt",
            directory / "groupjoin_direct_metrics.json",
            directory / "groupjoin_direct_oof.npz",
            directory / "groupjoin_direct.onnx",
            directory / "groupjoin_direct.manifest.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "tree": "HistGradientBoosting depth 3",
            "neural": "DeepSets direct head with 32 pooled dimensions",
            "epochs": integer_setting(context.config, "groupjoin_epochs"),
            "patience": integer_setting(context.config, "groupjoin_patience"),
            "batch_size": integer_setting(context.config, "groupjoin_batch_size"),
            "device": string_setting(context.config, "device"),
            "fold_boundary": "explicit clone-linkage groups produced by split_territories",
        }

    def run(self, context: StageContext) -> None:
        source = context.stage_dir("build_groupjoin_surface")
        directory = context.stage_dir(self.name)
        for name in (
            "groupjoin_frame.parquet",
            "groupjoin_features.parquet",
            "groupjoin_neural.npz",
            "groupjoin_frame_summary.json",
        ):
            (directory / name).symlink_to((source / name).resolve())
        tree = directory / "groupjoin_tree.pkl"
        run_logged(
            context,
            self.name,
            [
                *self._builder(context, "train_groupjoin.py"),
                "--build",
                str(directory),
                "--out",
                str(tree),
                "--exclude-mixed",
            ],
        )
        base_models = directory / "models-tree.json"
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("export_models.py")),
                "--pair",
                str(context.stage_dir("train_pair") / "pair.pkl"),
                "--groupjoin",
                str(tree),
                "--burst-corpus",
                str(context.stage_dir("materialize_corpora") / "train"),
                "--out",
                str(base_models),
            ],
        )
        neural_command = [
            *self._builder(context, "train_groupjoin_neural.py"),
            "--build",
            str(directory),
            "--max-epochs",
            str(integer_setting(context.config, "groupjoin_epochs")),
            "--patience",
            str(integer_setting(context.config, "groupjoin_patience")),
            "--batch-size",
            str(integer_setting(context.config, "groupjoin_batch_size")),
        ]
        device = string_setting(context.config, "device")
        if device != "auto":
            neural_command.extend(("--device", device))
        run_logged(context, self.name, neural_command)
        run_logged(
            context,
            self.name,
            [
                *self._builder(context, "finalize_groupjoin_stack.py"),
                "--build",
                str(directory),
                "--base-models",
                str(base_models),
                "--out-model",
                str(directory / "groupjoin_stack.pkl"),
                "--out-models",
                str(directory / "models-stack.json"),
            ],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("export_groupjoin_onnx.py")),
                "--build",
                str(directory),
                "--variant",
                "binary",
            ],
        )

    @staticmethod
    def _builder(context: StageContext, script: str) -> list[str]:
        return [
            python(context),
            str(builder_script(script)),
            "--document-groups",
            str(context.stage_dir("materialize_corpora") / "train" / "document_groups.json"),
        ]
