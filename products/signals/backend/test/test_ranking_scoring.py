import io
import sys
import json
import datetime
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import numpy as np
import pandas as pd
import pyarrow as pa
import xgboost as xgb
import pyarrow.parquet as pq
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking import model_store, report_facts, scorer
from products.signals.backend.ranking.features import (
    ALL_PROJECT_VECTOR_KINDS,
    EMBEDDING_DIMENSIONS,
    MIN_PROJECT_HISTORY_REPORTS,
    PROJECT_VECTOR_KINDS,
    REPORT_EMBEDDINGS_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
    FeatureSet,
)
from products.signals.backend.ranking.model_store import ModelLoadError, load_serving_set
from products.signals.backend.ranking.overrides import RankingOverrides
from products.signals.backend.ranking.report_facts import FACTS_SCHEMA_VERSION
from products.signals.backend.ranking.scorer import (
    NO_PROJECT_VECTORS,
    NO_REPORT_SOURCES,
    NO_VECTOR,
    PROJECT_VECTOR_KINDS_MISSING,
    ScoringError,
    score_reports,
)
from products.signals.backend.ranking.serving_manifest import (
    CROSS_FAMILY_ROLE,
    MANIFEST_SERVED_ROLE,
    METADATA_FILE,
    ONNX_MODEL_FILE,
    ONNX_MODEL_KIND,
    PINNED_ROLE,
    RECENT_ROLE,
    SERVED_OVERRIDE_ROLE,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    model_key,
    serving_manifest_key,
    serving_model_prefix,
    serving_project_vectors_key,
)
from products.signals.backend.ranking.sinks import REPORT_FACTS_EVENT, REPORT_SCORED_EVENT, classification_properties
from products.signals.backend.report_embedding_reader import (
    REPORT_EMBEDDINGS_TABLE,
    ReportVector,
    latest_report_vectors,
)
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE, EMBEDDING_RENDERING_TITLE_SUMMARY
from products.signals.backend.report_sources_reader import live_report_sources
from products.signals.backend.signal_metadata import EMBEDDING_MODEL

PREFIX = "inbox_ranking_test"
VERSION = "2026-09-01"
OLDER_VERSION = "2026-08-25"
NOW = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.UTC)
LANDED = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.UTC)
HEADS = ("open", "thumbs_up")
ONNX_FIXTURES = Path(__file__).parent / "fixtures" / "onnx"
# The column order of the fixture's `probabilities` output. Reversed from HEADS, so a model that
# reads columns in manifest order gives each head the other head's probability.
ONNX_OUTPUT_HEADS = ("thumbs_up", "open")

_BOOSTERS: dict[tuple[str, ...], bytes] = {}


def _booster_ubj(feature_names: tuple[str, ...]) -> bytes:
    if feature_names not in _BOOSTERS:
        rows = 20
        rng = np.random.default_rng(0)
        x = pd.DataFrame(rng.normal(size=(rows, len(feature_names))), columns=list(feature_names))
        model = xgb.XGBClassifier(n_estimators=3, max_depth=2)
        model.fit(x, np.arange(rows) % 2)
        _BOOSTERS[feature_names] = bytes(model.get_booster().save_raw("ubj"))
    return _BOOSTERS[feature_names]


def _vector(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=EMBEDDING_DIMENSIONS).astype(np.float32)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    def read_bytes(self, file_name: str, bucket: str | None = None, *, missing_ok: bool = False) -> bytes | None:
        self.reads.append(file_name)
        return self.objects.get(file_name)

    def read(self, file_name: str, bucket: str | None = None, *, missing_ok: bool = False) -> str | None:
        body = self.read_bytes(file_name, bucket, missing_ok=missing_ok)
        return None if body is None else body.decode()

    def publish_model(
        self,
        model_name: str,
        feature_set: FeatureSet,
        *,
        version: str = VERSION,
        roles: Sequence[str] = (SERVED_ROLE,),
        model_kind: str = "xgboost",
        booster_feature_names: tuple[str, ...] | None = None,
        missing_heads: Sequence[str] = (),
        thresholds: Mapping[str, float] | None = None,
        onnx_fixture: str = "report.onnx",
        project_vector_kinds: Sequence[str] = (),
    ) -> ServingManifestEntry:
        key = model_key(model_name, version)
        prefix = serving_model_prefix(PREFIX, key)
        onnx = model_kind == ONNX_MODEL_KIND
        metadata: dict[str, Any] = {
            "model_name": model_name,
            "model_version": version,
            "model_kind": model_kind,
            "feature_set": feature_set.name,
            "feature_schema_version": feature_set.schema_version,
            "feature_names": list(feature_set.feature_names),
            "heads": [
                {
                    "head": head,
                    "file": ONNX_MODEL_FILE if onnx else f"{head}.ubj",
                    "readable": head == "open",
                    **(
                        {"refit_classification_threshold": thresholds[head]}
                        if thresholds and head in thresholds
                        else {}
                    ),
                }
                for head in HEADS
            ],
        }
        if project_vector_kinds:
            metadata["project_vector_kinds"] = list(project_vector_kinds)
        if onnx:
            metadata["output_heads"] = list(ONNX_OUTPUT_HEADS)
            self.objects[f"{prefix}/{ONNX_MODEL_FILE}"] = (ONNX_FIXTURES / onnx_fixture).read_bytes()
        else:
            booster = _booster_ubj(booster_feature_names or feature_set.feature_names)
            for head in HEADS:
                if head not in missing_heads:
                    self.objects[f"{prefix}/{head}.ubj"] = booster
        self.objects[f"{prefix}/{METADATA_FILE}"] = json.dumps(metadata).encode()
        return ServingManifestEntry(
            key=key,
            model_name=model_name,
            model_version=version,
            model_kind=model_kind,
            roles=list(roles),
            prefix=prefix,
            heads=list(HEADS),
            model_file=ONNX_MODEL_FILE if onnx else None,
            reads_project_vectors=bool(project_vector_kinds),
        )

    def publish_project_vectors(self, team_id: int, vectors: np.ndarray, has_history: np.ndarray) -> str:
        key = serving_project_vectors_key(PREFIX, VERSION)
        table = pa.Table.from_pylist(
            [
                {
                    "team_id": team_id,
                    "kind": kind,
                    "vector": vectors[index].tolist(),
                    "n_reports": MIN_PROJECT_HISTORY_REPORTS if has_history[index] else 1,
                }
                for index, kind in enumerate(PROJECT_VECTOR_KINDS)
            ]
        )
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        self.objects[key] = buffer.getvalue()
        return key

    def publish_manifest(
        self, entries: Sequence[ServingManifestEntry], project_vectors: str | None = None
    ) -> ServingManifest:
        manifest = ServingManifest(
            manifest_version=NOW.isoformat(), models=list(entries), project_vectors=project_vectors
        )
        self.objects[serving_manifest_key(PREFIX)] = manifest.model_dump_json().encode()
        return manifest


class _StoreTestMixin:
    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        model_store.clear_model_cache()
        self.store = FakeObjectStore()
        for name in ("read", "read_bytes"):
            patcher = patch.object(model_store.object_storage, name, getattr(self.store, name))
            patcher.start()
            self.addCleanup(patcher.stop)  # type: ignore[attr-defined]
        settings_override = override_settings(INBOX_RANKING_DATASET_S3_PREFIX=PREFIX)
        settings_override.enable()
        self.addCleanup(settings_override.disable)  # type: ignore[attr-defined]
        self.addCleanup(model_store.clear_model_cache)  # type: ignore[attr-defined]

    def _served(self, **kwargs: Any) -> ServingManifestEntry:
        return self.store.publish_model("report_embeddings", REPORT_EMBEDDINGS_FEATURE_SET, **kwargs)

    def _challenger(self, model_name: str, feature_set: FeatureSet, **kwargs: Any) -> ServingManifestEntry:
        return self.store.publish_model(model_name, feature_set, roles=[CROSS_FAMILY_ROLE], **kwargs)


class TestModelStore(_StoreTestMixin, SimpleTestCase):
    def test_no_manifest_is_no_serving_set(self) -> None:
        assert load_serving_set() is None

    @parameterized.expand(
        [
            ("booster_on_other_features", {"booster_feature_names": ("age_hours",)}, "booster"),
            ("missing_head_file", {"missing_heads": ["thumbs_up"]}, "thumbs_up.ubj"),
            ("unknown_model_kind", {"model_kind": "torch"}, "torch"),
        ]
    )
    def test_a_served_entry_that_cannot_load_raises(self, _name: str, kwargs: dict, reason: str) -> None:
        self.store.publish_manifest([self._served(**kwargs)])
        with self.assertRaisesRegex(ModelLoadError, reason):
            load_serving_set()

    @parameterized.expand(
        [
            ("booster_on_other_features", {"booster_feature_names": ("age_hours",)}, "booster"),
            ("missing_head_file", {"missing_heads": ["thumbs_up"]}, "thumbs_up.ubj"),
            ("unknown_model_kind", {"model_kind": "torch"}, "torch"),
            (
                "onnx_input_width",
                {"model_kind": ONNX_MODEL_KIND, "onnx_fixture": "narrow_report.onnx"},
                "input report is tensor(float) ['batch', 8], not float (batch, 1536)",
            ),
            (
                "onnx_input_name",
                {"model_kind": ONNX_MODEL_KIND, "onnx_fixture": "unknown_input.onnx"},
                "inputs ['vector'] are not ['report']",
            ),
            (
                "onnx_graph_without_project_inputs",
                {"model_kind": ONNX_MODEL_KIND, "project_vector_kinds": PROJECT_VECTOR_KINDS},
                "inputs ['report'] are not ['has_history', 'project', 'report']",
            ),
            (
                "onnx_project_inputs_without_kinds",
                {"model_kind": ONNX_MODEL_KIND, "onnx_fixture": "project_report.onnx"},
                "inputs ['has_history', 'project', 'report'] are not ['report']",
            ),
            (
                "onnx_project_kind_unknown",
                {
                    "model_kind": ONNX_MODEL_KIND,
                    "onnx_fixture": "project_report.onnx",
                    "project_vector_kinds": ("typical", "open", "action", "closed"),
                },
                "project_vector_kinds ['typical', 'open', 'action', 'closed'] are not distinct",
            ),
            (
                "onnx_project_kind_repeated",
                {
                    "model_kind": ONNX_MODEL_KIND,
                    "onnx_fixture": "project_report.onnx",
                    "project_vector_kinds": ("typical", "open", "open", "dismiss"),
                },
                "project_vector_kinds ['typical', 'open', 'open', 'dismiss'] are not distinct",
            ),
            (
                "onnx_project_kinds_wider_than_the_graph",
                {
                    "model_kind": ONNX_MODEL_KIND,
                    "onnx_fixture": "project_report.onnx",
                    "project_vector_kinds": ALL_PROJECT_VECTOR_KINDS,
                },
                "input project is tensor(float)",
            ),
        ]
    )
    def test_a_challenger_that_cannot_load_is_skipped(self, _name: str, kwargs: dict, reason: str) -> None:
        served = self._served()
        challenger = self._challenger("nn", REPORT_EMBEDDINGS_FEATURE_SET, **kwargs)
        self.store.publish_manifest([served, challenger])

        serving = load_serving_set()

        assert serving is not None
        assert serving.served.entry.key == served.key
        assert serving.others == []
        assert reason in serving.skipped[challenger.key]

    @parameterized.expand(
        [
            ("not_in_the_manifest", None, "is not in the serving manifest"),
            ("files_missing", {"missing_heads": ["thumbs_up"]}, "did not load"),
            ("missing_a_served_head", {"heads": ["open"]}, "has no head for ['thumbs_up']"),
        ]
    )
    def test_a_served_override_that_cannot_apply_keeps_the_manifest_served_model(
        self, _name: str, override_kwargs: dict | None, reason: str
    ) -> None:
        served = self._served()
        entries = [served]
        override_key = model_key("report_embeddings", OLDER_VERSION)
        if override_kwargs is not None:
            heads = override_kwargs.pop("heads", None)
            pinned = self.store.publish_model(
                "report_embeddings",
                REPORT_EMBEDDINGS_FEATURE_SET,
                version=OLDER_VERSION,
                roles=[PINNED_ROLE],
                **override_kwargs,
            )
            entries.append(pinned.model_copy(update={"heads": heads}) if heads else pinned)
        self.store.publish_manifest(entries)

        with patch.object(model_store, "logger") as logger:
            serving = load_serving_set(RankingOverrides(served=override_key))

        assert serving is not None
        assert serving.served.entry.key == served.key
        assert serving.served_override is None
        [warning] = [
            call for call in logger.warning.call_args_list if call.args[0] == "inbox_ranking_override_rejected"
        ]
        assert reason in warning.kwargs["reason"]

    def test_a_served_override_moves_the_served_role_and_keeps_scoring_the_manifest_served_model(self) -> None:
        served = self._served()
        pinned = self.store.publish_model(
            "report_embeddings", REPORT_EMBEDDINGS_FEATURE_SET, version=OLDER_VERSION, roles=[PINNED_ROLE]
        )
        self.store.publish_manifest([served, pinned])
        overrides = RankingOverrides(served=pinned.key)

        serving = load_serving_set(overrides)

        assert serving is not None
        assert serving.served_override == overrides
        assert serving.manifest.served.key == pinned.key
        assert serving.served.entry.roles == [SERVED_ROLE, SERVED_OVERRIDE_ROLE, PINNED_ROLE]
        assert [(model.entry.key, model.entry.roles) for model in serving.others] == [
            (served.key, [MANIFEST_SERVED_ROLE])
        ]

    def test_a_loaded_key_is_not_read_again_but_takes_the_new_roles(self) -> None:
        served = self._served()
        self.store.publish_manifest([served])
        load_serving_set()
        model_reads = [key for key in self.store.reads if key != serving_manifest_key(PREFIX)]

        self.store.publish_manifest([served.model_copy(update={"roles": [SERVED_ROLE, RECENT_ROLE]})])
        serving = load_serving_set()

        assert serving is not None
        assert [key for key in self.store.reads if key != serving_manifest_key(PREFIX)] == model_reads
        assert serving.served.entry.roles == [SERVED_ROLE, RECENT_ROLE]


class _FakeVectors:
    def __init__(self, vectors_by_rendering: Mapping[str, Mapping[str, ReportVector]]) -> None:
        self.vectors_by_rendering = vectors_by_rendering
        self.calls: list[str] = []

    def __call__(self, team_id: int, report_ids: Sequence[str], *, rendering: str) -> dict[str, ReportVector]:
        self.calls.append(rendering)
        vectors = self.vectors_by_rendering.get(rendering, {})
        return {report_id: vectors[report_id] for report_id in report_ids if report_id in vectors}


class _Captured:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.scopes = 0

    def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    @contextmanager
    def __call__(self) -> Iterator[Any]:
        self.scopes += 1
        yield self.record


class _ScorerTestMixin(_StoreTestMixin):
    def _score(
        self,
        report_ids: Sequence[str],
        vectors: Mapping[str, Mapping[str, ReportVector]],
        *,
        persist: bool,
        shared_pass: bool = False,
    ) -> tuple[list[scorer.ReportScoringOutcome], _FakeVectors, _Captured]:
        fake_vectors = _FakeVectors(vectors)
        captured = _Captured()
        serving = load_serving_set() if shared_pass else None
        capture = cast(Any, captured.record) if shared_pass else None
        with (
            patch.object(scorer, "latest_report_vectors", fake_vectors),
            patch("products.signals.backend.ranking.sinks.ph_scoped_capture", captured),
        ):
            outcomes = score_reports(
                self.team_id, report_ids, persist=persist, now=NOW, serving=serving, capture=capture
            )
        return outcomes, fake_vectors, captured

    team_id = 1


class TestScorer(_ScorerTestMixin, SimpleTestCase):
    def test_a_missing_served_vector_is_no_score(self) -> None:
        self.store.publish_manifest([self._served()])

        outcomes, _, _ = self._score(["r1"], {}, persist=False)

        assert [(outcome.score, outcome.reason) for outcome in outcomes] == [(None, NO_VECTOR)]

    def test_one_vector_read_per_rendering_whatever_the_number_of_models(self) -> None:
        served = self._served()
        candidate = self.store.publish_model(
            "report_embeddings", REPORT_EMBEDDINGS_FEATURE_SET, version=OLDER_VERSION, roles=[RECENT_ROLE]
        )
        challenger = self._challenger("nn", REPORT_EMBEDDINGS_FEATURE_SET, model_kind=ONNX_MODEL_KIND)
        self.store.publish_manifest([served, candidate, challenger])

        _, fake_vectors, _ = self._score(["r1", "r2"], {}, persist=False)

        assert fake_vectors.calls == [EMBEDDING_RENDERING_TITLE_SUMMARY]

    def test_xgboost_and_onnx_models_score_in_one_pass(self) -> None:
        served = self._served()
        onnx = self._challenger("nn", REPORT_EMBEDDINGS_FEATURE_SET, model_kind=ONNX_MODEL_KIND)
        self.store.publish_manifest([served, onnx])
        expected = np.load(ONNX_FIXTURES / "report.expected.npz")
        report_ids = [f"r{index}" for index in range(len(expected["report"]))]
        vectors = {
            EMBEDDING_RENDERING_TITLE_SUMMARY: {
                report_id: ReportVector(embedding=vector, inserted_at=LANDED)
                for report_id, vector in zip(report_ids, expected["report"])
            }
        }

        outcomes, _, _ = self._score(report_ids, vectors, persist=False)

        for outcome, probabilities in zip(outcomes, expected["probabilities"]):
            assert outcome.score is not None
            results = outcome.score.results
            assert (results[served.key].status, set(results[served.key].scores)) == ("scored", set(HEADS))
            assert results[onnx.key].status == "scored"
            expected_scores = dict(zip(ONNX_OUTPUT_HEADS, probabilities.tolist()))
            assert results[onnx.key].scores == pytest.approx(expected_scores, abs=1e-6)

    def _project_model(
        self, roles: Sequence[str], kinds: Sequence[str] = PROJECT_VECTOR_KINDS, name: str = "nn"
    ) -> ServingManifestEntry:
        return self.store.publish_model(
            name,
            REPORT_EMBEDDINGS_FEATURE_SET,
            roles=roles,
            model_kind=ONNX_MODEL_KIND,
            onnx_fixture="project_report.onnx",
            project_vector_kinds=kinds,
        )

    def test_an_onnx_model_reads_the_team_project_vectors(self) -> None:
        served = self._served()
        nn = self._project_model([CROSS_FAMILY_ROLE])
        expected = np.load(ONNX_FIXTURES / "project_report.expected.npz")
        key = self.store.publish_project_vectors(self.team_id, expected["project"], expected["has_history"])
        self.store.publish_manifest([served, nn], project_vectors=key)
        report_ids = [f"r{index}" for index in range(len(expected["report"]))]
        vectors = {
            EMBEDDING_RENDERING_TITLE_SUMMARY: {
                report_id: ReportVector(embedding=vector, inserted_at=LANDED)
                for report_id, vector in zip(report_ids, expected["report"])
            }
        }

        outcomes, _, _ = self._score(report_ids, vectors, persist=False)

        for outcome, probabilities in zip(outcomes, expected["probabilities"]):
            assert outcome.score is not None
            result = outcome.score.results[nn.key]
            assert result.status == "scored"
            assert result.scores == pytest.approx(dict(zip(ONNX_OUTPUT_HEADS, probabilities.tolist())), abs=1e-6)

    @parameterized.expand(
        [("manifest_names_none", False, None), ("object_missing", True, None), ("object_unreadable", True, b"oops")]
    )
    def test_a_model_without_project_vectors_is_skipped_or_stops_the_served_score(
        self, _name: str, names_a_key: bool, body: bytes | None
    ) -> None:
        key = serving_project_vectors_key(PREFIX, VERSION) if names_a_key else None
        if key is not None and body is not None:
            self.store.objects[key] = body
        report = ReportVector(embedding=_vector(1), inserted_at=LANDED)
        vectors = {EMBEDDING_RENDERING_TITLE_SUMMARY: {"r1": report}}
        served = self._served()
        nn = self._project_model([CROSS_FAMILY_ROLE])
        self.store.publish_manifest([served, nn], project_vectors=key)

        (outcome,), _, _ = self._score(["r1"], vectors, persist=False)

        assert outcome.score is not None
        result = outcome.score.results[nn.key]
        assert (result.status, result.skip_reason) == ("skipped", NO_PROJECT_VECTORS)

        model_store.clear_model_cache()
        self.store.publish_manifest([self._project_model([SERVED_ROLE])], project_vectors=key)
        with self.assertRaisesRegex(ScoringError, "reads project vectors"):
            self._score(["r1"], vectors, persist=False)

    def test_a_model_that_reads_a_kind_the_day_lacks_is_skipped_or_stops_the_served_score(self) -> None:
        expected = np.load(ONNX_FIXTURES / "project_report.expected.npz")
        # The published day carries the four default kinds only, like a day written before `fixed` was stored.
        key = self.store.publish_project_vectors(self.team_id, expected["project"], expected["has_history"])
        report = ReportVector(embedding=_vector(1), inserted_at=LANDED)
        vectors = {EMBEDDING_RENDERING_TITLE_SUMMARY: {"r1": report}}
        served = self._served()
        nn = self._project_model([CROSS_FAMILY_ROLE])
        fixed = self._project_model([CROSS_FAMILY_ROLE], kinds=("typical", "open", "action", "fixed"), name="nn_fixed")
        self.store.publish_manifest([served, nn, fixed], project_vectors=key)

        (outcome,), _, _ = self._score(["r1"], vectors, persist=False)

        assert outcome.score is not None
        results = outcome.score.results
        assert results[nn.key].status == "scored"
        assert (results[fixed.key].status, results[fixed.key].skip_reason) == (
            "skipped",
            PROJECT_VECTOR_KINDS_MISSING,
        )

        model_store.clear_model_cache()
        self.store.publish_manifest(
            [self._project_model([SERVED_ROLE], kinds=("typical", "open", "action", "fixed"), name="nn_fixed")],
            project_vectors=key,
        )
        with self.assertRaisesRegex(ScoringError, r"reads project vector kinds \['fixed'\]"):
            self._score(["r1"], vectors, persist=False)


def test_importing_the_scoring_sweep_loads_no_model_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, django; django.setup(); import products.signals.backend.ranking.sweep; "
            "print(sorted({'onnxruntime', 'xgboost'} & set(sys.modules)))",
        ],
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "[]"


class TestClassificationProperties(SimpleTestCase):
    @parameterized.expand(
        [
            ("tie_is_a_positive", 0.3, True),
            ("above", 0.31, True),
            ("below", 0.29, False),
        ]
    )
    def test_predicted_reads_the_served_threshold(self, _name: str, score: float, predicted: bool) -> None:
        result = RankingModelResult(
            model_name="report_embeddings",
            model_version=VERSION,
            model_kind="xgboost",
            roles=[SERVED_ROLE],
            feature_schema_version=1,
            status="scored",
            scores={"open": score},
            metadata={"heads": [{"head": "open", "readable": True, "refit_classification_threshold": 0.3}]},
        )

        assert classification_properties(result) == {
            "readable_heads": ["open"],
            "threshold_open": 0.3,
            "predicted_open": predicted,
            "lift_open": score / 0.3,
        }


@override_settings(INBOX_RANKING_RECORD_REPORT_FACTS=False)
class TestScorerPersists(_ScorerTestMixin, BaseTest):
    def _report(self, team_id: int) -> str:
        return str(SignalReport.objects.create(team_id=team_id, status=SignalReport.Status.READY, title="A").id)

    @parameterized.expand([("own_scope", False), ("shared_pass", True)])
    def test_persist_writes_one_valid_row_per_scored_report_of_the_team(self, _name: str, shared_pass: bool) -> None:
        self.team_id = self.team.id
        served = self._served(thresholds={"open": 0.0})
        candidate = self.store.publish_model(
            "report_embeddings", REPORT_EMBEDDINGS_FEATURE_SET, version=OLDER_VERSION, roles=[RECENT_ROLE]
        )
        manifest = self.store.publish_manifest([served, candidate])
        scored, unscored = self._report(self.team.id), self._report(self.team.id)
        other_team = Team.objects.create(organization=self.organization)
        foreign = self._report(other_team.id)
        vector = ReportVector(embedding=_vector(1), inserted_at=LANDED)

        outcomes, _, captured = self._score(
            [scored, unscored, foreign],
            {EMBEDDING_RENDERING_TITLE_SUMMARY: {scored: vector, foreign: vector}},
            persist=True,
            shared_pass=shared_pass,
        )

        assert {outcome.report_id: outcome.reason for outcome in outcomes} == {
            scored: None,
            unscored: NO_VECTOR,
            foreign: None,
        }
        rows = list(SignalReportArtefact.objects.filter(type=SignalReportArtefact.ArtefactType.RANKING_SCORE))
        assert [(str(row.report_id), row.team_id) for row in rows] == [(scored, self.team.id)]
        score = RankingScore.model_validate_json(rows[0].content)
        assert score.served_key == manifest.served.key
        assert score.results[candidate.key].status == "scored"
        report = SignalReport.objects.get(id=scored)
        assert report.ranking_scores == score.results[manifest.served.key].scores
        assert report.ranking_open_score == score.results[manifest.served.key].scores["open"]
        assert sorted(
            (event["event"], event["properties"]["report_id"], event["properties"]["model_key"])
            for event in captured.events
        ) == sorted([(REPORT_SCORED_EVENT, scored, served.key), (REPORT_SCORED_EVENT, scored, candidate.key)])
        classification = {
            event["properties"]["model_key"]: {
                key: value
                for key, value in event["properties"].items()
                if key.startswith(("threshold_", "predicted_", "lift_", "readable_heads"))
            }
            for event in captured.events
        }
        # thumbs_up saved no threshold, and a model without one gets no stand-in. A zero threshold gives no lift.
        assert classification == {
            served.key: {"readable_heads": ["open"], "threshold_open": 0.0, "predicted_open": True},
            candidate.key: {"readable_heads": ["open"]},
        }
        assert self.store.reads.count(serving_manifest_key(PREFIX)) == 1
        assert captured.scopes == (0 if shared_pass else 1)

    def _judge(self, report_id: str, priority: str, created_at: datetime.datetime) -> None:
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority}),
        )
        SignalReportArtefact.objects.filter(pk=artefact.pk).update(created_at=created_at)

    def test_a_priority_model_scores_each_report_by_its_latest_priority_judgment(self) -> None:
        self.team_id = self.team.id
        feature_names = REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET.feature_names
        rng = np.random.default_rng(0)
        x = pd.DataFrame(np.zeros((40, len(feature_names))), columns=list(feature_names))
        x["priority_P0"] = np.arange(40) % 2
        x["emb_0"] = rng.normal(size=40)
        booster = xgb.XGBClassifier(n_estimators=3, max_depth=2).fit(x, x["priority_P0"]).get_booster()
        served = self.store.publish_model("nn_with_prio", REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET)
        for head in HEADS:
            self.store.objects[f"{served.prefix}/{head}.ubj"] = bytes(booster.save_raw("ubj"))
        self.store.publish_manifest([served])
        now_p0, now_p4 = self._report(self.team.id), self._report(self.team.id)
        self._judge(now_p0, "P4", NOW - datetime.timedelta(days=2))
        self._judge(now_p0, "P0", NOW - datetime.timedelta(days=1))
        self._judge(now_p4, "P0", NOW - datetime.timedelta(days=2))
        self._judge(now_p4, "P4", NOW - datetime.timedelta(days=1))
        vector = ReportVector(embedding=_vector(1), inserted_at=LANDED)

        outcomes, _, _ = self._score(
            [now_p0, now_p4], {EMBEDDING_RENDERING_TITLE_SUMMARY: {now_p0: vector, now_p4: vector}}, persist=False
        )

        scores = {
            outcome.report_id: outcome.score.results[served.key].scores["open"] for outcome in outcomes if outcome.score
        }
        assert scores[now_p0] > scores[now_p4]

    @parameterized.expand(
        [("read", None, "scored", None), ("read_fails", RuntimeError("down"), "skipped", NO_REPORT_SOURCES)]
    )
    def test_a_sources_model_scores_from_the_live_sources_or_is_skipped_when_the_read_fails(
        self, _name: str, error: Exception | None, status: str, skip_reason: str | None
    ) -> None:
        self.team_id = self.team.id
        served = self._served()
        sources = self._challenger("nn_with_prio_sources", REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET)
        self.store.publish_manifest([served, sources])
        report = self._report(self.team.id)
        vectors = {EMBEDDING_RENDERING_TITLE_SUMMARY: {report: ReportVector(embedding=_vector(1), inserted_at=LANDED)}}
        read = patch.object(scorer, "live_report_sources", side_effect=error, return_value=[(report, "error_tracking")])

        with read:
            (outcome,), _, _ = self._score([report], vectors, persist=False)

        assert outcome.score is not None
        assert outcome.score.results[served.key].status == "scored"
        result = outcome.score.results[sources.key]
        assert (result.status, result.skip_reason) == (status, skip_reason)
        if error is None:
            return
        model_store.clear_model_cache()
        self.store.publish_manifest(
            [self.store.publish_model("nn_with_prio_sources", REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET)]
        )
        with read, self.assertRaisesRegex(ScoringError, "reads report sources"):
            self._score([report], vectors, persist=False)

    def test_without_persist_nothing_is_written_or_captured(self) -> None:
        self.team_id = self.team.id
        self.store.publish_manifest([self._served()])
        report = self._report(self.team.id)

        (outcome,), _, captured = self._score(
            [report],
            {EMBEDDING_RENDERING_TITLE_SUMMARY: {report: ReportVector(embedding=_vector(1), inserted_at=LANDED)}},
            persist=False,
        )

        assert outcome.score is not None
        assert not SignalReportArtefact.objects.filter(type=SignalReportArtefact.ArtefactType.RANKING_SCORE).exists()
        assert captured.events == []


class TestLiveReportSources(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {REPORT_EMBEDDINGS_TABLE}", flush=False, team_id=self.team.pk)
        self.base = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)).replace(microsecond=0)

    def _emit(
        self,
        signal_id: str,
        report_id: str,
        product: str,
        *,
        hours: int,
        deleted: bool = False,
        team_id: int | None = None,
    ) -> None:
        at = self.base + datetime.timedelta(hours=hours)
        team_id = team_id or self.team.pk
        metadata = {"report_id": report_id, "source_product": product, "deleted": deleted}
        sync_execute(
            f"""
            INSERT INTO {REPORT_EMBEDDINGS_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id,
                    "signals",
                    "signal",
                    "plain",
                    signal_id,
                    self.base,
                    at,
                    "",
                    json.dumps(metadata),
                    [0.0] * EMBEDDING_DIMENSIONS,
                    at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id,
        )

    def test_reads_the_latest_emission_of_each_live_signal_of_the_team_only(self) -> None:
        self._emit("s1", "r1", "error_tracking", hours=1)
        self._emit("s2", "r1", "", hours=1)
        self._emit("s3", "r1", "zendesk", hours=1)
        self._emit("s3", "r1", "zendesk", hours=2, deleted=True)
        self._emit("s4", "r1", "linear", hours=1)
        self._emit("s4", "r2", "linear", hours=2)
        self._emit("s5", "r1", "github", hours=1, team_id=self.team.pk + 1)

        sources = live_report_sources(self.team.pk, ["r1", "r2", "absent"])

        assert sorted(sources, key=str) == sorted([("r1", "error_tracking"), ("r1", None), ("r2", "linear")], key=str)


@override_settings(INBOX_RANKING_RECORD_REPORT_FACTS=True)
class TestScorerRecordsFacts(ClickhouseTestMixin, _ScorerTestMixin, BaseTest):
    signals_table = f"posthog_document_embeddings_{EMBEDDING_MODEL.value.replace('-', '_')}"

    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE sharded_{self.signals_table}", flush=False, team_id=self.team.pk)
        self.store.publish_manifest([self._served()])
        self.other_team = Team.objects.create(organization=self.organization)

    def _report(self, team: Team, **fields: Any) -> str:
        return str(SignalReport.objects.create(team=team, status=SignalReport.Status.READY, **fields).id)

    def _signal(self, team_id: int, report_id: str, source_product: str) -> None:
        metadata = {"report_id": report_id, "source_product": source_product, "deleted": False}
        sync_execute(
            f"""
            INSERT INTO distributed_{self.signals_table} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id,
                    "signals",
                    "signal",
                    "plain",
                    f"{team_id}-{report_id}",
                    LANDED.replace(tzinfo=None),
                    LANDED.replace(tzinfo=None),
                    "a signal",
                    json.dumps(metadata),
                    [0.0] * EMBEDDING_DIMENSIONS,
                    LANDED.replace(tzinfo=None),
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id,
        )

    def _judge(self, team: Team, report_id: str, priority: str, created_at: datetime.datetime) -> None:
        artefact = SignalReportArtefact.objects.create(
            team=team,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority}),
        )
        SignalReportArtefact.objects.filter(pk=artefact.pk).update(created_at=created_at)

    def _pass(self, report_ids_by_team: Mapping[int, Sequence[str]]) -> list[dict[str, Any]]:
        vector = ReportVector(embedding=_vector(1), inserted_at=LANDED)
        vectors = {
            EMBEDDING_RENDERING_TITLE_SUMMARY: {
                report_id: vector for report_ids in report_ids_by_team.values() for report_id in report_ids
            }
        }
        captured = _Captured()
        serving = load_serving_set()
        with patch.object(scorer, "latest_report_vectors", _FakeVectors(vectors)):
            for team_id, report_ids in report_ids_by_team.items():
                score_reports(
                    team_id, report_ids, persist=True, now=NOW, serving=serving, capture=cast(Any, captured.record)
                )
        return captured.events

    def test_a_pass_over_two_teams_records_each_scored_reports_facts_from_its_own_team(self) -> None:
        own = self._report(self.team, title="A title", signal_count=3)
        other = self._report(self.other_team, title="Other", signal_count=9)
        self._signal(self.team.id, own, "error_tracking")
        self._signal(self.other_team.id, own, "session_replay")
        self._signal(self.other_team.id, other, "session_replay")
        self._judge(self.team, own, "P1", NOW - datetime.timedelta(days=2))
        self._judge(self.other_team, own, "P0", NOW - datetime.timedelta(days=1))

        events = self._pass({self.team.id: [own], self.other_team.id: [other]})

        facts = [event["properties"] for event in events if event["event"] == REPORT_FACTS_EVENT]
        assert {
            properties["report_id"]: (
                properties["team_id"],
                properties["source_products"],
                properties["signal_count"],
                properties["title_chars"],
                properties["priority"],
            )
            for properties in facts
        } == {
            own: (self.team.id, ["error_tracking"], 3, 7, "P1"),
            other: (self.other_team.id, ["session_replay"], 9, 5, None),
        }
        assert len(facts) == 2
        assert {
            (properties["scored_at"], properties["embedding_inserted_at"], properties["facts_schema_version"])
            for properties in facts
        } == {(NOW.isoformat(), LANDED.isoformat(), FACTS_SCHEMA_VERSION)}

    @parameterized.expand([("read_fails", True), ("turned_off", False)])
    def test_without_facts_the_scores_still_persist_and_no_facts_event_is_captured(
        self, _name: str, enabled: bool
    ) -> None:
        report = self._report(self.team)

        with (
            override_settings(INBOX_RANKING_RECORD_REPORT_FACTS=enabled),
            patch.object(report_facts, "fetch_source_products_for_reports", side_effect=RuntimeError("unreachable")),
        ):
            events = self._pass({self.team.id: [report]})

        assert SignalReportArtefact.objects.filter(
            report_id=report, type=SignalReportArtefact.ArtefactType.RANKING_SCORE
        ).exists()
        assert [event["event"] for event in events] == [REPORT_SCORED_EVENT]


class TestLatestReportVectors(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {REPORT_EMBEDDINGS_TABLE}", flush=False, team_id=self.team.pk)
        self.base = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2)).replace(microsecond=0)

    def _emit(
        self, *, team_id: int, report_id: str, hours: int, deleted: bool = False, rendering: str | None = None
    ) -> None:
        at = self.base + datetime.timedelta(hours=hours)
        sync_execute(
            f"""
            INSERT INTO {REPORT_EMBEDDINGS_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id,
                    "signals",
                    "report",
                    rendering or EMBEDDING_RENDERING_TITLE_SUMMARY,
                    report_id,
                    self.base,
                    at,
                    "a report",
                    json.dumps({"deleted": deleted}),
                    [float(hours)] * EMBEDDING_DIMENSIONS,
                    at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id,
        )

    def test_reads_the_newest_live_row_of_the_team_only(self) -> None:
        self._emit(team_id=self.team.pk, report_id="live", hours=1)
        self._emit(team_id=self.team.pk, report_id="live", hours=2)
        self._emit(team_id=self.team.pk, report_id="retracted", hours=1)
        self._emit(team_id=self.team.pk, report_id="retracted", hours=2, deleted=True)
        self._emit(team_id=self.team.pk, report_id="title_only", hours=1, rendering=EMBEDDING_RENDERING_TITLE)
        self._emit(team_id=self.team.pk + 1, report_id="foreign", hours=1)

        vectors = latest_report_vectors(
            self.team.pk,
            ["live", "retracted", "title_only", "foreign", "absent"],
            rendering=EMBEDDING_RENDERING_TITLE_SUMMARY,
        )

        assert list(vectors) == ["live"]
        assert vectors["live"].embedding[0] == 2.0
        assert vectors["live"].inserted_at == self.base + datetime.timedelta(hours=2)

    @parameterized.expand([("one_batch", 500, 1), ("paged", 2, 2)])
    def test_reads_in_batches_of_the_configured_size(self, _name: str, batch_size: int, queries: int) -> None:
        for index in range(3):
            self._emit(team_id=self.team.pk, report_id=f"r{index}", hours=1)

        with (
            override_settings(INBOX_RANKING_SCORING_BATCH_SIZE=batch_size),
            patch("products.signals.backend.report_embedding_reader.sync_execute", wraps=sync_execute) as spy,
        ):
            vectors = latest_report_vectors(
                self.team.pk, ["r0", "r1", "r2"], rendering=EMBEDDING_RENDERING_TITLE_SUMMARY
            )

        assert (sorted(vectors), spy.call_count) == (["r0", "r1", "r2"], queries)
