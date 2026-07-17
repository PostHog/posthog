from __future__ import annotations

from pathlib import Path

from ..io import JsonObject
from ..lineage import builder_script, integer_setting, python, run_logged, string_setting
from ..stage import StageContext
from .build_shuffler_substrate import BuildShufflerSubstrate


class TrainShuffler:
    name = "train_shuffler"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("build_shuffler_curriculum") / "labels.parquet",
            context.stage_dir("build_shuffler_curriculum") / "human_labels.parquet",
            *BuildShufflerSubstrate().output_paths(context),
            context.stage_dir("materialize_corpora") / "train",
            builder_script("train_integrated_report_shuffler.py"),
            builder_script("export_integrated_report_shuffler.py"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        exported = directory / "exported"
        return [
            directory / "pretrain" / "integrated_report_shuffler.pt",
            directory / "pretrain" / "integrated_report_shuffler_metrics.json",
            directory / "fine_tune" / "integrated_report_shuffler.pt",
            directory / "fine_tune" / "integrated_report_shuffler_metrics.json",
            exported / "integrated_report_shuffler.manifest.json",
            *(
                exported / f"integrated_late_interaction_report_shuffler_{width}.onnx"
                for width in (8, 32, 64, 128, 300)
            ),
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "architecture": "late-interaction integrated bipartite member, action, and safety network",
            "pretrain_epochs": integer_setting(context.config, "shuffler_pretrain_epochs"),
            "fine_tune_epochs": integer_setting(context.config, "shuffler_finetune_epochs"),
            "batch_size": integer_setting(context.config, "shuffler_batch_size"),
            "head_epochs": integer_setting(context.config, "shuffler_head_epochs"),
            "safety_epochs": integer_setting(context.config, "shuffler_safety_epochs"),
            "device": string_setting(context.config, "device"),
            "protocol": "five-fold curriculum pretrain followed by all-train human-only fine-tune",
        }

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        curriculum = context.stage_dir("build_shuffler_curriculum")
        substrate = context.stage_dir("build_shuffler_substrate")
        corpus = context.stage_dir("materialize_corpora") / "train"
        pretrain = directory / "pretrain"
        fine_tune = directory / "fine_tune"
        cache = directory / "prepared"
        common = [
            "--interaction",
            "late_interaction",
            "--member-predictions",
            str(substrate / "train_primary" / "member_compatibility_oof.parquet"),
            "--edge-context",
            str(substrate / "graph" / "scored_member_edges.parquet"),
            "--report-predictions",
            str(substrate / "train_report_gate_repaired" / "report_gate_oof.parquet"),
            "--corpus",
            str(corpus),
            "--prepared-cache-dir",
            str(cache),
            "--member-batch-size",
            str(integer_setting(context.config, "shuffler_batch_size")),
            "--member-loss-reduction",
            "operation",
            "--head-epochs",
            str(integer_setting(context.config, "shuffler_head_epochs")),
            "--safety-epochs",
            str(integer_setting(context.config, "shuffler_safety_epochs")),
        ]
        device = string_setting(context.config, "device")
        if device != "auto":
            common.extend(("--device", device))
        self._train(
            context,
            [
                *common,
                "--labels",
                str(curriculum / "labels.parquet"),
                "--output-dir",
                str(pretrain),
                "--member-epochs",
                str(integer_setting(context.config, "shuffler_pretrain_epochs")),
                "--folds",
                "5",
            ],
        )
        self._train(
            context,
            [
                *common,
                "--labels",
                str(curriculum / "human_labels.parquet"),
                "--output-dir",
                str(fine_tune),
                "--member-epochs",
                str(integer_setting(context.config, "shuffler_finetune_epochs")),
                "--member-learning-rate",
                "0.0002",
                "--member-initial-state",
                str(pretrain / "integrated_report_shuffler.pt"),
                "--fine-tune-member-initial-state",
                "--folds",
                "0",
            ],
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("export_integrated_report_shuffler.py")),
                "--base-root",
                str(substrate),
                "--state",
                str(fine_tune / "integrated_report_shuffler.pt"),
                "--output-dir",
                str(directory / "exported"),
            ],
        )

    @staticmethod
    def _train(context: StageContext, arguments: list[str]) -> None:
        run_logged(
            context,
            TrainShuffler.name,
            [python(context), str(builder_script("train_integrated_report_shuffler.py")), *arguments],
        )
