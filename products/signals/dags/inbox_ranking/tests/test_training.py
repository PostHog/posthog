import io
import copy
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
    BIRTH_GRAIN,
    EMBEDDING_COLUMN,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_INSERTED_AT_COLUMN,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    NO_EXTRAS,
    REPORT_EMBEDDINGS_EXTRA,
    REPORT_EMBEDDINGS_FEATURE_SET,
    REPORT_GRAIN,
    SCORING_MOMENT_GRAIN,
    TABULAR_FEATURE_SET,
    TITLE_EMBEDDINGS_EXTRA,
    TITLE_EMBEDDINGS_FEATURE_SET,
    Extras,
    FeatureSet,
    feature_frame,
    feature_set_by_name,
    feature_vector,
)
from products.signals.dags.inbox_ranking.common import partition_object_key
from products.signals.dags.inbox_ranking.dataset.dag import (
    EMBEDDINGS_TABLE,
    LABELS_TABLE,
    STATE_TABLE,
    TITLE_EMBEDDINGS_TABLE,
)
from products.signals.dags.inbox_ranking.training.calibration import (
    BUCKETS,
    calibration_buckets,
    expected_calibration_error,
)
from products.signals.dags.inbox_ranking.training.dag import (
    _EXTRA_SNAPSHOT_TABLES,
    METADATA_FILE,
    _delete_other_objects,
    _train_candidate,
    candidate_metadata,
    champion_object_key,
    embeddings_extras,
    examples_object_key,
    grade_metadata,
    inbox_ranking_training_examples,
    inbox_ranking_unseen_scores,
    load_snapshots,
    load_unseen_models,
    model_object_key,
    models_with_extras,
    pool_feature_coverage,
    snapshot_dates,
)
from products.signals.dags.inbox_ranking.training.examples import (
    STATE_LAG_LIMIT,
    Snapshot,
    assemble_snapshot,
    birth_day_positives,
    build_examples,
    cap_examples,
    example_columns,
    holdout_mask,
    reports_missing_birth_snapshot,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head, dismissed_as_wrong
from products.signals.dags.inbox_ranking.training.promotion import AUC_TOLERANCE, PromotionDecision, decide_promotion
from products.signals.dags.inbox_ranking.training.telemetry import (
    DISTINCT_ID,
    LOCAL_DISTINCT_ID,
    HeadExampleCounts,
    TrainingEvent,
    candidate_events,
    capture_training_events,
    examples_events,
    holdout_calibration_events,
    promotion_event,
    unseen_calibration_events,
    unseen_head_graded_events,
    unseen_report_graded_events,
    unseen_score_events,
)
from products.signals.dags.inbox_ranking.training.train import _head_readable, booster_holdout_auc, train_head
from products.signals.dags.inbox_ranking.training.unseen import (
    CANDIDATE_ROLE,
    CHAMPION_ROLE,
    LEGACY_POOL_NAME,
    MODEL_FAMILIES,
    POOL_NAME,
    REPORT_EMBEDDINGS_MODEL_NAME,
    SCORE_COLUMNS,
    TABULAR_MODEL_NAME,
    TITLE_EMBEDDINGS_MODEL_NAME,
    ModelFamily,
    UnseenModel,
    calibration_rows,
    chance_band,
    empty_scores_write_allowed,
    families_lost_by_rewrite,
    graded_rows,
    head_grades,
    leaked_report_ids,
    model_mismatch,
    readable_head_names,
    report_grade_rows,
    score_event_rows,
    score_pool,
    scored_pool,
    trained_head_files,
    unseen_pool,
    with_model_names,
)

EMBEDDINGS_MODEL_NAME = REPORT_EMBEDDINGS_MODEL_NAME
# The two renderings' sets. Every rule about a vector holds for both, because they are one class
# parameterized by the input it reads, so the embedding tests below run over the pair.
EMBEDDING_FEATURE_SETS = (REPORT_EMBEDDINGS_FEATURE_SET, TITLE_EMBEDDINGS_FEATURE_SET)
EMBEDDING_SET_IDS = [feature_set.name for feature_set in EMBEDDING_FEATURE_SETS]
_EMBEDDING_EXTRA_KEYS = (REPORT_EMBEDDINGS_EXTRA, TITLE_EMBEDDINGS_EXTRA)

D0 = datetime.date(2026, 8, 10)
NOW = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)


# Midday on D0, so a default report is born on the first snapshot day the tests build and the
# birth grain keeps it. A test about any other grain passes its own `report_created_at`.
BIRTH = pd.Timestamp("2026-08-10T12:00:00Z")
BEFORE_THE_WINDOW = pd.Timestamp("2026-07-01T00:00:00Z")


def _state(report_ids: list[str], **overrides) -> pd.DataFrame:
    n = len(report_ids)
    base = {
        "report_created_at": [BIRTH] * n,
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


def _at_grain(feature_set: FeatureSet, grain: str) -> FeatureSet:
    """`feature_set` with a different example grain, so a test can pin one grain's rows."""
    variant = copy.copy(feature_set)
    variant.example_grain = grain
    return variant


def _daily_snapshots(
    ids: list[str], head: Head, created: list[pd.Timestamp], *, days: int = 2
) -> dict[datetime.date, Snapshot]:
    snapshots: dict[datetime.date, Snapshot] = {}
    for offset in range(days):
        day = D0 + datetime.timedelta(days=offset)
        state = _state(ids, report_created_at=created)
        snapshots[day] = Snapshot(date=day, state=state, labels=_labels(ids, open_count=[0] * len(ids)))
        partner = day + datetime.timedelta(days=head.horizon_days)
        snapshots[partner] = Snapshot(date=partner, state=state, labels=_labels(ids, open_count=[1] * len(ids)))
    return snapshots


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
    # The grain a re-scoring family would ask for: a row per snapshot, censored once the outcome is
    # visible. Every report here is older than D0, so no birth-day exemption applies.
    open_head = HEADS_BY_NAME["open"]
    later = D0 + datetime.timedelta(days=open_head.horizon_days)
    ids = ["a", "b", "c", "d"]
    state = _state(ids, report_created_at=[BEFORE_THE_WINDOW] * 4)
    snapshots = {
        # a: not yet impressed or opened at D0, impressed and opened by D0+3 -> positive;
        # b: already opened at D0 -> excluded; c: never opened -> negative;
        # d: never impressed -> outside the cohort.
        D0: Snapshot(
            date=D0,
            state=state,
            labels=_labels(ids, open_count=[0, 1, 0, 0], impression_unit_count=[0, 1, 1, 0]),
        ),
        later: Snapshot(
            date=later,
            state=state,
            labels=_labels(ids, open_count=[2, 3, 0, 0], impression_unit_count=[1, 1, 1, 0]),
        ),
        # A snapshot with no horizon partner contributes nothing.
        later + datetime.timedelta(days=1): Snapshot(date=later, state=state, labels=_labels(ids)),
    }
    examples = build_examples(snapshots, open_head, _at_grain(TABULAR_FEATURE_SET, SCORING_MOMENT_GRAIN))
    assert list(examples.columns) == list(example_columns(TABULAR_FEATURE_SET))
    assert examples.set_index("report_id")["label"].to_dict() == {"a": 1, "c": 0}
    assert (examples["snapshot_date"] == D0).all()
    assert (examples["age_hours"] == 12.0).all()


def test_assemble_snapshot_makes_never_labeled_reports_negatives_and_drops_untrusted_status_rows():
    head = HEADS_BY_NAME["pr_created"]
    wrong_head = HEADS_BY_NAME["dismiss_wrong"]
    assert wrong_head.horizon_days == 14
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
        # The two heads read different horizons off the same day.
        D0 + datetime.timedelta(days=wrong_head.horizon_days): assemble_snapshot(
            D0 + datetime.timedelta(days=wrong_head.horizon_days), state_later, labels_later
        ),
    }

    assert snapshots[D0].labels.loc["b", "impression_unit_count"] == 0
    assert snapshots[D0].labels["label_provenance_ok"].to_dict() == {"a": False, "b": True, "c": True, "gone": True}
    assert snapshots[later].labels["label_provenance_ok"].to_dict() == {"a": False, "b": True, "c": True, "gone": False}
    # pr_created reads the tasks webhook, so a's untrusted status telemetry does not exclude it there.
    pr = build_examples(snapshots, head, TABULAR_FEATURE_SET).set_index("report_id")["label"].to_dict()
    assert pr == {"a": 0, "b": 0, "c": 1, "gone": 1}
    # dismiss_wrong reads the status stream: a is dropped, b was never impressed, c is a positive.
    wrong = build_examples(snapshots, wrong_head, TABULAR_FEATURE_SET).set_index("report_id")["label"].to_dict()
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
        # pr_merged: cohort is everyone, label is the merge within the horizon, whether or not the
        # report already had a PR at the scoring moment.
        (
            "pr_merged",
            pd.DataFrame({"pr_created_count": [1, 1, 0], "pr_merged_count": [1, 0, 1]}),
            [True, True, True],
            [True, False, True],
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
        # thumbs_up: cohort is opened reports, label is a positive rating.
        (
            "thumbs_up",
            pd.DataFrame({"open_count": [1, 1, 0], "feedback_positive_count": [1, 0, 0]}),
            [True, True, False],
            [True, False, False],
        ),
        # reviewer_fix: cohort is impressed reports, and an add or a remove is the same label.
        (
            "reviewer_fix",
            pd.DataFrame(
                {
                    "impression_unit_count": [1, 1, 1, 0],
                    "reviewer_add_count": [1, 0, 0, 0],
                    "reviewer_remove_count": [0, 2, 0, 0],
                }
            ),
            [True, True, True, False],
            [True, True, False, False],
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


@pytest.mark.parametrize("head_name", ["pr_merged", "refund", "thumbs_up", "reviewer_fix"])
def test_new_head_label_columns_survive_the_load_snapshots_projection(head_name):
    # load_snapshots projects the labels parquet down to _LABEL_COLUMNS before any head sees it, so a
    # head whose label column is missing from that list trains on all-zero labels. The cohort/label
    # unit test hand-builds frames that already carry the columns, so it never crosses the projection.
    # Drive the real parquet -> projection -> build_examples path and assert a positive label survives.
    head = HEADS_BY_NAME[head_name]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    labels_now = _labels(
        ["a"],
        open_count=[1],
        pr_created_count=[0],
        pr_merged_count=[0],
        refund_count=[0],
        feedback_positive_count=[0],
        reviewer_add_count=[0],
        reviewer_remove_count=[0],
    )
    labels_later = _labels(
        ["a"],
        open_count=[1],
        pr_created_count=[1],
        pr_merged_count=[1],
        refund_count=[1],
        feedback_positive_count=[1],
        reviewer_add_count=[1],
        reviewer_remove_count=[0],
    )
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
    # With no positive in the holdout, the decile error is the whole mean score.
    assert len(trained.calibration) == BUCKETS
    assert trained.metrics.holdout_mean_score is not None
    assert trained.metrics.holdout_expected_calibration_error == pytest.approx(trained.metrics.holdout_mean_score)


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
        # The default pool is the newborn one, so the default row was born on the day it was scored.
        "report_created_at": [pd.Timestamp("2026-08-10T09:00:00Z")] * n,
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


@pytest.mark.parametrize("grain", [BIRTH_GRAIN, SCORING_MOMENT_GRAIN, REPORT_GRAIN])
def test_build_examples_never_covers_a_report_born_on_the_partition_day(grain):
    # What the newborn pool rests on: a builder change that reached the partition day would leak,
    # and every grain a set can select has to keep that property.
    head = HEADS_BY_NAME["open"]
    scoring_day = D0 - datetime.timedelta(days=head.horizon_days)
    newborn = pd.Timestamp("2026-08-10T09:00:00Z")
    snapshots = {
        scoring_day: assemble_snapshot(
            scoring_day,
            _state(["old"], report_created_at=[pd.Timestamp(scoring_day, tz="UTC")]),
            _labels(["old"], open_count=[0]),
        ),
        D0: assemble_snapshot(
            D0,
            _state(["old", "newborn"], report_created_at=[pd.Timestamp(scoring_day, tz="UTC"), newborn]),
            _labels(["old", "newborn"], open_count=[1, 1]),
        ),
    }
    examples = build_examples(snapshots, head, _at_grain(TABULAR_FEATURE_SET, grain))
    assert set(examples["report_id"]) == {"old"}


@pytest.mark.parametrize("feature_set", [TABULAR_FEATURE_SET, *EMBEDDING_FEATURE_SETS])
def test_birth_grain_keeps_one_row_per_report_on_the_day_it_was_created(feature_set):
    head = HEADS_BY_NAME["open"]
    ids = ["newborn", "older", "utc_start", "utc_end"]
    created = [
        BIRTH,
        BEFORE_THE_WINDOW,
        pd.Timestamp("2026-08-09T20:00:00-04:00"),
        pd.Timestamp("2026-08-10T20:00:00-04:00"),
    ]
    snapshots = _daily_snapshots(ids, head, created, days=3)
    snapshots[D0 + datetime.timedelta(days=head.horizon_days)].labels.loc[:, "open_count"] = 0
    # Both renderings' inputs, so the parameter that varies is the set under test and not what it
    # was handed. The tabular set reads neither.
    extras = {key: _vector_frame({report_id: _embedding() for report_id in ids}) for key in _EMBEDDING_EXTRA_KEYS}

    examples = build_examples(snapshots, head, feature_set, extras)

    assert feature_set.example_grain == BIRTH_GRAIN
    assert examples["report_id"].is_unique
    assert examples.set_index("report_id")[["snapshot_date", "label"]].to_dict("index") == {
        "newborn": {"snapshot_date": D0, "label": 0},
        "utc_start": {"snapshot_date": D0, "label": 0},
        "utc_end": {"snapshot_date": D0 + datetime.timedelta(days=1), "label": 1},
    }
    moments = build_examples(snapshots, head, _at_grain(feature_set, SCORING_MOMENT_GRAIN), extras)
    assert moments[moments["report_id"] == "newborn"]["label"].tolist() == [0, 1, 1]


def test_pr_merged_is_a_merge_from_birth_rather_than_a_merge_given_a_pr():
    head = HEADS_BY_NAME["pr_merged"]
    assert head.horizon_days == 14
    later = D0 + datetime.timedelta(days=14)
    merged_day = D0 + datetime.timedelta(days=10)
    ids = ["merged", "unmerged", "nothing"]
    snapshots = {
        D0: assemble_snapshot(D0, _state(ids), _labels(ids, pr_created_count=[0, 1, 0], pr_merged_count=[0, 0, 0])),
        **{
            date: assemble_snapshot(
                date, _state(ids), _labels(ids, pr_created_count=[1, 1, 0], pr_merged_count=[1, 0, 0])
            )
            for date in (merged_day, later)
        },
    }

    examples = build_examples(snapshots, head, TABULAR_FEATURE_SET)

    assert examples.set_index("report_id")["label"].to_dict() == {"merged": 1, "unmerged": 0, "nothing": 0}


def test_reports_missing_birth_snapshot_counts_only_the_ones_a_partition_gap_costs(monkeypatch):
    gap = D0 + datetime.timedelta(days=1)
    dates = [D0 + datetime.timedelta(days=offset) for offset in range(6)]
    ids = ["born_in_the_gap", "older", "utc_start", "utc_end", "label_only"]
    created = [
        pd.Timestamp(gap, tz="UTC") + pd.Timedelta(hours=9),
        BEFORE_THE_WINDOW,
        pd.Timestamp("2026-08-10T20:00:00-04:00"),
        pd.Timestamp("2026-08-11T20:00:00-04:00"),
        pd.NaT,
    ]
    snapshots = {
        date: Snapshot(date=date, state=_state(ids, report_created_at=created), labels=_labels(ids))
        for date in dates
        if date != gap
    }

    assert reports_missing_birth_snapshot(snapshots, dates) == 2
    assert reports_missing_birth_snapshot({}, dates) == 0
    examples = build_examples(snapshots, HEADS_BY_NAME["open"], TABULAR_FEATURE_SET)
    assert examples["report_id"].tolist() == ["utc_end"]

    module = "products.signals.dags.inbox_ranking.training.dag"
    monkeypatch.setattr(f"{module}.skip_unconfigured", lambda context: False)
    monkeypatch.setattr(f"{module}.s3_client", lambda: None)
    monkeypatch.setattr(f"{module}.snapshot_dates", lambda *args: dates)
    monkeypatch.setattr(f"{module}.load_snapshots", lambda *args, **kwargs: snapshots)
    monkeypatch.setattr(f"{module}.embeddings_extras", lambda *args: NO_EXTRAS)
    monkeypatch.setattr(f"{module}._write_examples", lambda *args: {})
    with dagster.build_asset_context(partition_key=dates[-1].isoformat()) as context:
        inbox_ranking_training_examples(context)
        assert context.get_output_metadata("result")["reports_missing_birth_snapshot"].value == 2


def test_build_examples_keeps_an_outcome_that_landed_on_the_reports_birth_day():
    # Most PRs land the day the report is born. Censoring on the labels of the birth day would
    # drop those positives from the head that predicts them.
    head = HEADS_BY_NAME["pr_created"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    ids = ["newborn", "old"]
    created = [pd.Timestamp("2026-08-10T09:00:00Z"), pd.Timestamp("2026-07-01T00:00:00Z")]
    snapshots = {
        date: assemble_snapshot(date, _state(ids, report_created_at=created), _labels(ids, pr_created_count=[1, 1]))
        for date in (D0, later)
    }
    examples = build_examples(snapshots, head, TABULAR_FEATURE_SET)
    # The old report's PR predates D0, so it belongs to a moment before D0 and stays censored.
    assert examples.set_index("report_id")["label"].to_dict() == {"newborn": 1}
    assert birth_day_positives(examples) == 1


def test_leaked_report_ids_flags_a_pool_report_an_example_already_covers():
    # The guard must fail the asset rather than publish an AUC measured on training data.
    pool = _state(["a", "b"])
    assert leaked_report_ids(pool, ["c"]) == []
    assert leaked_report_ids(pool, ["b", "c"]) == ["b"]


def test_grading_keeps_the_scoring_moment_rows_and_reads_the_outcome_later():
    # Same rule build_examples applies, so the unseen AUC is comparable to the holdout AUC: the
    # cohort is read at the later snapshot, and a newborn keeps the outcome that landed on its
    # own birth day, which is where most outcomes land.
    head = HEADS_BY_NAME["open"]
    scores = _scores(["a", "b", "c", "d", "e"], label_at_scoring=[False, True, False, False, False])
    labels = _labels(["a", "b", "c", "e"], open_count=[1, 1, 1, 0], impression_unit_count=[1, 1, 0, 1])
    graded = graded_rows(scores, labels, head, pool=POOL_NAME).set_index("report_id")
    # c was never impressed and d has no labels row at all; b was opened on its birth day, which
    # the newborn pool grades rather than drops.
    assert graded["in_cohort"].to_dict() == {"a": True, "b": True, "c": False, "d": False, "e": True}
    assert (graded.loc["a", "outcome"], graded.loc["b", "outcome"], graded.loc["e", "outcome"]) == (True, True, False)
    # An excluded row keeps its score with no outcome, so a calibration read can filter on the flag.
    assert graded.loc[["c", "d"], "outcome"].isna().all()


def test_grading_an_older_pool_still_drops_an_outcome_that_predates_the_score():
    # The legacy sampled pool held reports of any age, so an outcome already observed at scoring
    # time belongs to an earlier moment there and must stay out of the grade.
    head = HEADS_BY_NAME["open"]
    scores = _scores(
        ["a", "b"],
        pool=[LEGACY_POOL_NAME] * 2,
        report_created_at=[pd.Timestamp("2026-07-01T00:00:00Z")] * 2,
        label_at_scoring=[False, True],
    )
    labels = _labels(["a", "b"], open_count=[1, 1], impression_unit_count=[1, 1])
    graded = graded_rows(scores, labels, head, pool=LEGACY_POOL_NAME).set_index("report_id")
    assert graded["in_cohort"].to_dict() == {"a": True, "b": False}


def test_grading_a_status_label_head_drops_a_newborn_outcome_from_the_scoring_day():
    # build_examples reads label_provenance_ok on the scoring snapshot too, and no scores column
    # carries that verdict, so grading the row would accept a label the builder can still refuse.
    head = HEADS_BY_NAME["dismiss_wrong"]
    scores = _scores(["a", "b"], label_at_scoring=[False, True])
    labels = _labels(
        ["a", "b"],
        wrong_dismissal_count=[1, 1],
        impression_unit_count=[1, 1],
        label_provenance_ok=[True, True],
    )
    graded = graded_rows(scores, labels, head, pool=POOL_NAME).set_index("report_id")
    assert graded["in_cohort"].to_dict() == {"a": True, "b": False}


def test_head_grades_report_counts_and_an_undefined_auc_on_a_single_class():
    head = HEADS_BY_NAME["open"]
    labels = _labels(["a", "e"], open_count=[1, 0])
    scores = _scores(["a", "e"], score=[0.9, 0.1], label_at_scoring=[True, False])
    two_classes = graded_rows(scores, labels, head, pool=POOL_NAME)
    (grade,) = head_grades(two_classes, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert (grade.rows, grade.positives, grade.auc, grade.base_rate) == (2, 1, 1.0, 0.5)
    # a was opened on its birth day, so the grade says how much of its signal that day carries.
    assert grade.birth_day_positives == 1
    assert grade.recency_auc == 0.5  # both reports are the same age, so newest-first cannot rank them
    assert grade.null_auc is not None
    # A head with rows but one outcome class still reports, so the daily series has no gap.
    (single_class,) = head_grades(
        graded_rows(_scores(["e"]), _labels(["e"], open_count=[0]), head, pool=POOL_NAME),
        head,
        pool=POOL_NAME,
        scoring_partition="2026-08-10",
    )
    assert (single_class.rows, single_class.positives, single_class.auc) == (1, 0, None)
    assert (single_class.null_auc, single_class.null_auc_std) == (None, None)
    # No AUC, and the score gap is still readable.
    assert (single_class.mean_score, single_class.expected_calibration_error) == (0.5, 0.5)
    # Counts are ints and the undefined AUC is dropped: the graded asset writes these as Dagster
    # metadata. The family is in the key, so a second family cannot overwrite the first's entries.
    metadata = grade_metadata([grade])
    assert metadata["open_tabular_xgb_candidate_rows"] == dagster.MetadataValue.int(2)
    assert metadata["open_tabular_xgb_candidate_auc"] == dagster.MetadataValue.float(1.0)
    assert "open_tabular_xgb_candidate_auc" not in grade_metadata([single_class])


def test_calibration_buckets_keep_a_run_of_tied_scores_in_one_bucket():
    # Splitting a run of equal scores would give each half a realized rate that depends on the
    # order the rows arrived in, and report a gap that is not there.
    scores = np.array([0.1] * 8 + [1.0, 1.0])
    outcomes = np.array([False] * 8 + [True, True])
    buckets = calibration_buckets(outcomes, scores, buckets=5)
    assert [(bucket.bucket, bucket.rows, bucket.realized_rate) for bucket in buckets] == [(1, 8, 0.0), (2, 2, 1.0)]
    # Row-weighted, so the perfectly calibrated top bucket does not count for half of the error.
    assert expected_calibration_error(buckets) == pytest.approx(0.08)


def test_calibration_error_on_tied_scores_does_not_move_with_the_row_order():
    # Ten of twenty reports on one score opened: that score is calibrated, however the frame is
    # ordered. A split run would read 0.0 interleaved and 0.5 grouped.
    tied = np.full(20, 0.5)
    interleaved = calibration_buckets(np.array([True, False] * 10), tied)
    grouped = calibration_buckets(np.array([True] * 10 + [False] * 10), tied)
    assert expected_calibration_error(interleaved) == expected_calibration_error(grouped) == 0.0


def test_calibration_buckets_fill_the_table_when_the_scores_are_distinct():
    rng = np.random.default_rng(0)
    scores = rng.random(100)
    buckets = calibration_buckets(rng.random(100) < scores, scores)
    assert len(buckets) == BUCKETS
    assert sum(bucket.rows for bucket in buckets) == 100


def test_calibration_reads_a_cohort_thinner_than_the_table_without_an_empty_bucket():
    buckets = calibration_buckets(np.array([True, False]), np.array([0.7, 0.2]))
    assert [(bucket.bucket, bucket.rows, bucket.mean_score, bucket.realized_rate) for bucket in buckets] == [
        (1, 1, 0.2, 0.0),
        (2, 1, 0.7, 1.0),
    ]
    assert expected_calibration_error(()) is None


def test_head_grades_report_the_score_gap_a_perfect_auc_hides():
    # Perfectly ranked and far too confident. AUC is 1.0 and says nothing about the gap, which is
    # what a composite score over two heads runs on.
    head = HEADS_BY_NAME["open"]
    report_ids = [f"r{index}" for index in range(10)]
    labels = _labels(report_ids, open_count=[1] + [0] * 9)
    scores = _scores(report_ids, score=[0.95, *[0.5] * 9])
    (grade,) = head_grades(
        graded_rows(scores, labels, head, pool=POOL_NAME), head, pool=POOL_NAME, scoring_partition="2026-08-10"
    )
    assert grade.auc == 1.0
    assert grade.base_rate == 0.1
    assert grade.mean_score == pytest.approx(0.545)
    assert grade.expected_calibration_error == pytest.approx(0.455)
    rows = calibration_rows([grade])
    assert [(row["bucket"], row["rows"]) for row in rows] == [(1, 9), (2, 1)]
    assert sum(bucket.rows for bucket in grade.calibration) == grade.rows
    assert {
        "head": "open",
        "model_name": TABULAR_MODEL_NAME,
        "model_role": CANDIDATE_ROLE,
        "pool": POOL_NAME,
        "bucket": 2,
        "positives": 1,
        "mean_score": 0.95,
        "realized_rate": 1.0,
    }.items() <= rows[-1].items()


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


def test_head_grades_keep_every_family_apart_on_the_same_rows():
    # A grade keyed on version and role alone would pool the families into one meaningless AUC.
    # Three of them now, and the paired title-against-combined read is a difference of two of these
    # grades, so a family whose rows leaked into another's would be read as a text effect.
    head = HEADS_BY_NAME["open"]
    labels = _labels(["a", "e"], open_count=[1, 0])
    per_family = {
        TABULAR_MODEL_NAME: [0.9, 0.1],
        EMBEDDINGS_MODEL_NAME: [0.1, 0.9],
        TITLE_EMBEDDINGS_MODEL_NAME: [0.8, 0.2],
    }
    graded = pd.concat(
        [
            graded_rows(_scores(["a", "e"], score=score, model_name=[model_name] * 2), labels, head, pool=POOL_NAME)
            for model_name, score in per_family.items()
        ],
        ignore_index=True,
    )
    grades = head_grades(graded, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert [(grade.model_name, grade.rows, grade.auc) for grade in grades] == [
        (EMBEDDINGS_MODEL_NAME, 2, 0.0),
        (TABULAR_MODEL_NAME, 2, 1.0),
        (TITLE_EMBEDDINGS_MODEL_NAME, 2, 1.0),
    ]
    # And the calibration read follows the grade, so each family has its own deciles.
    assert {row["model_name"] for row in calibration_rows(grades)} == set(per_family)


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


@pytest.mark.parametrize(
    "existing,scored,expected",
    [
        (
            [TABULAR_MODEL_NAME, EMBEDDINGS_MODEL_NAME, TITLE_EMBEDDINGS_MODEL_NAME],
            [TABULAR_MODEL_NAME, EMBEDDINGS_MODEL_NAME],
            [TITLE_EMBEDDINGS_MODEL_NAME],
        ),
        (
            [TABULAR_MODEL_NAME, EMBEDDINGS_MODEL_NAME],
            [TABULAR_MODEL_NAME, EMBEDDINGS_MODEL_NAME],
            [],
        ),
        ([TABULAR_MODEL_NAME], [], [TABULAR_MODEL_NAME]),
        ([], [TABULAR_MODEL_NAME], []),
    ],
    ids=["one_family_skipped", "every_family_scored", "nothing_scored", "first_write"],
)
def test_a_rewrite_that_drops_a_family_names_the_rows_it_would_delete(existing, scored, expected):
    # One object holds every family, so a re-run in a state where a family is not loadable would
    # replace the object without that family's rows, and the dt=D+horizon grade reads them off a
    # state snapshot that has aged out. The empty-write guard does not see this: two families out
    # of three is not an empty frame.
    assert (
        families_lost_by_rewrite(pd.DataFrame({"model_name": existing}), pd.DataFrame({"model_name": scored}))
        == expected
    )


def test_a_rewrite_reads_a_pre_family_scores_object_as_the_tabular_family():
    # A partition written before `model_name` existed holds tabular rows. Reading it as a family of
    # its own would refuse every re-run of those days, which is the opposite of the guard's point.
    existing = pd.DataFrame({"report_id": ["a"], "score": [0.5]})

    assert families_lost_by_rewrite(existing, pd.DataFrame({"model_name": [TABULAR_MODEL_NAME]})) == []


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
        (
            ModelFamily(name=EMBEDDINGS_MODEL_NAME, feature_set=REPORT_EMBEDDINGS_FEATURE_SET),
            ModelFamily(name=TABULAR_MODEL_NAME, feature_set=TABULAR_FEATURE_SET),
        ),
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
    scores = _scores(["a"], model_version=["2026-08-25"], score=[0.8], label_at_scoring=[True])
    graded = graded_rows(scores, _labels(["a"], open_count=[1]), HEADS_BY_NAME["open"], pool=POOL_NAME)
    grades = head_grades(graded, HEADS_BY_NAME["open"], pool=POOL_NAME, scoring_partition="2026-08-22")
    events = [
        *candidate_events(metadata),
        *examples_events(
            partition_key="2026-08-25",
            run_id="run-1",
            feature_set=TABULAR_FEATURE_SET.name,
            snapshots=20,
            backfilled_rows=0,
            per_head={"open": HeadExampleCounts(rows=10, positives=2, birth_day_positives=1)},
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
        *unseen_calibration_events(run_id="run-1", rows=calibration_rows(grades)),
        *holdout_calibration_events(
            partition_key="2026-08-25",
            run_id="run-1",
            model_name=TABULAR_MODEL_NAME,
            rows=[
                {
                    "head": "open",
                    "calibration_buckets": BUCKETS,
                    "bucket": 10,
                    "rows": 4,
                    "positives": 2,
                    "mean_score": 0.6,
                    "realized_rate": 0.5,
                }
            ],
        ),
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
        "inbox_ranking_unseen_calibration",
        "inbox_ranking_holdout_calibration",
        "inbox_ranking_unseen_report_graded",
    ):
        assert all(call["properties"]["model_name"] == TABULAR_MODEL_NAME for call in by_event[event_name])
    candidates = by_event["inbox_ranking_candidate_trained"]
    assert [c["properties"]["head"] for c in candidates] == ["open", "action", "dismiss_wrong"]
    assert candidates[0]["properties"]["holdout_auc"] == 0.67
    assert candidates[0]["properties"]["lookback_days"] == 60
    assert candidates[0]["properties"]["trained"] is True
    # The unseen events carry both roles, so this side needs the role to survive the same filter.
    assert all(c["properties"]["model_role"] == CANDIDATE_ROLE for c in candidates)
    assert "file" not in candidates[0]["properties"]
    # A head with nothing to fit still reports, so the readability alert sees a bad day, not a gap.
    assert {"trained": False, "readable": False}.items() <= candidates[2]["properties"].items()
    examples_props = by_event["inbox_ranking_examples_built"][0]["properties"]
    # Examples are per feature set, not per family: this is the dimension the counts break down on.
    assert {
        "head": "open",
        "rows": 10,
        "positives": 2,
        "birth_day_positives": 1,
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
        "birth_day_positives": 1,
        "readable": True,
        "auc": None,
        "mean_score": 0.8,
    }.items() <= head_graded_props.items()
    assert head_graded_props["expected_calibration_error"] == pytest.approx(0.2)
    calibration_props = by_event["inbox_ranking_unseen_calibration"][0]["properties"]
    assert {
        "head": "open",
        "scoring_partition": "2026-08-22",
        "pool": POOL_NAME,
        "bucket": 1,
        "rows": 1,
        "positives": 1,
        "mean_score": 0.8,
        "realized_rate": 1.0,
    }.items() <= calibration_props.items()
    assert set(by_event["inbox_ranking_holdout_calibration"][0]["properties"]) >= set(calibration_props) - {
        "horizon_days",
        "scoring_partition",
        "pool",
        # The holdout side reports readability on its own per-head event, not on every bucket.
        "readable",
    }
    assert by_event["inbox_ranking_holdout_calibration"][0]["properties"]["model_role"] == CANDIDATE_ROLE
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
    assert (
        model_object_key("inbox_ranking", EMBEDDINGS_MODEL_NAME, "2026-08-19", "open.ubj")
        == "inbox_ranking/inbox_ranking_models/v1/report_embeddings/dt=2026-08-19/open.ubj"
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

    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        return rows[["age_hours"]].astype(float)


class _CountingFeatureSet(FeatureSet):
    """`inner`, counting how many matrices are built from it."""

    def __init__(self, inner: FeatureSet) -> None:
        self.inner = inner
        self.name = inner.name
        self.schema_version = inner.schema_version
        self.feature_names = inner.feature_names
        self.state_columns = inner.state_columns
        self.extras_keys = inner.extras_keys
        self.builds = 0

    def build_matrix(
        self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS, *, as_of: datetime.datetime | None = None
    ) -> pd.DataFrame:
        self.builds += 1
        return self.inner.build_matrix(rows, extras, as_of=as_of)


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


def test_an_unreadable_trained_head_is_still_scored_and_graded():
    # A rare head never clears min_holdout_positives on one day's holdout, so gating the scoring on
    # readability means the pooled newborn grade, the only read that can ever give it a number,
    # never starts. The grade carries the flag instead, so the two populations stay apart.
    metadata = {
        "heads": [
            {"head": "open", "file": "open.ubj", "readable": True},
            {"head": "thumbs_up", "file": "thumbs_up.ubj", "readable": False},
        ]
    }
    assert trained_head_files(metadata) == {"open": "open.ubj", "thumbs_up": "thumbs_up.ubj"}
    assert readable_head_names(metadata) == frozenset({"open"})

    booster = _booster_ubj(tuple(TABULAR_FEATURE_SET.feature_names))
    model = UnseenModel(
        model_name=TABULAR_MODEL_NAME,
        model_version="2026-08-10",
        model_role=CANDIDATE_ROLE,
        feature_set=TABULAR_FEATURE_SET,
        boosters={"open": booster, "thumbs_up": booster},
        readable_heads=readable_head_names(metadata),
    )
    scores = score_pool(_state(["a", "b"]), _labels(["a", "b"]), [model], snapshot_date=D0)
    assert scores.groupby("head")["head_readable"].all().to_dict() == {"open": True, "thumbs_up": False}

    head = HEADS_BY_NAME["thumbs_up"]
    labels = _labels(["a", "b"], open_count=[1, 1], feedback_positive_count=[1, 0])
    graded = graded_rows(scores[scores["head"] == head.name], labels, head, pool=POOL_NAME)
    (grade,) = head_grades(graded, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert (grade.rows, grade.positives, grade.readable) == (2, 1, False)


def test_a_scores_object_written_before_the_readable_column_grades_as_readable():
    # The grader reads objects up to 14 days old, and those runs scored a head only when it was
    # readable, so a missing column must not turn a readable series unreadable overnight.
    head = HEADS_BY_NAME["open"]
    # _scores builds the pre-column row shape, so the frame reaching the grader carries no flag.
    graded = graded_rows(_scores(["a", "b"]), _labels(["a", "b"], open_count=[1, 0]), head, pool=POOL_NAME)
    assert graded["head_readable"].all()
    (grade,) = head_grades(graded, head, pool=POOL_NAME, scoring_partition="2026-08-10")
    assert grade.readable


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
        (
            _model_metadata(
                feature_set=REPORT_EMBEDDINGS_FEATURE_SET.name,
                feature_schema_version=REPORT_EMBEDDINGS_FEATURE_SET.schema_version,
                feature_names=list(REPORT_EMBEDDINGS_FEATURE_SET.feature_names),
            ),
            None,
        ),
        # A set a later build introduced, or one that has been withdrawn.
        (_model_metadata(feature_set="mmoe_trunk"), "this build can produce"),
        (_model_metadata(feature_schema_version=99), "feature_schema_version 99"),
        (_model_metadata(feature_names=["age_hours"]), "feature_names differ"),
    ],
)
def test_model_mismatch_checks_a_model_against_its_own_feature_set(metadata, expected):
    # A family on a richer set must not be rejected for disagreeing with the tabular contract, and
    # a set this build cannot produce must not be scored on whatever matrix happens to be at hand.
    mismatch = model_mismatch(metadata)
    assert expected is None and mismatch is None or (mismatch is not None and expected in mismatch)


@pytest.mark.parametrize("family", MODEL_FAMILIES, ids=[family.name for family in MODEL_FAMILIES])
def test_candidate_metadata_declares_the_set_it_was_fit_on(family):
    # The trainer's own record must pass the grader's check, or the day's candidate goes unscored.
    # Every registered family, because the trainer fits each on the set its registry entry names.
    metadata = candidate_metadata(
        "2026-08-19",
        [],
        model_name=family.name,
        feature_set=family.feature_set,
        skipped=[],
        trained_at=NOW,
        run_id="run-1",
    )
    assert metadata["model_name"] == family.name
    assert metadata["feature_set"] == family.feature_set.name
    assert metadata["feature_schema_version"] == family.feature_set.schema_version
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
    assert (
        examples_object_key("inbox_ranking", REPORT_EMBEDDINGS_FEATURE_SET.name, "2026-08-19")
        == "inbox_ranking/inbox_ranking_training_examples/v1/report_embeddings/dt=2026-08-19/part-00000.parquet"
    )
    assert (
        examples_object_key("inbox_ranking", TITLE_EMBEDDINGS_FEATURE_SET.name, "2026-08-19")
        == "inbox_ranking/inbox_ranking_training_examples/v1/title_embeddings/dt=2026-08-19/part-00000.parquet"
    )
    # And one models prefix per family, so a title booster never lands on the combined family's.
    assert (
        model_object_key("inbox_ranking", TITLE_EMBEDDINGS_MODEL_NAME, "2026-08-19", "open.ubj")
        == "inbox_ranking/inbox_ranking_models/v1/title_embeddings/dt=2026-08-19/open.ubj"
    )


@pytest.mark.parametrize("feature_set", [TABULAR_FEATURE_SET, *EMBEDDING_FEATURE_SETS])
def test_every_registered_set_is_reachable_by_the_name_a_model_records(feature_set):
    # A model names its set in `metadata.json`, and a name this build cannot resolve is left
    # unscored, so registering the set is what makes the family's boosters loadable at all.
    assert feature_set_by_name(feature_set.name) is feature_set


def test_the_two_embedding_families_share_one_recipe():
    # The pair measures the text choice, so everything except the input must match. A budget, grain
    # or width that drifted on one side would make the paired AUC difference read as content.
    report, title = REPORT_EMBEDDINGS_FEATURE_SET, TITLE_EMBEDDINGS_FEATURE_SET
    assert report.extras_keys != title.extras_keys
    for attribute in ("schema_version", "feature_names", "state_columns", "example_grain", "max_examples_per_head"):
        assert getattr(report, attribute) == getattr(title, attribute)
    families = {family.name: family.feature_set for family in MODEL_FAMILIES}
    assert families[TITLE_EMBEDDINGS_MODEL_NAME] is title
    assert families[EMBEDDINGS_MODEL_NAME] is report


# Before every snapshot the tests build, so a vector counts as present unless a test says otherwise.
LANDED_EARLY = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
# The end of D0, the moment a D0 example or a D0 score is built as of.
SNAPSHOT_END = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)


def _vector_frame(vectors: dict[str, object], landed: datetime.datetime = LANDED_EARLY) -> pd.DataFrame:
    """One rendering's snapshot rows, shaped like a dt=D embeddings partition."""
    return pd.DataFrame(
        {EMBEDDING_COLUMN: list(vectors.values()), EMBEDDING_INSERTED_AT_COLUMN: [landed] * len(vectors)},
        index=pd.Index(list(vectors), name="report_id"),
    )


def _report_vectors(
    vectors: dict[str, object],
    landed: datetime.datetime = LANDED_EARLY,
    *,
    feature_set: FeatureSet = REPORT_EMBEDDINGS_FEATURE_SET,
) -> Extras:
    """The side input one embedding set reads, under that set's own extras key."""
    return {feature_set.extras_keys[0]: _vector_frame(vectors, landed)}


def _embedding(*, first: float = 0.0) -> list[float]:
    return [first, *([0.5] * (EMBEDDING_DIMENSIONS - 1))]


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
def test_report_embeddings_matrix_puts_the_vector_in_position_order(feature_set):
    # `emb_i` must be the vector's ith component: the booster is saved with these names, so a
    # transposed or reordered matrix would score a report against another dimension's splits.
    rows = _state(["a", "b"])
    ascending = [float(index) for index in range(EMBEDDING_DIMENSIONS)]
    extras = _report_vectors({"a": ascending, "b": list(reversed(ascending))}, feature_set=feature_set)

    matrix = feature_set.build_matrix(rows, extras)

    assert list(matrix.columns) == list(feature_set.feature_names)
    last = f"emb_{EMBEDDING_DIMENSIONS - 1}"
    assert matrix.loc["a", ["emb_0", last]].tolist() == [0.0, float(EMBEDDING_DIMENSIONS - 1)]
    assert matrix.loc["b", ["emb_0", last]].tolist() == [float(EMBEDDING_DIMENSIONS - 1), 0.0]


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
@pytest.mark.parametrize(
    "vectors",
    [
        pytest.param({"a": None}, id="tombstoned"),  # the report keeps its row with a null vector
        pytest.param({"a": [0.5] * 8}, id="another_models_width"),
        pytest.param({"other": _embedding()}, id="no_row_for_this_report"),
        pytest.param(None, id="snapshot_missing"),  # the day's snapshot for this rendering is gone
    ],
)
def test_a_report_without_this_models_vector_is_not_an_embeddings_example(feature_set, vectors):
    # An all-missing row would teach the booster nothing but the base rate, and the source table's
    # TTL runs from report creation, so a long-lived report does lose its vector while still live.
    rows = _state(["a"])
    extras = NO_EXTRAS if vectors is None else _report_vectors(vectors, feature_set=feature_set)

    assert feature_set.buildable(rows, extras).tolist() == [False]
    assert feature_set.build_matrix(rows, extras).isna().to_numpy().all()


def _snapshot_objects(**frames: pd.DataFrame | None) -> dict[str, bytes]:
    """The dt=D embeddings partitions to serve, by extras key. A key mapped to None has no object."""
    return {
        partition_object_key("inbox_ranking", _EXTRA_SNAPSHOT_TABLES[key], "2026-08-10"): _parquet(frame)
        for key, frame in frames.items()
        if frame is not None
    }


def _extras_for(objects: dict[str, bytes], keys=_EMBEDDING_EXTRA_KEYS, **kwargs) -> Extras:
    return embeddings_extras(
        dagster.build_asset_context(), _ParquetS3(objects), "bucket", "inbox_ranking", "2026-08-10", keys, **kwargs
    )


def test_a_missing_rendering_is_left_out_while_an_empty_one_keeps_its_key():
    # The two cases must not be folded together. A missing snapshot has to leave the family's
    # partition as it stands, because rebuilding from nothing writes an empty candidate over
    # boosters a champion pointer can name. A snapshot that exists and holds no usable vector is a
    # day the family genuinely has nothing to fit, and takes the ordinary thin-input path.
    empty = _vector_frame({}).astype({EMBEDDING_COLUMN: object})

    missing_title = _extras_for(
        _snapshot_objects(report_embeddings=_vector_frame({"a": _embedding()}), title_embeddings=None)
    )
    assert set(missing_title) == {REPORT_EMBEDDINGS_EXTRA}
    assert TITLE_EMBEDDINGS_FEATURE_SET.missing_extras(missing_title) == (TITLE_EMBEDDINGS_EXTRA,)
    assert REPORT_EMBEDDINGS_FEATURE_SET.missing_extras(missing_title) == ()

    empty_title = _extras_for(
        _snapshot_objects(report_embeddings=_vector_frame({"a": _embedding()}), title_embeddings=empty)
    )
    assert TITLE_EMBEDDINGS_FEATURE_SET.missing_extras(empty_title) == ()
    assert TITLE_EMBEDDINGS_FEATURE_SET.buildable(_state(["a"]), empty_title).tolist() == [False]


def test_a_rendering_is_read_only_when_a_set_asks_for_it():
    # The examples asset reads one set's inputs at a time, so a family it is not building must not
    # pull a fleet-wide vector table across the network.
    objects = _snapshot_objects(
        report_embeddings=_vector_frame({"a": _embedding()}), title_embeddings=_vector_frame({"a": _embedding()})
    )
    assert set(_extras_for(objects, TITLE_EMBEDDINGS_FEATURE_SET.extras_keys)) == {TITLE_EMBEDDINGS_EXTRA}
    assert _extras_for(objects, ()) == {}


def _retained_vector_bytes(vectors: pd.DataFrame) -> int:
    """The bytes the frame's vectors keep alive, counting each shared buffer once.

    `to_pandas` gives every row a view on the Arrow child buffer the whole column was decoded
    into, so a frame of one row can hold the whole snapshot. `.base` is that buffer.
    """
    buffers = {id(value.base): value.base.nbytes for value in vectors[EMBEDDING_COLUMN] if value.base is not None}
    return sum(buffers.values())


def test_a_snapshot_is_narrowed_to_the_rows_the_caller_scores():
    # A snapshot holds a vector per live report while the scored population is one day's newborns,
    # so the scorer passes the pool's index rather than holding a table per rendering at full size.
    # Narrowing the frame is not enough: filtered in pandas, the one kept row still holds every
    # decoded vector alive, and the two renderings then sit in the pod together at full size.
    vectors = {f"old_{index}": _embedding() for index in range(64)}
    objects = _snapshot_objects(title_embeddings=_vector_frame({"newborn": _embedding(), **vectors}))
    keys = TITLE_EMBEDDINGS_FEATURE_SET.extras_keys

    narrowed = _extras_for(objects, keys, report_ids=pd.Index(["newborn", "never_embedded"]))
    whole = _extras_for(objects, keys)

    assert narrowed[TITLE_EMBEDDINGS_EXTRA].index.tolist() == ["newborn"]
    assert whole[TITLE_EMBEDDINGS_EXTRA].index.tolist() == ["newborn", *vectors]
    assert _retained_vector_bytes(narrowed[TITLE_EMBEDDINGS_EXTRA]) * 8 < _retained_vector_bytes(
        whole[TITLE_EMBEDDINGS_EXTRA]
    )


def test_only_the_set_whose_snapshot_is_missing_is_skipped(monkeypatch):
    # One rendering's failed snapshot must cost one family's day. The others have to keep building,
    # or a title-side gap silently stops the combined family the title is measured against.
    module = "products.signals.dags.inbox_ranking.training.dag"
    written: list[str] = []
    monkeypatch.setattr(f"{module}.skip_unconfigured", lambda context: False)
    monkeypatch.setattr(f"{module}.s3_client", lambda: None)
    monkeypatch.setattr(f"{module}.load_snapshots", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        f"{module}.embeddings_extras",
        lambda context, client, bucket, prefix, partition_key, keys: {
            key: _vector_frame({}) for key in keys if key != TITLE_EMBEDDINGS_EXTRA
        },
    )

    def _record(context, client, bucket, prefix, partition_key, feature_set, *args) -> dict[str, Any]:
        written.append(feature_set.name)
        return {}

    monkeypatch.setattr(f"{module}._write_examples", _record)

    with dagster.build_asset_context(partition_key="2026-08-10") as context:
        inbox_ranking_training_examples(context)
        metadata = context.get_output_metadata("result")

    assert written == [TABULAR_FEATURE_SET.name, REPORT_EMBEDDINGS_FEATURE_SET.name]
    assert metadata[f"{TITLE_EMBEDDINGS_FEATURE_SET.name}_skipped"].value is True


@pytest.mark.parametrize(
    "asset",
    [inbox_ranking_training_examples, inbox_ranking_unseen_scores],
    ids=["examples", "unseen_scores"],
)
def test_both_renderings_snapshots_are_upstream_of_the_assets_that_read_them(asset):
    # An asset that reads a snapshot without declaring it can run before the day's snapshot lands
    # and record the family as having no input. One dependency per rendering, so the two renderings
    # are scheduled independently rather than as one edge that either family's failure breaks.
    deps = {key.path[-1] for key in asset.keys_by_input_name.values()}
    assert {EMBEDDINGS_TABLE, TITLE_EMBEDDINGS_TABLE} <= deps


def test_a_rendering_never_falls_back_to_the_other_renderings_vector():
    # The families exist to measure the title against the title plus summary, so a row that took
    # the other rendering's vector would compare the two models on partly the same text. The inputs
    # also diverge in practice: a summary-only edit re-embeds only the combined rendering, and
    # either snapshot can hold a report the other does not.
    rows = _state(["combined_only", "title_only"])
    extras = {
        **_report_vectors({"combined_only": _embedding()}, feature_set=REPORT_EMBEDDINGS_FEATURE_SET),
        **_report_vectors({"title_only": _embedding()}, feature_set=TITLE_EMBEDDINGS_FEATURE_SET),
    }

    assert REPORT_EMBEDDINGS_FEATURE_SET.buildable(rows, extras).tolist() == [True, False]
    assert TITLE_EMBEDDINGS_FEATURE_SET.buildable(rows, extras).tolist() == [False, True]


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
def test_report_grain_keeps_one_example_per_report_and_needs_a_vector(feature_set):
    # The scoring-moment grain emits a near-duplicate row per snapshot, which is what 1536 columns
    # cannot afford; the report grain keeps the first snapshot a report is usable on.
    head = HEADS_BY_NAME["open"]
    snapshots = _daily_snapshots(["a", "b"], head, [BIRTH, BIRTH])
    extras = _report_vectors({"a": _embedding()}, feature_set=feature_set)

    examples = build_examples(snapshots, head, _at_grain(feature_set, REPORT_GRAIN), extras)

    assert examples["report_id"].tolist() == ["a"]
    assert examples["snapshot_date"].tolist() == [D0]
    assert examples["emb_0"].tolist() == [0.0]
    # The same snapshots at the moment grain: both reports, both days.
    moments = build_examples(snapshots, head, _at_grain(TABULAR_FEATURE_SET, SCORING_MOMENT_GRAIN))
    assert moments["report_id"].tolist() == ["a", "b", "a", "b"]


def test_cap_examples_keeps_every_positive_and_a_seeded_sample_of_the_negatives():
    # The budget is what keeps a 1536-column head inside one partition's object and the job's
    # runtime. Positives are the scarce side, and a re-run of a partition must keep the same rows.
    moments = pd.DataFrame({"report_id": [f"r{index}" for index in range(23)], "label": [1] * 3 + [0] * 20})

    capped = cap_examples(moments, 10)

    assert (len(capped), capped["label"].sum()) == (10, 3)
    assert capped.equals(cap_examples(moments, 10))
    assert cap_examples(moments, None) is moments
    # A head with more positives than the budget is not the case the budget is for.
    assert cap_examples(moments, 2)["label"].tolist() == [1, 1, 1]


def test_score_pool_scores_every_newborn_even_without_a_vector():
    # Families are graded on paired rows, so a set whose side input is thin must still produce a row
    # per report; coverage is the metadata that makes a thin side input visible instead of silent.
    # Both renderings at once, because the paired read is the whole point of the second one, and
    # each reports its own coverage: one thin rendering must not read as the other's.
    models = [_unseen_model(family.name, family.feature_set) for family in MODEL_FAMILIES]
    pool = _state(["a", "b"])
    extras = {
        **_report_vectors({"a": _embedding()}, feature_set=REPORT_EMBEDDINGS_FEATURE_SET),
        **_report_vectors({"a": _embedding(), "b": _embedding()}, feature_set=TITLE_EMBEDDINGS_FEATURE_SET),
    }

    scores = score_pool(pool, _labels(["a", "b"]), models, snapshot_date=D0, extras=extras)

    assert set(scores["model_name"]) == {family.name for family in MODEL_FAMILIES}
    for model_name in scores["model_name"].unique():
        assert scores[scores["model_name"] == model_name]["report_id"].tolist() == ["a", "b"]
    assert scores["score"].notna().all()
    coverage = pool_feature_coverage(pool, models, extras, SNAPSHOT_END)
    assert coverage[f"{REPORT_EMBEDDINGS_FEATURE_SET.name}_pool_coverage"].value == 0.5
    assert coverage[f"{TITLE_EMBEDDINGS_FEATURE_SET.name}_pool_coverage"].value == 1.0


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
def test_a_vector_that_landed_after_the_moment_is_not_that_moments_feature(feature_set):
    # The snapshot holds the latest vector per report, and a report is re-embedded whenever its text
    # changes (the summary workflow and every re-research run rewrite it). Taking the latest vector
    # for an earlier moment would train the family on text that did not exist when the report was
    # scored, which is the one defect that would invalidate the comparison it exists for.
    rows = _state(["a"])
    extras = _report_vectors(
        {"a": _embedding()}, landed=SNAPSHOT_END + datetime.timedelta(days=1), feature_set=feature_set
    )

    assert feature_set.buildable(rows, extras, as_of=SNAPSHOT_END).tolist() == [False]
    assert feature_set.build_matrix(rows, extras, as_of=SNAPSHOT_END).isna().to_numpy().all()
    later = SNAPSHOT_END + datetime.timedelta(days=2)
    assert feature_set.buildable(rows, extras, as_of=later).tolist() == [True]


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
def test_report_grain_moves_the_example_to_the_first_moment_its_vector_existed_for(feature_set):
    # A report whose vector landed after its first snapshot must not be dropped outright: its
    # example belongs on the first snapshot where that vector was already the report's own.
    head = HEADS_BY_NAME["open"]
    snapshots = _daily_snapshots(["a"], head, [BIRTH])
    # Landed during D0 + 1, so D0 cannot have it and D0 + 1 can.
    extras = _report_vectors(
        {"a": _embedding()}, landed=SNAPSHOT_END + datetime.timedelta(hours=6), feature_set=feature_set
    )

    examples = build_examples(snapshots, head, _at_grain(feature_set, REPORT_GRAIN), extras)

    assert examples["snapshot_date"].tolist() == [D0 + datetime.timedelta(days=1)]
    # At the birth grain there is no later moment to move to, so the report is no example at all.
    assert build_examples(snapshots, head, feature_set, extras).empty


@pytest.mark.parametrize("feature_set", EMBEDDING_FEATURE_SETS, ids=EMBEDDING_SET_IDS)
def test_reading_a_moment_needs_the_vectors_landing_time(feature_set):
    # A side input without the landing time cannot answer "did this vector exist yet", and silently
    # treating it as current is the leak this check exists to stop.
    vectors = {feature_set.extras_keys[0]: pd.DataFrame({EMBEDDING_COLUMN: [_embedding()]}, index=["a"])}
    with pytest.raises(ValueError, match=EMBEDDING_INSERTED_AT_COLUMN):
        feature_set.buildable(_state(["a"]), vectors, as_of=SNAPSHOT_END)


@pytest.mark.parametrize(
    "feature_set,extras,expected",
    [
        (TABULAR_FEATURE_SET, NO_EXTRAS, ()),
        (REPORT_EMBEDDINGS_FEATURE_SET, _report_vectors({"a": _embedding()}), ()),
        (REPORT_EMBEDDINGS_FEATURE_SET, NO_EXTRAS, (REPORT_EMBEDDINGS_EXTRA,)),
        # Each rendering answers for its own input: the other one being present is not its input.
        (
            TITLE_EMBEDDINGS_FEATURE_SET,
            _report_vectors({"a": _embedding()}, feature_set=TITLE_EMBEDDINGS_FEATURE_SET),
            (),
        ),
        (TITLE_EMBEDDINGS_FEATURE_SET, NO_EXTRAS, (TITLE_EMBEDDINGS_EXTRA,)),
        (TITLE_EMBEDDINGS_FEATURE_SET, _report_vectors({"a": _embedding()}), (TITLE_EMBEDDINGS_EXTRA,)),
    ],
)
def test_a_set_declares_the_side_inputs_it_needs(feature_set, extras, expected):
    # The examples asset skips a set with a missing side input instead of rebuilding it from
    # nothing, and the scorer skips its models, so both need to ask the set what it reads.
    assert feature_set.missing_extras(extras) == expected


def test_a_family_without_examples_keeps_the_partition_it_already_has():
    # Rebuilding from a missing examples object would write an empty candidate and delete this
    # partition's boosters, which a champion pointer can name. _EmptyS3 has no put_object or
    # delete_objects, so any write here raises instead of passing silently.
    family = ModelFamily(name=EMBEDDINGS_MODEL_NAME, feature_set=REPORT_EMBEDDINGS_FEATURE_SET)

    metadata = _train_candidate(
        dagster.build_asset_context(), _EmptyS3(), "bucket", "inbox_ranking", "2026-08-19", family
    )

    assert metadata[f"{EMBEDDINGS_MODEL_NAME}_skipped"].value is True


def test_a_model_is_not_scored_without_the_side_input_its_set_reads():
    # Scoring every report off the booster's missing branch would put a line on the chart that says
    # nothing about the model, and the day's grade would read as the family's performance.
    tabular = _unseen_model(TABULAR_MODEL_NAME, TABULAR_FEATURE_SET)
    embeddings = _unseen_model(EMBEDDINGS_MODEL_NAME, REPORT_EMBEDDINGS_FEATURE_SET)

    kept = models_with_extras(dagster.build_asset_context(), [tabular, embeddings], NO_EXTRAS)

    assert [model.model_name for model in kept] == [TABULAR_MODEL_NAME]
