from __future__ import annotations

import os
import json
import asyncio
import tempfile
from collections import defaultdict
from pathlib import Path
from stat import S_IMODE
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

import numpy as np
import onnxruntime as ort

from products.signals.backend.grouping_replay.artifacts import load_frozen_pipeline
from products.signals.backend.grouping_replay.bundle import (
    build_bundle,
    canonical_bundle_sha256,
    inspect_bundle,
    write_bundle,
)
from products.signals.backend.grouping_replay.cache import append_jsonl
from products.signals.backend.grouping_replay.engine import (
    CONCERN_SPLIT_BUDGET,
    PythonPipeline,
    load_rows,
    materialize_signals,
)
from products.signals.backend.grouping_replay.enrichment import embed_missing_values, generate_signatures
from products.signals.backend.grouping_replay.input import load_input
from products.signals.backend.management.commands.export_signals_grouping_data import _report_rows
from products.signals.backend.management.commands.import_signals_grouping_pipeline import (
    _document_id_prefix_option,
    _ensure_clickhouse_document_ids_available,
    _load_and_validate_bundle,
)
from products.signals.backend.management.commands.run_signals_grouping_pipeline import _validate_signals_jsonl


class _RecordingSignatureProvider:
    def __init__(self) -> None:
        self.payloads: list[str] = []

    async def generate_signature(self, *, model: str, system_prompt: str, signal_payload: str) -> str:
        self.payloads.append(signal_payload)
        return json.dumps(
            {
                "polarity": "problem",
                "surface": "surface",
                "failure_mode": "failure",
                "error_anchor": None,
                "affected_entity": "entity",
                "concern_tags": ["tag"],
                "one_liner": "one line",
            }
        )


class _ControlledEmbeddingProvider:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.full = asyncio.Event()
        self.release = asyncio.Event()

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 1
        text = texts[0]
        self.attempts[text] += 1
        if text == "text-0" and self.attempts[text] == 1:
            raise RuntimeError("transient request failure")
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        if self.active == 3:
            self.full.set()
        await self.release.wait()
        self.active -= 1
        return [[0.0] * 1536]


class TestGroupingReplayContracts(SimpleTestCase):
    def test_equal_timestamp_signals_use_document_id_stream_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "signals.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "document_id": "signal-z",
                                "timestamp": "2026-07-01T00:00:00Z",
                                "content": "last by stable ID",
                            }
                        ),
                        json.dumps(
                            {
                                "document_id": "signal-a",
                                "timestamp": "2026-07-01T00:00:00Z",
                                "content": "first by stable ID",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rows = load_rows(input_path)

        assert [row["document_id"] for row in rows] == ["signal-a", "signal-z"]

    def test_multi_file_input_uses_document_id_to_break_timestamp_ties(self) -> None:
        timestamp = "2026-07-01T00:00:00Z"
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory)
            (input_path / "a.jsonl").write_text(
                json.dumps({"document_id": "signal-z", "timestamp": timestamp, "content": "later by ID"}) + "\n",
                encoding="utf-8",
            )
            (input_path / "b.jsonl").write_text(
                json.dumps({"document_id": "signal-a", "timestamp": timestamp, "content": "earlier by ID"}) + "\n",
                encoding="utf-8",
            )

            loaded = load_input(input_path)

        assert [row["document_id"] for row in loaded.rows] == ["signal-a", "signal-z"]

    def test_concern_split_budget_stops_repeated_report_evaluation(self) -> None:
        pipeline = PythonPipeline.__new__(PythonPipeline)
        pipeline.reports = {"report-1": [0, 1, 2]}
        pipeline.split_events = [
            {"source": f"source-{index}", "new": "report-1"} for index in range(CONCERN_SPLIT_BUDGET)
        ]

        pipeline.evaluate_split("report-1", trigger=2)

        assert len(pipeline.split_events) == CONCERN_SPLIT_BUDGET

    def test_dynamic_shuffler_accepts_reports_beyond_the_old_size_contract(self) -> None:
        pipeline = load_frozen_pipeline()
        manifest = json.loads((pipeline.artifact_dir / "integrated_report_shuffler.manifest").read_text())
        artifact = pipeline.artifact_dir / manifest["bipartite"]["artifact"]["path"]
        session = ort.InferenceSession(str(artifact), providers=["CPUExecutionProvider"])
        left_members, right_members = 301, 151
        node_features = len(manifest["node_feature_names"])
        edge_features = len(manifest["edge_feature_names"])
        edge_mask = np.zeros((1, left_members, right_members), dtype=bool)
        for left in range(left_members):
            edge_mask[0, left, left % right_members] = True
        for right in range(right_members):
            edge_mask[0, right % left_members, right] = True

        left_logits, right_logits, action_logit, safety_logit = session.run(
            ["left_logits", "right_logits", "action_logit", "safety_logit"],
            {
                "left_features": np.zeros((1, left_members, node_features), dtype=np.float32),
                "right_features": np.zeros((1, right_members, node_features), dtype=np.float32),
                "left_embeddings": np.zeros((1, left_members, 1536), dtype=np.float32),
                "right_embeddings": np.zeros((1, right_members, 1536), dtype=np.float32),
                "edge_features": np.zeros((1, left_members, right_members, edge_features), dtype=np.float32),
                "edge_mask": edge_mask,
                "member_threshold": np.asarray([[0.1]], dtype=np.float32),
            },
        )

        assert left_logits.shape == (1, left_members)
        assert right_logits.shape == (1, right_members)
        assert action_logit.shape == (1,)
        assert safety_logit.shape == (1,)

    def test_customer_derived_cache_and_bundle_files_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache_path = root / "cache" / "responses.jsonl"
            bundle_path = root / "bundle.json"

            cache_path.parent.mkdir()
            cache_path.write_text("", encoding="utf-8")
            os.chmod(cache_path.parent, 0o755)
            os.chmod(cache_path, 0o644)
            append_jsonl(cache_path, {"response": "customer-derived"})
            write_bundle(bundle_path, {"value": "customer-derived"})

            assert S_IMODE(cache_path.parent.stat().st_mode) == 0o700
            assert S_IMODE(cache_path.stat().st_mode) == 0o600
            assert S_IMODE(bundle_path.stat().st_mode) == 0o600

    def test_signature_cache_distinguishes_the_complete_provider_input(self) -> None:
        provider = _RecordingSignatureProvider()
        base_row: dict[str, object] = {
            "document_id": "signal-1",
            "content": "same words",
            "source_type": "issue",
            "concern_signature": None,
        }
        first = {**base_row, "source_product": "error_tracking"}
        second = {**base_row, "document_id": "signal-2", "source_product": "session_replay"}

        async def run_scenario(cache_dir: Path) -> None:
            await generate_signatures([first], cache_dir, 1, provider)
            await generate_signatures([second], cache_dir, 1, provider)

        with tempfile.TemporaryDirectory() as temporary_directory:
            asyncio.run(run_scenario(Path(temporary_directory)))

        assert len(provider.payloads) == 2
        assert provider.payloads[0] != provider.payloads[1]

    def test_embedding_retries_and_concurrency_are_scoped_per_text_request(self) -> None:
        async def no_wait(_delay: float) -> None:
            return None

        async def run_scenario(cache_path: Path) -> _ControlledEmbeddingProvider:
            provider = _ControlledEmbeddingProvider()
            operation = asyncio.create_task(
                embed_missing_values(
                    {f"id-{index}": f"text-{index}" for index in range(6)},
                    cache_path,
                    3,
                    provider,
                )
            )
            await provider.full.wait()
            provider.release.set()
            await operation
            return provider

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("products.signals.backend.grouping_replay.enrichment.asyncio.sleep", new=no_wait):
                provider = asyncio.run(run_scenario(Path(temporary_directory) / "embeddings.jsonl"))

        assert provider.maximum_active == 3
        assert provider.attempts["text-0"] == 2
        assert all(provider.attempts[f"text-{index}"] == 1 for index in range(1, 6))

    def test_import_requires_a_namespace_and_rejects_clickhouse_collisions(self) -> None:
        with pytest.raises(CommandError, match="non-empty namespace"):
            _document_id_prefix_option({"document_id_prefix": "  "})

        with (
            patch(
                "products.signals.backend.management.commands.import_signals_grouping_pipeline.sync_execute",
                side_effect=[[], [("existing-id",)]],
            ) as execute,
            pytest.raises(CommandError, match="already present"),
        ):
            _ensure_clickhouse_document_ids_available(team_id=7, document_ids=["namespace:signal-1"])

        assert all(call.kwargs == {"team_id": 7, "readonly": True} for call in execute.call_args_list)

    def test_replay_input_rejects_negative_weights(self) -> None:
        row = {
            "document_id": "signal-1",
            "timestamp": "2026-07-01T00:00:00Z",
            "content": "one signal",
            "weight": -0.1,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "signals.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with pytest.raises(CommandError, match="negative or non-finite"):
                _validate_signals_jsonl(path, require_embedding=False)

    def test_bundle_rejects_changed_frozen_operating_point(self) -> None:
        source_embedding = [1.0, *([0.0] * 1535)]
        signal = materialize_signals(
            [
                {
                    "document_id": "signal-1",
                    "timestamp": 1.0,
                    "content": "one signal",
                    "source_product": "error_tracking",
                    "source_type": "issue",
                    "source_id": "source-1",
                    "weight": 0.5,
                    "metadata": {},
                    "embedding": source_embedding,
                    "concern_signature": {
                        "polarity": "problem",
                        "surface": ["errors"],
                        "failmode": ["timeout"],
                        "tags": ["timeout"],
                        "anchor": [],
                        "oneliner": ["fix", "timeout"],
                        "has_failmode": True,
                        "has_anchor": False,
                        "emb": source_embedding,
                    },
                }
            ]
        )[0]
        pipeline = load_frozen_pipeline()
        bundle = build_bundle(
            signals=[signal],
            replay={
                "assignment": {"signal-1": "engine-report-1"},
                "decisions": [],
                "events": {"report_shuffling": [], "split": []},
            },
            mode="oracle-off",
            source_name="signals.jsonl",
            source_sha256="a" * 64,
            pipeline=pipeline,
            enrichment={
                "signature_model": "claude-haiku-4-5",
                "signature_prompt_version": "lab3-sig-v1",
                "embedding_model": "text-embedding-3-small",
            },
            signature_concurrency=1,
            embedding_concurrency=1,
            oracle_calls=0,
            oracle_cache_hits=0,
        )
        pipeline_record = bundle["pipeline"]
        assert isinstance(pipeline_record, dict)
        configuration = cast(dict[str, object], pipeline_record["configuration"])
        assert isinstance(configuration, dict)
        configuration["gj_raw_tau"] = 0.1
        bundle["integrity"] = {"algorithm": "sha256", "canonical_payload_sha256": canonical_bundle_sha256(bundle)}

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bundle.json"
            write_bundle(path, bundle)
            with pytest.raises(ValueError, match="engine configuration"):
                inspect_bundle(path)

    def test_export_directory_replay_does_not_ingest_report_rows(self) -> None:
        signal = {
            "document_id": "signal-1",
            "timestamp": "2026-07-01T00:00:00Z",
            "content": "one signal",
        }
        report = {"report_id": "report-1", "member_ids": ["signal-1"]}
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory)
            (input_path / "signals.jsonl").write_text(json.dumps(signal) + "\n", encoding="utf-8")
            (input_path / "reports.jsonl").write_text(json.dumps(report) + "\n", encoding="utf-8")

            loaded = load_input(input_path)

        assert [row["document_id"] for row in loaded.rows] == ["signal-1"]
        assert loaded.source_name == Path(temporary_directory).name

    def test_materialization_preserves_provider_vector_separately_from_normalized_features(self) -> None:
        source_embedding = [2.0, *([0.0] * 1535)]
        rows: list[dict[str, object]] = [
            {
                "document_id": "signal-1",
                "timestamp": 1.0,
                "content": "one signal",
                "source_product": "error_tracking",
                "source_type": "issue",
                "source_id": "source-1",
                "weight": 0.5,
                "metadata": {},
                "embedding": source_embedding,
                "concern_signature": {
                    "polarity": "problem",
                    "surface": ["errors"],
                    "failmode": ["timeout"],
                    "tags": ["timeout"],
                    "anchor": [],
                    "oneliner": ["fix", "timeout"],
                    "has_failmode": True,
                    "has_anchor": False,
                    "emb": [1.0, *([0.0] * 1535)],
                },
            }
        ]

        signal = materialize_signals(rows)[0]

        assert signal.source_embedding[0] == 2.0
        assert signal.embedding[0] == 1.0

    def test_export_reports_cover_dangling_and_unassigned_signals_exactly_once(self) -> None:
        signals: list[dict[str, object]] = [
            {"document_id": "assigned", "report_id": "missing-report", "weight": 0.5},
            {"document_id": "unassigned", "report_id": "", "weight": 1.0},
        ]

        with patch(
            "products.signals.backend.management.commands.export_signals_grouping_data.SignalReport.objects.filter"
        ) as filter_reports:
            filter_reports.return_value.order_by.return_value = []
            reports, warnings = _report_rows(team_id=1, signals=signals)

        report_members = [cast(list[str], report["member_ids"]) for report in reports]
        assert {member for members in report_members for member in members} == {"assigned", "unassigned"}
        assert len([member for members in report_members for member in members]) == 2
        assert signals[1]["report_id"] == "unassigned:unassigned"
        assert {warning["code"] for warning in warnings} == {"missing_report_metadata", "unassigned_signals"}

    def test_import_rejects_report_weight_that_disagrees_with_members(self) -> None:
        bundle = {
            "schema_version": "posthog-signals-grouping-replay/v1",
            "mode": "oracle-off",
            "pipeline": {"fingerprint": "a" * 64},
            "input": {"signal_count": 1, "concern_signature_coverage": 1.0},
            "warnings": [],
            "reports": [
                {
                    "report_id": "report-1",
                    "signal_ids": ["signal-1"],
                    "signal_count": 1,
                    "total_weight": 100.0,
                }
            ],
            "signals": [
                {
                    "document_id": "signal-1",
                    "report_id": "report-1",
                    "timestamp": "2026-07-01T00:00:00Z",
                    "content": "one signal",
                    "weight": 0.5,
                    "embedding": [0.0] * 1536,
                    "metadata": {},
                }
            ],
        }
        inspection = SimpleNamespace(bundle=bundle)

        with (
            patch(
                "products.signals.backend.management.commands.import_signals_grouping_pipeline.inspect_bundle",
                return_value=inspection,
            ),
            pytest.raises(CommandError, match="total_weight does not match"),
        ):
            _load_and_validate_bundle(Path("unused.json"))
