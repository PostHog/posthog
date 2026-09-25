import json
import datetime
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import numpy as np
import pandas as pd
import xgboost as xgb
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking import model_store, scorer
from products.signals.backend.ranking.features import (
    EMBEDDING_DIMENSIONS,
    REPORT_EMBEDDINGS_EXTRA,
    REPORT_EMBEDDINGS_FEATURE_SET,
    TABULAR_FEATURE_SET,
    TITLE_EMBEDDINGS_FEATURE_SET,
    FeatureSet,
)
from products.signals.backend.ranking.model_store import ModelLoadError, load_serving_set
from products.signals.backend.ranking.scorer import NO_VECTOR, score_reports
from products.signals.backend.ranking.serving_manifest import (
    CROSS_FAMILY_ROLE,
    DAILY_CANDIDATE_ROLE,
    METADATA_FILE,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    model_key,
    serving_manifest_key,
    serving_model_prefix,
)
from products.signals.backend.ranking.sinks import REPORT_SCORED_EVENT
from products.signals.backend.report_embedding_reader import (
    REPORT_EMBEDDINGS_TABLE,
    ReportVector,
    latest_report_vectors,
)
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE, EMBEDDING_RENDERING_TITLE_SUMMARY
from products.signals.dags.inbox_ranking.training.unseen import UnseenModel, score_pool

PREFIX = "inbox_ranking_test"
VERSION = "2026-09-01"
OLDER_VERSION = "2026-08-25"
NOW = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.UTC)
LANDED = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.UTC)
HEADS = ("open", "thumbs_up")

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
    ) -> ServingManifestEntry:
        key = model_key(model_name, version)
        prefix = serving_model_prefix(PREFIX, key)
        metadata = {
            "model_name": model_name,
            "model_version": version,
            "model_kind": model_kind,
            "feature_set": feature_set.name,
            "feature_schema_version": feature_set.schema_version,
            "feature_names": list(feature_set.feature_names),
            "heads": [{"head": head, "file": f"{head}.ubj", "readable": head == "open"} for head in HEADS],
        }
        self.objects[f"{prefix}/{METADATA_FILE}"] = json.dumps(metadata).encode()
        booster = _booster_ubj(booster_feature_names or feature_set.feature_names)
        for head in HEADS:
            if head not in missing_heads:
                self.objects[f"{prefix}/{head}.ubj"] = booster
        return ServingManifestEntry(
            key=key,
            model_name=model_name,
            model_version=version,
            model_kind=model_kind,
            roles=list(roles),
            prefix=prefix,
            heads=list(HEADS),
        )

    def publish_manifest(self, entries: Sequence[ServingManifestEntry]) -> ServingManifest:
        manifest = ServingManifest(manifest_version=NOW.isoformat(), models=list(entries))
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
            ("booster_on_other_features", {"booster_feature_names": TABULAR_FEATURE_SET.feature_names}, "booster"),
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
            ("booster_on_other_features", {"booster_feature_names": TABULAR_FEATURE_SET.feature_names}, "booster"),
            ("missing_head_file", {"missing_heads": ["thumbs_up"]}, "thumbs_up.ubj"),
            ("unknown_model_kind", {"model_kind": "torch"}, "torch"),
        ]
    )
    def test_a_challenger_that_cannot_load_is_skipped(self, _name: str, kwargs: dict, reason: str) -> None:
        served = self._served()
        challenger = self._challenger("title_embeddings", TITLE_EMBEDDINGS_FEATURE_SET, **kwargs)
        self.store.publish_manifest([served, challenger])

        serving = load_serving_set()

        assert serving is not None
        assert serving.served.entry.key == served.key
        assert serving.others == []
        assert reason in serving.skipped[challenger.key]

    def test_a_loaded_key_is_not_read_again_but_takes_the_new_roles(self) -> None:
        served = self._served()
        self.store.publish_manifest([served])
        load_serving_set()
        model_reads = [key for key in self.store.reads if key != serving_manifest_key(PREFIX)]

        self.store.publish_manifest([served.model_copy(update={"roles": [SERVED_ROLE, DAILY_CANDIDATE_ROLE]})])
        serving = load_serving_set()

        assert serving is not None
        assert [key for key in self.store.reads if key != serving_manifest_key(PREFIX)] == model_reads
        assert serving.served.entry.roles == [SERVED_ROLE, DAILY_CANDIDATE_ROLE]


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

    @contextmanager
    def __call__(self) -> Iterator[Any]:
        yield lambda **kwargs: self.events.append(kwargs)


class _ScorerTestMixin(_StoreTestMixin):
    def _score(
        self, report_ids: Sequence[str], vectors: Mapping[str, Mapping[str, ReportVector]], *, persist: bool
    ) -> tuple[list[scorer.ReportScoringOutcome], _FakeVectors, _Captured]:
        fake_vectors = _FakeVectors(vectors)
        captured = _Captured()
        with (
            patch.object(scorer, "latest_report_vectors", fake_vectors),
            patch("products.signals.backend.ranking.sinks.ph_scoped_capture", captured),
        ):
            outcomes = score_reports(self.team_id, report_ids, persist=persist, now=NOW)
        return outcomes, fake_vectors, captured

    team_id = 1


class TestScorer(_ScorerTestMixin, SimpleTestCase):
    def test_a_served_score_equals_the_dags_unseen_score_for_the_same_model_and_vector(self) -> None:
        served = self._served()
        self.store.publish_manifest([served])
        vector = _vector(1)

        (outcome,), _, _ = self._score(
            ["r1"],
            {EMBEDDING_RENDERING_TITLE_SUMMARY: {"r1": ReportVector(embedding=vector, inserted_at=LANDED)}},
            persist=False,
        )

        pool = pd.DataFrame(
            {
                "report_created_at": [pd.Timestamp(LANDED)],
                "report_age_hours": [3.0],
                "signal_count": [2],
            },
            index=pd.Index(["r1"], name="report_id"),
        )
        extras = {
            REPORT_EMBEDDINGS_EXTRA: pd.DataFrame(
                {"embedding_small": [list(vector)], "embedding_inserted_at": [LANDED]},
                index=pd.Index(["r1"], name="report_id"),
            )
        }
        booster = self.store.objects[f"{served.prefix}/open.ubj"]
        dag_scores = score_pool(
            pool,
            pd.DataFrame({"open_count": [0], "impression_unit_count": [1]}, index=pool.index),
            [
                UnseenModel(
                    model_name=served.model_name,
                    model_version=served.model_version,
                    model_role="champion",
                    feature_set=REPORT_EMBEDDINGS_FEATURE_SET,
                    boosters={"open": booster},
                )
            ],
            snapshot_date=LANDED.date(),
            extras=extras,
        )

        assert outcome.score is not None
        assert outcome.score.results[served.key].scores["open"] == float(dag_scores["score"].iloc[0])

    def test_a_missing_served_vector_is_no_score(self) -> None:
        self.store.publish_manifest([self._served()])

        outcomes, _, _ = self._score(["r1"], {}, persist=False)

        assert [(outcome.score, outcome.reason) for outcome in outcomes] == [(None, NO_VECTOR)]

    def test_one_vector_read_per_rendering_whatever_the_number_of_models(self) -> None:
        served = self._served()
        candidate = self.store.publish_model(
            "report_embeddings", REPORT_EMBEDDINGS_FEATURE_SET, version=OLDER_VERSION, roles=[DAILY_CANDIDATE_ROLE]
        )
        title = self._challenger("title_embeddings", TITLE_EMBEDDINGS_FEATURE_SET)
        self.store.publish_manifest([served, candidate, title])

        _, fake_vectors, _ = self._score(["r1", "r2"], {}, persist=False)

        assert sorted(fake_vectors.calls) == sorted([EMBEDDING_RENDERING_TITLE_SUMMARY, EMBEDDING_RENDERING_TITLE])

    def test_challengers_without_a_vector_or_a_served_feature_set_are_skipped_results(self) -> None:
        served = self._served()
        title = self._challenger("title_embeddings", TITLE_EMBEDDINGS_FEATURE_SET)
        tabular = self._challenger("tabular_xgb", TABULAR_FEATURE_SET)
        manifest = self.store.publish_manifest([served, title, tabular])

        (outcome,), _, captured = self._score(
            ["r1"],
            {EMBEDDING_RENDERING_TITLE_SUMMARY: {"r1": ReportVector(embedding=_vector(1), inserted_at=LANDED)}},
            persist=False,
        )

        assert outcome.score is not None
        results = outcome.score.results
        assert (results[served.key].status, set(results[served.key].scores)) == ("scored", set(HEADS))
        assert (results[title.key].status, results[title.key].skip_reason) == ("skipped", NO_VECTOR)
        assert (results[tabular.key].status, results[tabular.key].skip_reason) == (
            "skipped",
            "feature set tabular is not served yet",
        )
        assert outcome.score.served_key == manifest.served.key
        assert outcome.score.embedding_inserted_at == LANDED
        assert captured.events == []


class TestScorerPersists(_ScorerTestMixin, BaseTest):
    def _report(self, team_id: int) -> str:
        return str(SignalReport.objects.create(team_id=team_id, status=SignalReport.Status.READY, title="A").id)

    def test_persist_writes_one_valid_row_per_scored_report_of_the_team(self) -> None:
        self.team_id = self.team.id
        served = self._served()
        title = self._challenger("title_embeddings", TITLE_EMBEDDINGS_FEATURE_SET)
        manifest = self.store.publish_manifest([served, title])
        scored, unscored = self._report(self.team.id), self._report(self.team.id)
        other_team = Team.objects.create(organization=self.organization)
        foreign = self._report(other_team.id)
        vector = ReportVector(embedding=_vector(1), inserted_at=LANDED)

        outcomes, _, captured = self._score(
            [scored, unscored, foreign],
            {
                EMBEDDING_RENDERING_TITLE_SUMMARY: {scored: vector, foreign: vector},
                EMBEDDING_RENDERING_TITLE: {scored: vector},
            },
            persist=True,
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
        assert score.results[title.key].status == "scored"
        assert sorted(
            (event["event"], event["properties"]["report_id"], event["properties"]["model_key"])
            for event in captured.events
        ) == sorted([(REPORT_SCORED_EVENT, scored, served.key), (REPORT_SCORED_EVENT, scored, title.key)])

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
