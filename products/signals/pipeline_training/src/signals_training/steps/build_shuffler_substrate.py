from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..io import JsonObject
from ..lineage import builder_script, python, run_logged, training_engine, write_engine_config
from ..stage import StageContext

BUILDERS = (
    "build_member_alignment_edges.py",
    "extract_member_pair_features.py",
    "score_member_alignment_graphs.py",
    "train_member_compatibility.py",
    "train_member_report_gate.py",
    "train_member_selector.py",
    "train_member_operation_risk.py",
)


class BuildShufflerSubstrate:
    name = "build_shuffler_substrate"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("build_shuffler_curriculum") / "labels.parquet",
            context.stage_dir("build_shuffler_curriculum") / "consensus_labels.parquet",
            context.stage_dir("materialize_corpora") / "train",
            context.stage_dir("train_pair") / "models-pair.json",
            training_engine(context),
            *(builder_script(name) for name in BUILDERS),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "graph" / "member_edges.parquet",
            directory / "graph" / "pair_features.jsonl",
            directory / "graph" / "pair_features.parquet",
            directory / "graph" / "scored_member_edges.parquet",
            directory / "graph" / "consensus_scored_member_edges.parquet",
            directory / "train_primary" / "member_compatibility_oof.parquet",
            directory / "train_primary" / "member_compatibility_models.pkl",
            directory / "train_consensus" / "member_compatibility_oof.parquet",
            directory / "train_consensus" / "member_compatibility_models.pkl",
            directory / "train_report_gate_repaired" / "report_gate_oof.parquet",
            directory / "train_report_gate_repaired" / "report_gate_models.pkl",
            directory / "train_member_selector" / "member_selector_oof.parquet",
            directory / "train_operation_risk_contextual" / "operation_risk_models.pkl",
            directory / "train_operation_risk_bipartite" / "operation_risk_models.pkl",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "retrieval": "top 24 embedding neighbors in each cross-report direction",
            "pair_features": "frozen serving pair featurizer",
            "compatibility": "exact normalized member components",
            "consensus": "only independently dual-read or deterministic exact component operations",
        }

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        graph = directory / "graph"
        labels = context.stage_dir("build_shuffler_curriculum") / "labels.parquet"
        consensus_labels = context.stage_dir("build_shuffler_curriculum") / "consensus_labels.parquet"
        corpus = context.stage_dir("materialize_corpora") / "train"
        primary = directory / "train_primary"
        consensus = directory / "train_consensus"
        report_gate = directory / "train_report_gate_repaired"
        member_selector = directory / "train_member_selector"
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("build_member_alignment_edges.py")),
                "--ledger",
                str(labels),
                "--corpus",
                str(corpus),
                "--output-dir",
                str(graph),
                "--top-k",
                "24",
            ],
        )
        feature_config = directory / "pair-feature-config.json"
        write_engine_config(
            feature_config,
            corpus,
            models=str((context.stage_dir("train_pair") / "models-pair.json").resolve()),
            featurize_pairs=str((graph / "pair_requests.jsonl").resolve()),
            featurize_out=str((graph / "pair_features.jsonl").resolve()),
        )
        run_logged(
            context,
            self.name,
            [str(training_engine(context)), "featurize-pairs", str(feature_config)],
        )
        self._model(
            context,
            "extract_member_pair_features.py",
            "--input",
            str(graph / "pair_features.jsonl"),
            "--output",
            str(graph / "pair_features.parquet"),
        )
        self._model(
            context,
            "score_member_alignment_graphs.py",
            "--ledger",
            str(labels),
            "--edges",
            str(graph / "member_edges.parquet"),
            "--pair-features",
            str(graph / "pair_features.jsonl"),
            "--output-dir",
            str(graph),
        )
        self._model(
            context,
            "train_member_compatibility.py",
            "--labels",
            str(labels),
            "--edges",
            str(graph / "scored_member_edges.parquet"),
            "--pair-features",
            str(graph / "pair_features.parquet"),
            "--output-dir",
            str(primary),
            "--member-labels",
            str(labels),
            "--member-label-mode",
            "opus",
        )
        consensus_ids = set(pd.read_parquet(consensus_labels, columns=["merge_id"])["merge_id"].astype(str))
        scored_edges = pd.read_parquet(graph / "scored_member_edges.parquet")
        consensus_edges = scored_edges.loc[scored_edges["merge_id"].astype(str).isin(consensus_ids)].copy()
        if consensus_edges.empty:
            raise ValueError("consensus member-compatibility surface has no retrieved edges")
        consensus_edge_path = graph / "consensus_scored_member_edges.parquet"
        consensus_edges.to_parquet(consensus_edge_path, index=False)
        self._model(
            context,
            "train_member_compatibility.py",
            "--labels",
            str(consensus_labels),
            "--edges",
            str(consensus_edge_path),
            "--pair-features",
            str(graph / "pair_features.parquet"),
            "--output-dir",
            str(consensus),
            "--member-labels",
            str(consensus_labels),
            "--member-label-mode",
            "consensus",
        )
        predictions = primary / "member_compatibility_oof.parquet"
        edge_context = graph / "scored_member_edges.parquet"
        self._model(
            context,
            "train_member_report_gate.py",
            "--labels",
            str(labels),
            "--predictions",
            str(predictions),
            "--edge-context",
            str(edge_context),
            "--output-dir",
            str(report_gate),
        )
        report_predictions = report_gate / "report_gate_oof.parquet"
        self._model(
            context,
            "train_member_selector.py",
            "--labels",
            str(labels),
            "--member-predictions",
            str(predictions),
            "--edge-context",
            str(edge_context),
            "--report-predictions",
            str(report_predictions),
            "--output-dir",
            str(member_selector),
        )
        for architecture in ("contextual", "bipartite"):
            self._model(
                context,
                "train_member_operation_risk.py",
                "--architecture",
                architecture,
                "--labels",
                str(labels),
                "--member-predictions",
                str(member_selector / "member_selector_oof.parquet"),
                "--edge-predictions",
                str(predictions),
                "--report-predictions",
                str(report_predictions),
                "--output-dir",
                str(directory / f"train_operation_risk_{architecture}"),
            )

    @staticmethod
    def _model(context: StageContext, script: str, *arguments: str) -> None:
        run_logged(
            context,
            BuildShufflerSubstrate.name,
            [python(context), str(builder_script(script)), *arguments],
        )
