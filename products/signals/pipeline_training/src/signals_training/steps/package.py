from __future__ import annotations

import gzip
import json
import math
import shutil
from pathlib import Path
from typing import cast

from ..io import JsonObject, atomic_write, hash_paths, sha256_file, write_json
from ..stage import StageContext

RUNTIME_SHUFFLER_METADATA = (
    "schema_version",
    "model_family",
    "feature_contract",
    "interaction",
    "feature_independence",
    "caps",
    "node_feature_names",
    "edge_feature_names",
    "bipartite",
    "status",
)


class Package:
    name = "package"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.config.path,
            context.stage_dir("train_split_gate") / "models-stack.json",
            context.stage_dir("train_groupjoin") / "groupjoin_direct.onnx",
            context.stage_dir("train_groupjoin") / "groupjoin_direct.manifest.json",
            context.stage_dir("train_shuffler") / "exported",
            context.stage_dir("evaluate_a") / "score.json",
            *(context.stage_dir(name) / "_stage.json" for name in self._upstream_stages()),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        return [
            context.config.outputs / "pipeline.json",
            context.config.outputs / "training-run.json",
            context.config.outputs / "artifacts",
            context.config.outputs / "artifacts" / "manifest.json",
            context.stage_dir(self.name) / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "package_schema_version": 1,
            "concern_prompt_version": context.config.source["concern_prompt_version"],
            "evaluation": dict(context.config.evaluation),
        }

    def run(self, context: StageContext) -> None:
        score_value = json.loads((context.stage_dir("evaluate_a") / "score.json").read_text())
        if not isinstance(score_value, dict):
            raise ValueError("validation A score must be an object")
        score = cast(JsonObject, score_value)
        self._require_useful_validation_a(score)
        output = context.config.outputs
        if output.exists():
            shutil.rmtree(output)
        artifacts = output / "artifacts"
        artifacts.mkdir(parents=True)
        models_source = context.stage_dir("train_split_gate") / "models-stack.json"
        groupjoin_manifest_source = context.stage_dir("train_groupjoin") / "groupjoin_direct.manifest.json"
        shuffler_export = context.stage_dir("train_shuffler") / "exported"
        shuffler_manifest_source = shuffler_export / "integrated_report_shuffler.manifest.json"
        sources = [
            context.stage_dir("train_groupjoin") / "groupjoin_direct.onnx",
            *self._shuffler_runtime_files(shuffler_manifest_source),
        ]
        copied: list[Path] = []
        for source in sorted((path for path in sources if path.is_file()), key=lambda path: path.name):
            destination = artifacts / source.name
            shutil.copy2(source, destination)
            copied.append(destination)
        groupjoin_manifest_destination = artifacts / "groupjoin_direct.manifest"
        self._write_repo_json(groupjoin_manifest_destination, json.loads(groupjoin_manifest_source.read_text()))
        copied.append(groupjoin_manifest_destination)
        models_destination = artifacts / "models-stack.json.gz"
        self._write_deterministic_json_gzip(models_destination, json.loads(models_source.read_text()))
        copied.append(models_destination)
        # Validation A consumes the full training export earlier. Only the fields read by the
        # Python serving runtime cross the packaging boundary.
        copied.extend(self._write_compact_shuffler_artifacts(shuffler_manifest_source, artifacts))
        artifact_hashes = {path.name: sha256_file(path) for path in copied}
        artifact_sizes = {path.name: path.stat().st_size for path in copied}
        self._write_repo_json(
            artifacts / "manifest.json",
            {
                "schema_version": 1,
                "artifacts": artifact_hashes,
                "artifact_bytes": artifact_sizes,
                "source": "standalone Signals pipeline training orchestrator",
            },
        )
        self._write_pipeline(context, output / "pipeline.json")
        stage_fingerprints = {
            name: json.loads((context.stage_dir(name) / "_stage.json").read_text())["fingerprint"]
            for name in self._upstream_stages()
        }
        self._write_repo_json(
            output / "training-run.json",
            {
                "schema_version": 1,
                "configuration": self._sanitized_configuration(context.config.raw),
                "configuration_file": context.config.path.name,
                "inputs": hash_paths(context.config.inputs.values()),
                "stage_fingerprints": stage_fingerprints,
                "validation_a": score,
                "validation_b": "not read by the default training and package flow",
                "reproducibility": {
                    "data_stages": "content-fingerprinted and deterministic",
                    "model_fitting": "seeded; accelerator and library revisions can change floating-point weights",
                    "labels": "append-only LLM and human events normalized before the territory firewall",
                    "local_fold_metrics": (
                        "model-local only; downstream features can come from upstream fits with overlapping "
                        "train operations and are not end-to-end OOF calibration"
                    ),
                    "held_out_evidence": "territory-held-out validation A and one-shot frozen validation B",
                },
            },
        )
        write_json(
            context.stage_dir(self.name) / "summary.json",
            {"output": str(output), "artifacts": len(copied), "validation_a": score},
        )

    @staticmethod
    def _write_pipeline(context: StageContext, path: Path) -> None:
        evaluation = context.config.evaluation
        Package._write_repo_json(
            path,
            {
                "schema_version": 1,
                "name": "signals-grouping-trained-curriculum-shuffler-v1",
                "description": (
                    "Reproduced elected learned pipeline. Hosted oracle calls are a replay-time mode, "
                    "not a training dependency."
                ),
                "artifact_manifest": "artifacts/manifest.json",
                "preflight": {
                    "signature_model": "claude-haiku-4-5",
                    "signature_prompt_version": context.config.source["concern_prompt_version"],
                    "embedding_model": "text-embedding-3-small",
                    "signature_concurrency": 128,
                    "embedding_concurrency": 8,
                    "cache_policy": "append-only-run-directory",
                },
                "engine_config": {
                    "mode": "classifier",
                    "models": "artifacts/models-stack.json.gz",
                    "id_lane_limit": 10,
                    "precompute_retrieval": True,
                    "use_groupjoin": True,
                    "groupjoin_neural_manifest": "artifacts/groupjoin_direct.manifest",
                    "groupjoin_neural_mode": "stack",
                    "gj_raw_tau": evaluation["admission_threshold"],
                    "use_concern": True,
                    "concern_split_sigma": evaluation["split_threshold"],
                    "concern_split_budget": 256,
                    "concern_merge_gamma": 1.1,
                    "member_repair_manifest": "artifacts/integrated_report_shuffler.manifest",
                    "member_repair_architecture": "bipartite",
                    "member_repair_integrated_gates": True,
                    "member_repair_trigger_tau": evaluation["shuffle_trigger_threshold"],
                    "member_repair_member_tau": evaluation["shuffle_member_threshold"],
                    "member_repair_report_gate": "hgb-d2",
                    "member_repair_report_gate_tau": evaluation["shuffle_action_threshold"],
                    "member_repair_risk_gate": "logistic",
                    "member_repair_risk_tau": evaluation["shuffle_safety_threshold"],
                    "member_repair_apply": True,
                    "member_repair_split_after": True,
                    "member_repair_llm_max_tokens": 6000,
                    "matching_model": "claude-opus-4-8",
                },
                "modes": {
                    "oracle-off": {"engine_overrides": {"member_repair_llm_oracle": False}},
                    "oracle-on": {
                        "engine_overrides": {"member_repair_llm_oracle": True},
                        "oracle_model": "claude-opus-4-8",
                        "oracle_prompt_version": "remediation-coherence-v2",
                        "proposal_count": 1,
                    },
                },
            },
        )

    @staticmethod
    def _upstream_stages() -> tuple[str, ...]:
        return (
            "import_export",
            "enrich_concerns",
            "build_clone_links",
            "select_label_candidates",
            "normalize_label_ledgers",
            "validate_inputs",
            "clean_corpus",
            "split_territories",
            "prepare_labels",
            "materialize_corpora",
            "build_engine",
            "build_pair_surface",
            "train_pair",
            "harvest_groupjoin",
            "build_groupjoin_surface",
            "train_groupjoin",
            "build_cut_surface",
            "train_split_gate",
            "build_shuffler_curriculum",
            "build_shuffler_substrate",
            "train_shuffler",
            "evaluate_a",
        )

    @staticmethod
    def _require_useful_validation_a(score: JsonObject) -> None:
        metrics = ("pair_precision", "pair_recall", "keep_apart", "gold_cohesion")
        missing = [
            name
            for name in metrics
            if isinstance(score.get(name), bool)
            or not isinstance(score.get(name), (int, float))
            or not math.isfinite(float(cast(float, score.get(name))))
        ]
        denominators = score.get("denominators")
        if not isinstance(denominators, dict):
            raise RuntimeError("validation A has no scoring denominators; refusing to package")
        required_weights = ("positive_pair_weight", "negative_pair_weight", "gold_report_weight")
        empty = [
            name
            for name in required_weights
            if isinstance(denominators.get(name), bool)
            or not isinstance(denominators.get(name), (int, float))
            or float(cast(float, denominators.get(name))) <= 0.0
        ]
        if missing or empty:
            details = [*(f"undefined metric {name}" for name in missing), *(f"empty {name}" for name in empty)]
            raise RuntimeError(f"validation A is not useful enough to package: {', '.join(details)}")

    @classmethod
    def _write_compact_shuffler_artifacts(cls, source: Path, output: Path) -> list[Path]:
        raw_value = json.loads(source.read_text())
        if not isinstance(raw_value, dict):
            raise ValueError("integrated shuffler manifest must be an object")
        missing = [key for key in (*RUNTIME_SHUFFLER_METADATA, "compatibility_consensus") if key not in raw_value]
        if missing:
            raise ValueError(f"integrated shuffler manifest is missing runtime fields: {', '.join(missing)}")
        compatibility = raw_value["compatibility_consensus"]
        if not isinstance(compatibility, dict) or not compatibility:
            raise ValueError("integrated shuffler compatibility payload must be a non-empty object")

        compatibility_path = output / "integrated_report_shuffler.compatibility.json.gz"
        cls._write_deterministic_json_gzip(compatibility_path, compatibility)
        compact_manifest = {key: raw_value[key] for key in RUNTIME_SHUFFLER_METADATA}
        compact_manifest["compatibility_consensus"] = {
            "model_names": sorted(str(name) for name in compatibility),
            "artifact": {
                "path": compatibility_path.name,
                "format": "deterministic-json-gzip",
                "sha256": sha256_file(compatibility_path),
                "bytes": compatibility_path.stat().st_size,
            },
        }
        manifest_path = output / "integrated_report_shuffler.manifest"
        cls._write_repo_json(manifest_path, compact_manifest)
        return [compatibility_path, manifest_path]

    @staticmethod
    def _shuffler_runtime_files(manifest_path: Path) -> list[Path]:
        value = json.loads(manifest_path.read_text())
        if not isinstance(value, dict):
            raise ValueError("integrated shuffler manifest must be an object")
        bipartite = value.get("bipartite")
        if not isinstance(bipartite, dict):
            raise ValueError("integrated shuffler manifest has no bipartite runtime record")
        buckets = bipartite.get("buckets")
        if not isinstance(buckets, list) or not buckets:
            raise ValueError("integrated shuffler manifest has no ONNX buckets")
        root = manifest_path.parent.resolve()
        paths: list[Path] = []
        for bucket in buckets:
            artifact = bucket.get("artifact") if isinstance(bucket, dict) else None
            relative_path = artifact.get("path") if isinstance(artifact, dict) else None
            if not isinstance(relative_path, str) or not relative_path:
                raise ValueError("integrated shuffler bucket has no artifact path")
            path = (root / relative_path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"invalid integrated shuffler artifact path: {relative_path}")
            paths.append(path)
        return paths

    @staticmethod
    def _write_deterministic_json_gzip(path: Path, value: object) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        with (
            path.open("wb") as target,
            gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=9, mtime=0) as compressed,
        ):
            compressed.write(payload)

    @staticmethod
    def _write_repo_json(path: Path, value: object) -> None:
        atomic_write(
            path,
            json.dumps(value, ensure_ascii=False, indent=4, sort_keys=True, allow_nan=False) + "\n",
        )

    @classmethod
    def _sanitized_configuration(cls, value: object, key: str = "configuration") -> object:
        if isinstance(value, dict):
            return {
                str(child_key): cls._sanitized_configuration(child, str(child_key))
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [cls._sanitized_configuration(child, key) for child in value]
        normalized = key.lower()
        is_path = (
            normalized in {"workspace", "outputs", "python"}
            or normalized.endswith("_path")
            or normalized.endswith("_directory")
            or normalized.endswith("_ledger")
        )
        if is_path and isinstance(value, str) and value != "auto":
            return f"<redacted-path:{key}>"
        return value
