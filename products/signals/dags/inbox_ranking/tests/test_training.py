import io
import json
import math
import datetime
from typing import Any

import pytest

import numpy as np
import pandas as pd
import dagster
import pyarrow as pa
import xgboost as xgb
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    NO_EXTRAS,
    TABULAR_FEATURE_SET,
    Extras,
    FeatureSet,
    feature_frame,
    feature_vector,
)
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.training.dag import (
    METADATA_FILE,
    _delete_other_objects,
    candidate_metadata,
    champion_object_key,
    examples_object_key,
    grade_metadata,
    inbox_ranking_training_examples,
    load_snapshots,
    load_unseen_models,
    model_object_key,
    snapshot_dates,
)
from products.signals.dags.inbox_ranking.training.examples import (
    STATE_LAG_LIMIT,
    Snapshot,
    assemble_snapshot,
    build_examples,
    example_columns,
    holdout_mask,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, dismissed_as_wrong
from products.signals.dags.inbox_ranking.training.promotion import AUC_TOLERANCE, PromotionDecision, decide_promotion
from products.signals.dags.inbox_ranking.training.telemetry import (
    DISTINCT_ID,
    LOCAL_DISTINCT_ID,
    HeadExampleCounts,
    TrainingEvent,
    candidate_events,
    capture_training_events,
    examples_events,
    promotion_event,
    unseen_head_graded_events,
    unseen_report_graded_events,
    unseen_score_events,
)
from products.signals.dags.inbox_ranking.training.train import _head_readable, booster_holdout_auc, train_head
from products.signals.dags.inbox_ranking.training.unseen import (
    CANDIDATE_ROLE,
    CHAMPION_ROLE,
    LEGACY_POOL_NAME,
    POOL_NAME,
    SCORE_COLUMNS,
    TABULAR_MODEL_NAME,
    UnseenModel,
    chance_band,
    empty_scores_write_allowed,
    graded_rows,
    head_grades,
    leaked_report_ids,
    model_mismatch,
    report_grade_rows,
    score_event_rows,
    score_pool,
    scored_pool,
    unseen_pool,
    with_model_names,
)

# No trainer writes this family yet: it stands in for a second family in the grouping tests.
EMBEDDINGS_MODEL_NAME = "report_embeddings"

D0 = datetime.date(2026, 8, 10)
NOW = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)


def _state(report_ids: list[str], **overrides) -> pd.DataFrame:
    n = len(report_ids)
    base = {
        "report_created_at": [pd.Timestamp("2026-08-09T12:00:00Z")] * n,
        "report_age_hours": [12.0] * n,
        "signal_count": [3] * n,
        "total_weight": [1.5] * n,
        "run_count": [1] * n,
        "title_chars": [40] * n,
        "summary_chars": [400] * n,
        "priority": ["P2"] * n,
        "actionability": ["immediately_actionable"] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base, index=pd.Index(report_ids, name="report_id"))


def _labels(report_ids: list[str], **overrides) -> pd.DataFrame:
    n = len(report_ids)
    base = {
        "impression_unit_count": [1] * n,
        "open_count": [0] * n,
        "create_pr_click_count": [0] * n,
        "discuss_count": [0] * n,
        "dismissal_reason": [None] * n,
        "pr_created_count": [0] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base, index=pd.Index(report_ids, name="report_id"))


@pytest.mark.parametrize(
    "row",
    [
        {
            "signal_count": 3,
            "total_weight": 1.5,
            "run_count": 1,
            "title_chars": 40,
            "summary_chars": 400,
            "priority": "P1",
            "actionability": "not_actionable",
            "age_hours": 5.0,
        },
        {
            "signal_count": None,
            "total_weight": float("nan"),
            "run_count": 2,
            "title_chars": 0,
            "summary_chars": 0,
            "priority": None,
            "actionability": "bogus",
            "age_hours": 100.0,
        },
        {},
    ],
)
def test_feature_vector_matches_feature_frame(row):
    # The sweep scores one report at a time through feature_vector; training builds matrices
    # through feature_frame. They must agree or the booster sees a different universe at serve time.
    vector = feature_vector(row)
    frame = feature_frame(pd.DataFrame([row]) if row else pd.DataFrame([{}]))
    assert len(vector) == len(FEATURE_NAMES) == frame.shape[1]
    for name, value, column_value in zip(FEATURE_NAMES, vector, frame.iloc[0].tolist(), strict=True):
        assert (math.isnan(value) and math.isnan(column_value)) or value == column_value, name


def test_build_examples_is_a_scoring_moment_with_a_future_label():
    open_head = HEADS_BY_NAME["open"]
    later = D0 + datetime.timedelta(days=open_head.horizon_days)
    ids = ["a", "b", "c", "d"]
    snapshots = {
        # a: not yet impressed or opened at D0, impressed and opened by D0+3 -> positive;
        # b: already opened at D0 -> excluded; c: never opened -> negative;
        # d: never impressed -> outside the cohort.
        D0: Snapshot(
            date=D0,
            state=_state(ids),
            labels=_labels(ids, open_count=[0, 1, 0, 0], impression_unit_count=[0, 1, 1, 0]),
        ),
        later: Snapshot(
            date=later,
            state=_state(ids),
            labels=_labels(ids, open_count=[2, 3, 0, 0], impression_unit_count=[1, 1, 1, 0]),
        ),
        # A snapshot with no horizon partner contributes nothing.
        later + datetime.timedelta(days=1): Snapshot(date=later, state=_state(ids), labels=_labels(ids)),
    }
    examples = build_examples(snapshots, open_head, TABULAR_FEATURE_SET)
    assert list(examples.columns) == list(example_columns(TABULAR_FEATURE_SET))
    assert examples.set_index("report_id")["label"].to_dict() == {"a": 1, "c": 0}
    assert (examples["snapshot_date"] == D0).all()
    assert (examples["age_hours"] == 12.0).all()


def test_assemble_snapshot_makes_never_labeled_reports_negatives_and_drops_untrusted_status_rows():
    head = HEADS_BY_NAME["pr_created"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    ids = ["a", "b", "c", "gone"]
    # a: status telemetry names another tenant -> provenance fails; b: no label row at all;
    # c: trusted, dismissed as wrong by the horizon; gone: hard-deleted before the horizon, so the
    # later snapshot has its label row but no state row.
    state = _state(
        ids,
        report_team_id=[1, 1, 1, 1],
        status=["ready"] * 4,
        pg_updated_at=[pd.Timestamp("2026-08-09T12:00:00Z")] * 4,
    )
    labels_now = _labels(["a", "c"], latest_status_event=["suppressed", None], status_event_team_id=[99, None])
    labels_later = _labels(
        ["a", "c", "gone"],
        latest_status_event=["suppressed", "suppressed", None],
        status_event_team_id=[99, 1, None],
        wrong_dismissal_count=[1, 1, 0],
        pr_created_count=[0, 1, 1],
    )
    state_later = state.drop("gone").assign(status=["ready", "ready", "suppressed"])
    snapshots = {
        D0: assemble_snapshot(D0, state, labels_now),
        later: assemble_snapshot(later, state_later, labels_later),
    }

    assert snapshots[D0].labels.loc["b", "impression_unit_count"] == 0
    assert snapshots[D0].labels["label_provenance_ok"].to_dict() == {"a": False, "b": True, "c": True, "gone": True}
    assert snapshots[later].labels["label_provenance_ok"].to_dict() == {"a": False, "b": True, "c": True, "gone": False}
    # pr_created reads the tasks webhook, so a's untrusted status telemetry does not exclude it there.
    pr = build_examples(snapshots, head, TABULAR_FEATURE_SET).set_index("report_id")["label"].to_dict()
    assert pr == {"a": 0, "b": 0, "c": 1, "gone": 1}
    # dismiss_wrong reads the status stream: a is dropped, b was never impressed, c is a positive.
    wrong = (
        build_examples(snapshots, HEADS_BY_NAME["dismiss_wrong"], TABULAR_FEATURE_SET)
        .set_index("report_id")["label"]
        .to_dict()
    )
    assert wrong == {"c": 1}


def test_build_examples_drops_state_rows_read_long_after_their_snapshot():
    head = HEADS_BY_NAME["pr_created"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    forward_run = pd.Timestamp(D0 + datetime.timedelta(days=1), tz="UTC") + pd.Timedelta(hours=3)
    backfill = pd.Timestamp(D0 + datetime.timedelta(days=1), tz="UTC") + STATE_LAG_LIMIT + pd.Timedelta(hours=1)
    state = _state(["a", "b"], features_observed_at=[forward_run, backfill])
    snapshots = {
        D0: Snapshot(date=D0, state=state, labels=_labels(["a", "b"])),
        later: Snapshot(date=later, state=state, labels=_labels(["a", "b"])),
    }
    assert build_examples(snapshots, head, TABULAR_FEATURE_SET)["report_id"].tolist() == ["a"]


@pytest.mark.parametrize(
    "frame,expected",
    [
        # The cumulative count wins: a wrong dismissal later overwritten by already_fixed stays positive.
        (
            pd.DataFrame({"wrong_dismissal_count": [1, 0], "dismissal_reason": ["already_fixed", "analysis_wrong"]}),
            [True, False],
        ),
        # Partitions written before the count existed fall back to the latest-wins reason.
        (pd.DataFrame({"dismissal_reason": ["already_fixed", "analysis_wrong"]}), [False, True]),
    ],
)
def test_dismissed_as_wrong_prefers_the_cumulative_count(frame, expected):
    assert dismissed_as_wrong(frame).tolist() == expected


@pytest.mark.parametrize(
    "head_name,frame,expected_cohort,expected_label",
    [
        # pr_merged: cohort is reports with a PR, label is the merge within the horizon.
        (
            "pr_merged",
            pd.DataFrame({"pr_created_count": [1, 1, 0], "pr_merged_count": [1, 0, 0]}),
            [True, True, False],
            [True, False, False],
        ),
        # discuss: cohort is impressed reports, label is a discuss action.
        (
            "discuss",
            pd.DataFrame({"impression_unit_count": [1, 1, 0], "discuss_count": [2, 0, 0]}),
            [True, True, False],
            [True, False, False],
        ),
        # refund: cohort is everyone, label is a refund event.
        (
            "refund",
            pd.DataFrame({"refund_count": [1, 0, 0]}),
            [True, True, True],
            [True, False, False],
        ),
    ],
)
def test_new_heads_read_the_right_cohort_and_label_columns(head_name, frame, expected_cohort, expected_label):
    head = HEADS_BY_NAME[head_name]
    assert head.cohort(frame).tolist() == expected_cohort
    assert head.label(frame).tolist() == expected_label


def _parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(frame.reset_index(), preserve_index=False), buffer)
    return buffer.getvalue()


class _ParquetS3:
    """Serves the state and labels parquet objects load_snapshots reads, keyed by object key."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def get_object(self, *, Bucket, Key):
        if Key not in self._objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self._objects[Key])}


@pytest.mark.parametrize("head_name", ["pr_merged", "refund"])
def test_new_head_label_columns_survive_the_load_snapshots_projection(head_name):
    # load_snapshots projects the labels parquet down to _LABEL_COLUMNS before any head sees it, so a
    # head whose label column is missing from that list trains on all-zero labels. The cohort/label
    # unit test hand-builds frames that already carry the columns, so it never crosses the projection.
    # Drive the real parquet -> projection -> build_examples path and assert a positive label survives.
    head = HEADS_BY_NAME[head_name]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    labels_now = _labels(["a"], pr_created_count=[0], pr_merged_count=[0], refund_count=[0])
    labels_later = _labels(["a"], pr_created_count=[1], pr_merged_count=[1], refund_count=[1])
    objects: dict[str, bytes] = {}
    for date, labels in ((D0, labels_now), (later, labels_later)):
        key = date.isoformat()
        objects[partition_object_key("inbox_ranking", STATE_TABLE, key)] = _parquet(_state(["a"]))
        objects[partition_object_key("inbox_ranking", LABELS_TABLE, key)] = _parquet(labels)
    snapshots = load_snapshots(_ParquetS3(objects), "bucket", "inbox_ranking", [D0, later])
    examples = build_examples(snapshots, head, TABULAR_FEATURE_SET)
    assert examples.set_index("report_id")["label"].to_dict() == {"a": 1}


def test_build_examples_skips_refund_pairs_when_the_scoring_snapshot_lacks_the_column():
    # refund_count entered the labels schema after the epoch, so a partition written before it has no
    # such column. Without the guard _count reads the gap as zero, so the "not refunded yet" filter
    # passes for a report already refunded before D0, and its cumulative refund in the later snapshot
    # mints a stale future positive. The whole pair must be skipped, not scored.
    head = HEADS_BY_NAME["refund"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    snapshots = {
        D0: Snapshot(date=D0, state=_state(["a"]), labels=_labels(["a"])),
        later: Snapshot(date=later, state=_state(["a"]), labels=_labels(["a"], refund_count=[1])),
    }
    assert build_examples(snapshots, head, TABULAR_FEATURE_SET).empty


def test_build_examples_skips_label_only_rows():
    head = HEADS_BY_NAME["pr_created"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    state = _state(["a", "eu"], signal_count=[3, None])
    snapshots = {
        D0: Snapshot(date=D0, state=state, labels=_labels(["a", "eu"])),
        later: Snapshot(date=later, state=state, labels=_labels(["a", "eu"], pr_created_count=[1, 1])),
    }
    assert build_examples(snapshots, head, TABULAR_FEATURE_SET)["report_id"].tolist() == ["a"]


def test_holdout_mask_cuts_by_report_not_by_row():
    examples = pd.DataFrame(
        {
            "report_id": ["old", "old", "new", "new"],
            "report_created_at": pd.to_datetime(["2026-08-01", "2026-08-01", "2026-08-18", "2026-08-18"], utc=True),
        }
    )
    assert holdout_mask(examples, holdout_days=7).tolist() == [False, False, True, True]


def test_train_head_learns_a_separable_signal_and_names_its_features():
    head = HEADS_BY_NAME["open"]
    rng = np.random.default_rng(0)
    n = 2000
    created = pd.to_datetime("2026-07-01", utc=True) + pd.to_timedelta(rng.integers(0, 40, n), unit="D")
    signal_count = rng.integers(1, 50, n)
    rows = pd.DataFrame(
        {
            "signal_count": signal_count,
            "total_weight": rng.random(n),
            "run_count": 1,
            "title_chars": 40,
            "summary_chars": 400,
            "priority": "P2",
            "actionability": None,
            "age_hours": 12.0,
        }
    )
    examples = feature_frame(rows)
    examples.insert(0, "head", head.name)
    examples.insert(1, "report_id", [f"r{i}" for i in range(n)])
    examples.insert(2, "snapshot_date", D0)
    examples.insert(3, "report_created_at", created)
    examples["label"] = (signal_count > 25).astype(int)

    trained = train_head(examples, head, feature_names=FEATURE_NAMES, holdout_days=7)
    assert trained is not None
    assert trained.metrics.readable
    assert trained.metrics.holdout_auc is not None and trained.metrics.holdout_auc > 0.9
    assert trained.metrics.null_auc is not None and abs(trained.metrics.null_auc - 0.5) < 0.15
    assert trained.metrics.null_auc_std is not None and trained.metrics.null_auc_std < 0.15
    assert trained.metrics.train_auc is not None and trained.metrics.train_auc > 0.9
    assert trained.metrics.holdout_average_precision is not None and trained.metrics.holdout_average_precision > 0.9
    assert trained.metrics.holdout_logloss is not None and trained.metrics.holdout_logloss < 0.5
    assert trained.metrics.holdout_positive_rate == pytest.approx(
        trained.metrics.holdout_positives / trained.metrics.holdout_rows
    )
    booster = xgb.Booster()
    booster.load_model(bytearray(trained.booster_ubj))
    assert booster.feature_names == list(FEATURE_NAMES)
    # The saved holdout fit graded on the same rows must reproduce the stored metric: this is the
    # path the champion gate uses to compare two models on one holdout.
    assert trained.holdout_booster_ubj is not None
    paired = booster_holdout_auc(
        trained.holdout_booster_ubj, examples, head, feature_names=FEATURE_NAMES, holdout_days=7
    )
    assert paired == pytest.approx(trained.metrics.holdout_auc, abs=1e-6)
    # A booster from another feature schema is not scorable on these examples: the gate must fall
    # back to the stored AUC instead of failing the champion asset every day.
    other_schema = xgb.XGBClassifier(n_estimators=2).fit(pd.DataFrame({"not_a_feature": [0, 1, 0, 1]}), [0, 1, 0, 1])
    other_ubj = bytes(other_schema.get_booster().save_raw("ubj"))
    assert booster_holdout_auc(other_ubj, examples, head, feature_names=FEATURE_NAMES, holdout_days=7) is None


def test_train_head_keeps_logloss_on_a_single_class_holdout():
    # Only the newest reports fall in the holdout, and they are all negatives: AUC is undefined
    # there but logloss is not, and the head must still train and ship.
    head = HEADS_BY_NAME["open"]
    rng = np.random.default_rng(1)
    n = 400
    created = pd.to_datetime("2026-07-01", utc=True) + pd.to_timedelta(rng.integers(0, 40, n), unit="D")
    signal_count = rng.integers(1, 50, n)
    rows = pd.DataFrame(
        {
            "signal_count": signal_count,
            "total_weight": rng.random(n),
            "run_count": 1,
            "title_chars": 40,
            "summary_chars": 400,
            "priority": "P2",
            "actionability": None,
            "age_hours": 12.0,
        }
    )
    examples = feature_frame(rows)
    examples.insert(0, "head", head.name)
    examples.insert(1, "report_id", [f"r{i}" for i in range(n)])
    examples.insert(2, "snapshot_date", D0)
    examples.insert(3, "report_created_at", created)
    in_holdout = holdout_mask(examples, 7).to_numpy()
    examples["label"] = ((signal_count > 25) & ~in_holdout).astype(int)

    trained = train_head(examples, head, feature_names=FEATURE_NAMES, holdout_days=7)
    assert trained is not None
    assert trained.metrics.holdout_positives == 0
    assert trained.metrics.holdout_auc is None
    assert trained.metrics.holdout_average_precision is None
    assert trained.metrics.holdout_logloss is not None and trained.metrics.holdout_logloss > 0
    assert not trained.metrics.readable


def test_train_head_returns_none_without_both_classes():
    head = HEADS_BY_NAME["open"]
    examples = pd.DataFrame(
        {
            "head": [head.name] * 3,
            "report_id": ["a", "b", "c"],
            "snapshot_date": D0,
            "report_created_at": pd.to_datetime(["2026-08-01"] * 3, utc=True),
            "label": [0, 0, 0],
        }
    )
    for name in FEATURE_NAMES:
        examples[name] = 1.0
    assert train_head(examples, head, feature_names=FEATURE_NAMES, holdout_days=7) is None


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.client_kwargs: dict[str, Any] = {}
        self.shutdowns = 0

    def capture(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def shutdown(self) -> None:
        self.shutdowns += 1


def _patch_capture(monkeypatch, *, cloud: bool, debug: bool) -> _FakeClient:
    client = _FakeClient()

    def build(region: str, **kwargs: Any) -> _FakeClient:
        client.client_kwargs = kwargs
        return client

    monkeypatch.setattr("products.signals.dags.inbox_ranking.training.telemetry.get_client", build)
    monkeypatch.setattr("products.signals.dags.inbox_ranking.training.telemetry.is_cloud", lambda: cloud)
    monkeypatch.setattr(settings, "DEBUG", debug)
    monkeypatch.setattr(settings, "CLOUD_DEPLOYMENT", "US" if cloud else None)
    return client


def _scores(report_ids: list[str], **overrides) -> pd.DataFrame:
    n = len(report_ids)
    base = {
        "report_id": report_ids,
        "team_id": [2] * n,
        "report_created_at": [pd.Timestamp("2026-08-09T12:00:00Z")] * n,
        "snapshot_date": [D0] * n,
        "pool": [POOL_NAME] * n,
        "model_name": [TABULAR_MODEL_NAME] * n,
        "model_version": ["2026-08-10"] * n,
        "model_role": [CANDIDATE_ROLE] * n,
        "feature_schema_version": [1] * n,
        "head": ["open"] * n,
        "score": [0.5] * n,
        "age_hours": [12.0] * n,
        "label_at_scoring": [False] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_unseen_pool_is_the_reports_born_on_the_partition_day():
    # A report born before D can already be a training example on D, so the pool must exclude it.
    born_on_d0 = pd.Timestamp("2026-08-10T09:00:00Z")
    pool = unseen_pool(
        _state(
            ["a", "b", "c", "d"],
            report_created_at=[born_on_d0, pd.Timestamp("2026-08-09T23:59:59Z"), born_on_d0, born_on_d0],
            signal_count=[3, 3, None, 3],
            features_observed_at=[pd.Timestamp("2026-08-11T04:00:00Z")] * 3 + [pd.Timestamp("2026-08-20T04:00:00Z")],
        ),
        D0,
    )
    # b was born the day before; c has no signal_count and d is a backfill, which build_examples drops too.
    assert pool.index.tolist() == ["a"]


def test_build_examples_never_covers_a_report_born_on_the_partition_day():
    # What the newborn pool rests on: a builder change that reached the partition day would leak.
    head = HEADS_BY_NAME["open"]
    scoring_day = D0 - datetime.timedelta(days=head.horizon_days)
    old, newborn = pd.Timestamp("2026-07-01T00:00:00Z"), pd.Timestamp("2026-08-10T09:00:00Z")
    snapshots = {
        scoring_day: assemble_snapshot(
            scoring_day, _state(["old"], report_created_at=[old]), _labels(["old"], open_count=[0])
        ),
        D0: assemble_snapshot(
            D0,
            _state(["old", "newborn"], report_created_at=[old, newborn]),
            _labels(["old", "newborn"], open_count=[1, 1]),
        ),
    }
    assert set(build_examples(snapshots, head, TABULAR_FEATURE_SET)["report_id"]) == {"old"}


def test_leaked_report_ids_flags_a_pool_report_an_example_already_covers():
    # The guard must fail the asset rather than publish an AUC measured on training data.
    pool = _state(["a", "b"])
    assert leaked_report_ids(pool, ["c"]) == []
    assert leaked_report_ids(pool, ["b", "c"]) == ["b"]


def test_grading_keeps_the_scoring_moment_rows_and_reads_the_outcome_later():
    # Same rule build_examples applies, so the unseen AUC is comparable to the holdout AUC: the
    # outcome must not have happened at scoring time, and the cohort is read at the later snapshot.
    head = HEADS_BY_NAME["open"]
    scores = _scores(["a", "b", "c", "d", "e"], label_at_scoring=[False, True, False, False, False])
    labels = _labels(["a", "b", "c", "e"], open_count=[1, 1, 1, 0], impression_unit_count=[1, 1, 0, 1])
    graded = graded_rows(scores, labels, head).set_index("report_id")
    # b was already opened when it was scored, c was never impressed, d has no labels row at all.
    assert graded["in_cohort"].to_dict() == {"a": True, "b": False, "c": False, "d": False, "e": True}
    assert (graded.loc["a", "outcome"], graded.loc["e", "outcome"]) == (True, False)
    # An excluded row keeps its score with no outcome, so a calibration read can filter on the flag.
    assert graded.loc[["b", "c", "d"], "outcome"].isna().all()


def test_head_grades_report_counts_and_an_undefined_auc_on_a_single_class():
    head = HEADS_BY_NAME["open"]
    labels = _labels(["a", "e"], open_count=[1, 0])
    two_classes = graded_rows(_scores(["a", "e"], score=[0.9, 0.1]), labels, head)
    (grade,) = head_grades(two_classes, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert (grade.rows, grade.positives, grade.auc, grade.base_rate) == (2, 1, 1.0, 0.5)
    assert grade.recency_auc == 0.5  # both reports are the same age, so newest-first cannot rank them
    assert grade.null_auc is not None
    # A head with rows but one outcome class still reports, so the daily series has no gap.
    (single_class,) = head_grades(
        graded_rows(_scores(["e"]), _labels(["e"], open_count=[0]), head),
        head,
        pool=POOL_NAME,
        scoring_partition="2026-08-10",
    )
    assert (single_class.rows, single_class.positives, single_class.auc) == (1, 0, None)
    assert (single_class.null_auc, single_class.null_auc_std) == (None, None)
    # Counts are ints and the undefined AUC is dropped: the graded asset writes these as Dagster
    # metadata. The family is in the key, so a second family cannot overwrite the first's entries.
    metadata = grade_metadata([grade])
    assert metadata["open_tabular_xgb_candidate_rows"] == dagster.MetadataValue.int(2)
    assert metadata["open_tabular_xgb_candidate_auc"] == dagster.MetadataValue.float(1.0)
    assert "open_tabular_xgb_candidate_auc" not in grade_metadata([single_class])


@pytest.mark.parametrize(
    "scores,expected",
    [
        (_scores(["a"]), POOL_NAME),
        # The grader reads scores up to 14 days old, so it still meets objects written before the
        # column existed. Reading one as the current pool would mix two populations in one AUC.
        (_scores(["a"]).drop(columns=["pool"]), LEGACY_POOL_NAME),
    ],
)
def test_scored_pool_names_the_definition_a_scores_object_was_written_under(scores, expected):
    assert scored_pool(scores) == expected


@pytest.mark.parametrize(
    "scores,expected",
    [
        (_scores(["a"]), TABULAR_MODEL_NAME),
        (_scores(["a"], model_name=[EMBEDDINGS_MODEL_NAME]), EMBEDDINGS_MODEL_NAME),
        # A pre-column object is still in the grader's 14-day window, and a null name splits the series.
        (_scores(["a"]).drop(columns=["model_name"]), TABULAR_MODEL_NAME),
        (_scores(["a"], model_name=[None]), TABULAR_MODEL_NAME),
    ],
)
def test_scores_written_before_the_family_dimension_read_as_the_tabular_family(scores, expected):
    assert with_model_names(scores)["model_name"].tolist() == [expected]


def test_head_grades_keep_two_families_apart_on_the_same_rows():
    # A grade keyed on version and role alone would pool two families into one meaningless AUC.
    head = HEADS_BY_NAME["open"]
    labels = _labels(["a", "e"], open_count=[1, 0])
    tabular = _scores(["a", "e"], score=[0.9, 0.1])
    embeddings = _scores(["a", "e"], score=[0.1, 0.9], model_name=[EMBEDDINGS_MODEL_NAME] * 2)
    graded = pd.concat([graded_rows(tabular, labels, head), graded_rows(embeddings, labels, head)], ignore_index=True)
    grades = head_grades(graded, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert [(grade.model_name, grade.model_version, grade.auc) for grade in grades] == [
        (EMBEDDINGS_MODEL_NAME, "2026-08-10", 0.0),
        (TABULAR_MODEL_NAME, "2026-08-10", 1.0),
    ]


def test_chance_band_is_seeded_and_sizes_the_noise_of_the_rows_it_grades():
    # The band must not move between grades of the same rows, and must widen as the rows thin out.
    rng = np.random.default_rng(7)
    outcomes = np.array([True, False] * 40)
    scores = rng.random(80)
    band = chance_band(outcomes, scores)
    assert band == chance_band(outcomes, scores)
    spread = band.auc_std
    assert spread is not None and spread > 0
    thin_band = chance_band(outcomes[:8], scores[:8])
    assert thin_band.auc_std is not None and thin_band.auc_std > spread
    # No band where the AUC itself is undefined, so the chance line has the same gaps as `auc`.
    assert chance_band(np.array([True, True]), scores[:2]) == chance_band(np.array([]), np.array([]))


@pytest.mark.parametrize("rows", [80, 8, 2])
def test_chance_band_holds_the_line_at_half_however_few_rows_it_grades(rows):
    # A sampled mean drifts off 0.5 on a thin head, and two families on the same rows would then
    # report chance lines differing by nothing but their shuffles. Two rows is the extreme case.
    rng = np.random.default_rng(7)
    outcomes = np.array([True, False] * (rows // 2))
    assert chance_band(outcomes, rng.random(rows)).auc == pytest.approx(0.5, abs=1e-9)


@pytest.mark.parametrize(
    "existing_row_count,expected",
    [
        (None, True),  # no object at all, or one written before the row-count stamp
        (0, True),
        (12, False),
    ],
)
def test_an_empty_scores_write_is_refused_over_a_partition_that_holds_rows(existing_row_count, expected):
    # A partition whose candidate predates the family layout loads no model and scores nothing.
    # Overwriting it would destroy rows the later grade reads and the state snapshot cannot rebuild.
    assert empty_scores_write_allowed(existing_row_count) is expected


class _ModelStoreS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}


def test_load_unseen_models_skips_a_family_with_nothing_to_score_that_day(monkeypatch):
    # A family registered before its first trainer run, or one whose candidate failed, must cost only its own line.
    partition_key = "2026-08-19"
    metadata = {
        "model_name": TABULAR_MODEL_NAME,
        "model_version": partition_key,
        "feature_set": TABULAR_FEATURE_SET.name,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "heads": [{"head": "open", "readable": True, "file": "open.ubj"}],
    }
    client = _ModelStoreS3(
        {
            model_object_key("inbox_ranking", TABULAR_MODEL_NAME, partition_key, METADATA_FILE): json.dumps(
                metadata
            ).encode(),
            model_object_key("inbox_ranking", TABULAR_MODEL_NAME, partition_key, "open.ubj"): b"booster",
        }
    )
    monkeypatch.setattr(
        "products.signals.dags.inbox_ranking.training.dag.MODEL_FAMILIES",
        (EMBEDDINGS_MODEL_NAME, TABULAR_MODEL_NAME),
    )
    models = load_unseen_models(dagster.build_asset_context(), client, "bucket", "inbox_ranking", partition_key)
    assert [(model.model_name, model.model_role, sorted(model.boosters)) for model in models] == [
        (TABULAR_MODEL_NAME, CANDIDATE_ROLE, ["open"])
    ]


@pytest.mark.parametrize(
    "cloud,debug,expected_distinct_id,expected_environment",
    [
        (True, False, DISTINCT_ID, "US"),
        (False, True, LOCAL_DISTINCT_ID, "local"),  # a laptop run lands on the dashboard, marked
        (False, False, None, None),  # a self-hosted instance never reports into PostHog's project
    ],
)
def test_training_events_capture_gate_and_local_marking(
    monkeypatch, cloud, debug, expected_distinct_id, expected_environment
):
    client = _patch_capture(monkeypatch, cloud=cloud, debug=debug)
    events = [TrainingEvent(event="inbox_ranking_examples_built", properties={"head": "open"})]
    capture_training_events(dagster.build_asset_context(), "2026-08-25", events)
    if expected_distinct_id is None:
        assert client.calls == []
        return
    assert client.shutdowns == 1
    (call,) = client.calls
    assert call["distinct_id"] == expected_distinct_id
    assert call["properties"]["environment"] == expected_environment


def test_capture_sizes_the_client_queue_to_the_batch(monkeypatch):
    # The SDK drops an event that meets a full queue and reports it only on its own logger. A
    # grading run enqueues one event per report, model and horizon, so a queue left at the
    # 10,000-slot default would lose the tail of the per-report events with nothing in the log.
    client = _patch_capture(monkeypatch, cloud=True, debug=False)
    events = [
        TrainingEvent(event="inbox_ranking_unseen_report_graded", properties={"report_id": str(index)})
        for index in range(10_001)
    ]
    capture_training_events(dagster.build_asset_context(), "2026-08-25", events)
    assert client.client_kwargs["max_queue_size"] >= len(events)


def test_training_events_carry_the_dashboard_contract(monkeypatch):
    # The per-head events are what the project-2 insights break down on; dropping the head
    # property, the partition-day timestamp, or the person-profile opt-out breaks every chart.
    metadata = {
        "model_name": TABULAR_MODEL_NAME,
        "model_version": "2026-08-25",
        "run_id": "run-1",
        "dataset_version": "v1",
        "feature_schema_version": 1,
        "lookback_days": 60,
        "holdout_days": 7,
        "heads": [
            {"head": "open", "holdout_auc": 0.67, "readable": True, "file": "open.ubj", "holdout_file": None},
            {"head": "action", "holdout_auc": None, "readable": False, "file": "action.ubj", "holdout_file": None},
        ],
        "skipped_heads": ["dismiss_wrong"],
    }
    scores = _scores(["a"], model_version=["2026-08-25"], score=[0.8])
    graded = graded_rows(scores, _labels(["a"], open_count=[1]), HEADS_BY_NAME["open"])
    grades = head_grades(graded, HEADS_BY_NAME["open"], pool=POOL_NAME, scoring_partition="2026-08-22")
    events = [
        *candidate_events(metadata),
        *examples_events(
            partition_key="2026-08-25",
            run_id="run-1",
            feature_set=TABULAR_FEATURE_SET.name,
            snapshots=20,
            backfilled_rows=0,
            per_head={"open": HeadExampleCounts(rows=10, positives=2)},
        ),
        promotion_event(
            partition_key="2026-08-25",
            run_id="run-1",
            model_name=TABULAR_MODEL_NAME,
            decision=PromotionDecision(promote=True, reason="no champion yet"),
            promoted=False,
            champion_version="none",
            incumbent_champion_version="none",
            champion_aucs={"open": 0.6},
        ),
        *unseen_score_events(run_id="run-1", rows=score_event_rows(scores, _state(["a"]))),
        *unseen_head_graded_events(run_id="run-1", grades=grades),
        *unseen_report_graded_events(
            run_id="run-1",
            rows=report_grade_rows({"open": graded}, pool=POOL_NAME, horizon_days=3, scoring_partition="2026-08-22"),
        ),
    ]
    client = _patch_capture(monkeypatch, cloud=True, debug=False)
    capture_training_events(dagster.build_asset_context(), "2026-08-25", events)

    by_event: dict[str, list[dict]] = {}
    for call in client.calls:
        by_event.setdefault(call["event"], []).append(call)
        assert call["distinct_id"] == DISTINCT_ID
        assert call["timestamp"] == datetime.datetime(2026, 8, 25, 12, tzinfo=datetime.UTC)
        assert call["properties"]["$process_person_profile"] is False
        assert call["properties"]["model_version"] == "2026-08-25"
    # Every model event breaks down on the family; the examples event is per feature set instead.
    for event_name in (
        "inbox_ranking_candidate_trained",
        "inbox_ranking_promotion_decided",
        "inbox_ranking_unseen_report_scored",
        "inbox_ranking_unseen_head_graded",
        "inbox_ranking_unseen_report_graded",
    ):
        assert all(call["properties"]["model_name"] == TABULAR_MODEL_NAME for call in by_event[event_name])
    candidates = by_event["inbox_ranking_candidate_trained"]
    assert [c["properties"]["head"] for c in candidates] == ["open", "action", "dismiss_wrong"]
    assert candidates[0]["properties"]["holdout_auc"] == 0.67
    assert candidates[0]["properties"]["lookback_days"] == 60
    assert candidates[0]["properties"]["trained"] is True
    assert "file" not in candidates[0]["properties"]
    # A head with nothing to fit still reports, so the readability alert sees a bad day, not a gap.
    assert {"trained": False, "readable": False}.items() <= candidates[2]["properties"].items()
    examples_props = by_event["inbox_ranking_examples_built"][0]["properties"]
    # Examples are per feature set, not per family: this is the dimension the counts break down on.
    assert {
        "head": "open",
        "rows": 10,
        "positives": 2,
        "feature_set": TABULAR_FEATURE_SET.name,
    }.items() <= examples_props.items()
    promotion_props = by_event["inbox_ranking_promotion_decided"][0]["properties"]
    assert {
        "would_promote": True,
        "promoted": False,
        "incumbent_champion_version": "none",
        "champion_open_auc_on_this_holdout": 0.6,
    }.items() <= promotion_props.items()
    # The unseen series is charted next to the holdout series, so it breaks down on the same head
    # property and carries the model it graded; the p_/outcome_ naming is what a calibration read joins on.
    scored_props = by_event["inbox_ranking_unseen_report_scored"][0]["properties"]
    assert {
        "report_id": "a",
        "model_role": CANDIDATE_ROLE,
        "p_open": 0.8,
        "pool": POOL_NAME,
        "unseen_pool": 1,
        "signal_count": 3,
    }.items() <= scored_props.items()
    head_graded_props = by_event["inbox_ranking_unseen_head_graded"][0]["properties"]
    assert {
        "head": "open",
        "model_role": CANDIDATE_ROLE,
        "scoring_partition": "2026-08-22",
        "pool": POOL_NAME,
        "horizon_days": 3,
        "rows": 1,
        "positives": 1,
        "auc": None,
    }.items() <= head_graded_props.items()
    report_graded_props = by_event["inbox_ranking_unseen_report_graded"][0]["properties"]
    assert {
        "report_id": "a",
        "model_role": CANDIDATE_ROLE,
        "scoring_partition": "2026-08-22",
        "pool": POOL_NAME,
        "horizon_days": 3,
        "in_cohort_open": True,
        "outcome_open": True,
        "p_open": 0.8,
    }.items() <= report_graded_props.items()


@pytest.mark.parametrize(
    "holdout_auc,null_auc,holdout_positives,expected",
    [
        (0.46, 0.40, 50, False),  # below chance, yet clears the null margin: the floor must reject it
        (0.70, 0.50, 50, True),  # above chance, clears the margin, enough positives
    ],
)
def test_head_readable_requires_above_chance_auc(holdout_auc, null_auc, holdout_positives, expected):
    assert _head_readable(holdout_auc, null_auc, holdout_positives, min_positives=30) is expected


def _metadata(version: str, **aucs: float | None) -> dict:
    return {
        "model_version": version,
        "heads": [{"head": head, "holdout_auc": auc, "readable": auc is not None} for head, auc in aucs.items()],
    }


@pytest.mark.parametrize(
    "candidate,champion,expected_promote,reason_fragment",
    [
        (_metadata("d2", open=0.65), None, True, "no champion"),
        (_metadata("d2", open=None), None, False, "no readable head"),
        (
            _metadata("d2", open=0.65),
            {**_metadata("d1", open=0.64), "promoted_at": "2026-08-10T00:00:00+00:00"},
            True,
            "at or above",
        ),
        (
            _metadata("d2", open=0.65 - AUC_TOLERANCE - 0.01),
            {**_metadata("d1", open=0.65), "promoted_at": "2026-08-10T00:00:00+00:00"},
            False,
            "regressed",
        ),
        (
            _metadata("d2", open=0.70),
            {**_metadata("d1", open=0.65), "promoted_at": "2026-08-19T00:00:00+00:00"},
            False,
            "less than 3d ago",
        ),
        (
            _metadata("d2", open=0.70),
            {**_metadata("d1", open=0.65, action=0.6), "promoted_at": "2026-08-10T00:00:00+00:00"},
            False,
            "action readable on champion but not on candidate",
        ),
        # A backfilled older candidate, even a much better one, must not roll the champion backwards.
        (
            _metadata("2026-08-11", open=0.90),
            {**_metadata("2026-08-12", open=0.65), "promoted_at": "2026-08-10T00:00:00+00:00"},
            False,
            "not newer",
        ),
        # Re-running the champion's own partition must not re-promote it.
        (
            _metadata("2026-08-12", open=0.90),
            {**_metadata("2026-08-12", open=0.65), "promoted_at": "2026-08-10T00:00:00+00:00"},
            False,
            "not newer",
        ),
    ],
)
def test_decide_promotion(candidate, champion, expected_promote, reason_fragment):
    decision = decide_promotion(candidate, champion, now=NOW, min_days_between=3)
    assert decision.promote is expected_promote
    assert reason_fragment in decision.reason


def test_decide_promotion_grades_the_champion_on_the_candidate_holdout():
    candidate = _metadata("d2", open=0.66)
    champion = {**_metadata("d1", open=0.60), "promoted_at": "2026-08-10T00:00:00+00:00"}
    assert decide_promotion(candidate, champion, now=NOW, min_days_between=3).promote
    # Paired on this holdout the champion is stronger than its stored number said.
    paired = decide_promotion(candidate, champion, now=NOW, min_days_between=3, champion_aucs={"open": 0.75})
    assert not paired.promote and "regressed" in paired.reason


class _FakeS3:
    def __init__(self, keys: list[str]):
        self.keys = set(keys)
        self.deleted: list[str] = []

    def get_paginator(self, _name):
        return self

    def paginate(self, *, Bucket, Prefix):
        yield {"Contents": [{"Key": key} for key in sorted(self.keys) if key.startswith(Prefix)]}

    def delete_objects(self, *, Bucket, Delete):
        self.deleted = [obj["Key"] for obj in Delete["Objects"]]
        self.keys -= set(self.deleted)


def test_rerun_removes_stale_head_files_but_keeps_what_it_just_wrote():
    folder = model_object_key("inbox_ranking", TABULAR_MODEL_NAME, "2026-08-19", "")
    champion = champion_object_key("inbox_ranking", TABULAR_MODEL_NAME)
    written = {folder + "open.ubj", folder + "open.holdout.ubj", folder + "metadata.json"}
    client = _FakeS3([*written, folder + "action.ubj", champion])
    assert _delete_other_objects(client, "bucket", folder, written) == [folder + "action.ubj"]
    assert client.keys == written | {champion}


class _EmptyS3:
    def get_object(self, *, Bucket, Key):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def test_load_snapshots_fails_without_the_requested_partition():
    dates = snapshot_dates("2026-08-19", 2)
    assert load_snapshots(_EmptyS3(), "bucket", "inbox_ranking", dates) == {}
    with pytest.raises(dagster.Failure, match="2026-08-19"):
        load_snapshots(_EmptyS3(), "bucket", "inbox_ranking", dates, required=dates[-1])


def test_examples_depend_on_the_whole_lookback_window():
    # An asset backfill must not run examples(D) before the older state and labels days exist.
    for upstream in (STATE_TABLE, LABELS_TABLE):
        mapping = inbox_ranking_training_examples.get_partition_mapping(dagster.AssetKey(upstream))
        assert isinstance(mapping, dagster.TimeWindowPartitionMapping)
        assert mapping.start_offset == -settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS
        assert mapping.end_offset == 0


def test_model_key_layout_is_stable():
    # The scoring sweep resolves these keys, and a prefix per family stops two families colliding.
    assert (
        model_object_key("inbox_ranking", TABULAR_MODEL_NAME, "2026-08-19", "open.ubj")
        == "inbox_ranking/inbox_ranking_models/v1/tabular_xgb/dt=2026-08-19/open.ubj"
    )
    assert (
        champion_object_key("inbox_ranking", TABULAR_MODEL_NAME)
        == "inbox_ranking/inbox_ranking_models/v1/tabular_xgb/champion.json"
    )
    assert snapshot_dates("2026-08-19", 2) == [
        datetime.date(2026, 8, 17),
        datetime.date(2026, 8, 18),
        datetime.date(2026, 8, 19),
    ]


class _AgeOnlyFeatureSet(FeatureSet):
    """A second set for the tests: no trainer writes one yet, so this stands in for a family that
    reads different features on the same rows."""

    name = "age_only"
    schema_version = 1
    feature_names = ("age_hours",)
    state_columns = ()

    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        return rows[["age_hours"]].astype(float)


class _CountingFeatureSet(FeatureSet):
    """`inner`, counting how many matrices are built from it."""

    def __init__(self, inner: FeatureSet) -> None:
        self.inner = inner
        self.name = inner.name
        self.schema_version = inner.schema_version
        self.feature_names = inner.feature_names
        self.state_columns = inner.state_columns
        self.builds = 0

    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        self.builds += 1
        return self.inner.build_matrix(rows, extras)


def _booster_ubj(feature_names: tuple[str, ...]) -> bytes:
    rows = 20
    x = pd.DataFrame({name: np.linspace(0.0, 1.0, rows) for name in feature_names})
    model = xgb.XGBClassifier(n_estimators=2, max_depth=2)
    model.fit(x, np.arange(rows) % 2)
    return bytes(model.get_booster().save_raw("ubj"))


def _unseen_model(model_name: str, feature_set: FeatureSet, role: str = CANDIDATE_ROLE) -> UnseenModel:
    return UnseenModel(
        model_name=model_name,
        model_version="2026-08-10",
        model_role=role,
        feature_set=feature_set,
        boosters={"open": _booster_ubj(tuple(feature_set.feature_names))},
    )


def test_score_pool_builds_one_matrix_per_feature_set_and_shares_it():
    # Two models on one set must reuse its matrix, and a model on another set must get its own.
    # Scoring every model against a single matrix would feed the second set the wrong columns.
    tabular = _CountingFeatureSet(TABULAR_FEATURE_SET)
    age_only = _CountingFeatureSet(_AgeOnlyFeatureSet())
    models = [
        _unseen_model(TABULAR_MODEL_NAME, tabular),
        _unseen_model(TABULAR_MODEL_NAME, tabular, role=CHAMPION_ROLE),
        _unseen_model(EMBEDDINGS_MODEL_NAME, age_only),
    ]
    scores = score_pool(_state(["a", "b"]), _labels(["a", "b"]), models, snapshot_date=D0)

    assert (tabular.builds, age_only.builds) == (1, 1)
    assert list(scores.columns) == list(SCORE_COLUMNS)
    assert scores.groupby(["model_name", "model_role"]).size().to_dict() == {
        (TABULAR_MODEL_NAME, CANDIDATE_ROLE): 2,
        (TABULAR_MODEL_NAME, CHAMPION_ROLE): 2,
        (EMBEDDINGS_MODEL_NAME, CANDIDATE_ROLE): 2,
    }
    # Each row carries the schema version of the set its model was fit on, not one global version.
    assert set(scores.loc[scores["model_name"] == EMBEDDINGS_MODEL_NAME, "feature_schema_version"]) == {
        age_only.schema_version
    }


def _model_metadata(**overrides) -> dict[str, Any]:
    base = {
        "feature_set": TABULAR_FEATURE_SET.name,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "metadata,expected",
    [
        (_model_metadata(), None),
        # Written before the field existed: every one of those models is tabular.
        ({key: value for key, value in _model_metadata().items() if key != "feature_set"}, None),
        (_model_metadata(feature_set="report_embeddings"), "this build can produce"),
        (_model_metadata(feature_schema_version=99), "feature_schema_version 99"),
        (_model_metadata(feature_names=["age_hours"]), "feature_names differ"),
    ],
)
def test_model_mismatch_checks_a_model_against_its_own_feature_set(metadata, expected):
    # A family on a richer set must not be rejected for disagreeing with the tabular contract, and
    # a set this build cannot produce must not be scored on whatever matrix happens to be at hand.
    mismatch = model_mismatch(metadata)
    assert expected is None and mismatch is None or (mismatch is not None and expected in mismatch)


def test_candidate_metadata_declares_the_set_it_was_fit_on():
    # The trainer's own record must pass the grader's check, or the day's candidate goes unscored.
    metadata = candidate_metadata(
        "2026-08-19",
        [],
        model_name=TABULAR_MODEL_NAME,
        feature_set=TABULAR_FEATURE_SET,
        skipped=[],
        trained_at=NOW,
        run_id="run-1",
    )
    assert metadata["feature_set"] == TABULAR_FEATURE_SET.name
    assert metadata["feature_schema_version"] == TABULAR_FEATURE_SET.schema_version
    assert model_mismatch(metadata) is None


def test_build_examples_carries_the_columns_of_the_set_it_is_given():
    # The examples Parquet is per feature set, so a second set's object holds its own features.
    ids = ["a"]
    later = D0 + datetime.timedelta(days=3)
    snapshots = {
        D0: Snapshot(date=D0, state=_state(ids), labels=_labels(ids)),
        later: Snapshot(date=later, state=_state(ids), labels=_labels(ids, open_count=[2])),
    }
    examples = build_examples(snapshots, HEADS_BY_NAME["open"], _AgeOnlyFeatureSet())
    assert list(examples.columns) == ["head", "report_id", "snapshot_date", "report_created_at", "age_hours", "label"]
    assert examples["age_hours"].tolist() == [12.0]


def test_examples_key_layout_is_per_feature_set():
    # Two sets carry different feature columns, so they cannot share a partition's object.
    assert (
        examples_object_key("inbox_ranking", TABULAR_FEATURE_SET.name, "2026-08-19")
        == "inbox_ranking/inbox_ranking_training_examples/v1/tabular/dt=2026-08-19/part-00000.parquet"
    )
