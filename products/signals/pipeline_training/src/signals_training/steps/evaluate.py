from __future__ import annotations

from pathlib import Path

from ..io import JsonObject
from ..lineage import number_setting, run_logged, training_engine, write_engine_config
from ..stage import StageContext


class Evaluate:
    def __init__(self, territory: str, name: str, *, requires_permission: bool) -> None:
        self.territory = territory
        self.name = name
        self.requires_permission = requires_permission

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("materialize_corpora") / self.territory,
            context.stage_dir("prepare_labels") / self.territory / "pairs.jsonl",
            context.stage_dir("prepare_labels") / self.territory / "reports.jsonl",
            context.stage_dir("train_split_gate") / "models-stack.json",
            context.stage_dir("train_groupjoin") / "groupjoin_direct.manifest.json",
            context.stage_dir("train_groupjoin") / "groupjoin_direct.onnx",
            context.stage_dir("train_shuffler") / "exported",
            training_engine(context),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "engine-config.json",
            directory / "replay" / "final_assignment.json",
            directory / "replay" / "runtime_stats.json",
            directory / "score.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "territory": self.territory,
            "requires_explicit_permission": self.requires_permission,
            "oracle": False,
            "operating_point": dict(context.config.evaluation),
        }

    def run(self, context: StageContext) -> None:
        if self.requires_permission and not context.allow_validation_b:
            raise PermissionError("validation B is frozen; rerun with --allow-validation-b after selecting on A")
        directory = context.stage_dir(self.name)
        corpus = context.stage_dir("materialize_corpora") / self.territory
        config_path = directory / "engine-config.json"
        write_engine_config(
            config_path,
            corpus,
            models=str((context.stage_dir("train_split_gate") / "models-stack.json").resolve()),
            id_lane_limit=10,
            use_groupjoin=True,
            groupjoin_neural_manifest=str(
                (context.stage_dir("train_groupjoin") / "groupjoin_direct.manifest.json").resolve()
            ),
            groupjoin_neural_mode="stack",
            gj_raw_tau=number_setting(context.config, "evaluation", "admission_threshold"),
            use_concern=True,
            concern_split_sigma=number_setting(context.config, "evaluation", "split_threshold"),
            concern_split_budget=256,
            concern_merge_gamma=1.1,
            member_repair_manifest=str(
                (
                    context.stage_dir("train_shuffler") / "exported" / "integrated_report_shuffler.manifest.json"
                ).resolve()
            ),
            member_repair_architecture="bipartite",
            member_repair_integrated_gates=True,
            member_repair_trigger_tau=number_setting(context.config, "evaluation", "shuffle_trigger_threshold"),
            member_repair_member_tau=number_setting(context.config, "evaluation", "shuffle_member_threshold"),
            member_repair_report_gate="hgb-d2",
            member_repair_report_gate_tau=number_setting(context.config, "evaluation", "shuffle_action_threshold"),
            member_repair_risk_gate="logistic",
            member_repair_risk_tau=number_setting(context.config, "evaluation", "shuffle_safety_threshold"),
            member_repair_apply=True,
            member_repair_split_after=True,
            member_repair_llm_oracle=False,
        )
        replay = directory / "replay"
        run_logged(
            context,
            self.name,
            [str(training_engine(context)), "replay", str(config_path), str(replay)],
        )
        run_logged(
            context,
            self.name,
            [
                str(training_engine(context)),
                "score",
                str(replay / "final_assignment.json"),
                str(context.stage_dir("prepare_labels") / self.territory / "pairs.jsonl"),
                str(context.stage_dir("prepare_labels") / self.territory / "reports.jsonl"),
                str(corpus / "source_reports.jsonl"),
                str(directory / "score.json"),
            ],
        )
