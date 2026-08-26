import math
import datetime

import pytest

import numpy as np
import pandas as pd
import dagster
import xgboost as xgb
from botocore.exceptions import ClientError

from posthog import settings

from products.signals.backend.ranking.features import FEATURE_NAMES, feature_frame, feature_vector
from products.signals.dags.inbox_ranking.dataset.dag import LABELS_TABLE, STATE_TABLE
from products.signals.dags.inbox_ranking.training.dag import (
    _delete_other_objects,
    champion_object_key,
    inbox_ranking_training_examples,
    load_snapshots,
    model_object_key,
    snapshot_dates,
)
from products.signals.dags.inbox_ranking.training.examples import (
    EXAMPLE_COLUMNS,
    STATE_LAG_LIMIT,
    Snapshot,
    assemble_snapshot,
    build_examples,
    holdout_mask,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, dismissed_as_wrong
from products.signals.dags.inbox_ranking.training.promotion import AUC_TOLERANCE, decide_promotion
from products.signals.dags.inbox_ranking.training.train import _head_readable, booster_holdout_auc, train_head

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
    examples = build_examples(snapshots, open_head)
    assert list(examples.columns) == list(EXAMPLE_COLUMNS)
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
    pr = build_examples(snapshots, head).set_index("report_id")["label"].to_dict()
    assert pr == {"a": 0, "b": 0, "c": 1, "gone": 1}
    # dismiss_wrong reads the status stream: a is dropped, b was never impressed, c is a positive.
    wrong = build_examples(snapshots, HEADS_BY_NAME["dismiss_wrong"]).set_index("report_id")["label"].to_dict()
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
    assert build_examples(snapshots, head)["report_id"].tolist() == ["a"]


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


def test_build_examples_skips_label_only_rows():
    head = HEADS_BY_NAME["pr_created"]
    later = D0 + datetime.timedelta(days=head.horizon_days)
    state = _state(["a", "eu"], signal_count=[3, None])
    snapshots = {
        D0: Snapshot(date=D0, state=state, labels=_labels(["a", "eu"])),
        later: Snapshot(date=later, state=state, labels=_labels(["a", "eu"], pr_created_count=[1, 1])),
    }
    assert build_examples(snapshots, head)["report_id"].tolist() == ["a"]


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

    trained = train_head(examples, head, holdout_days=7)
    assert trained is not None
    assert trained.metrics.readable
    assert trained.metrics.holdout_auc is not None and trained.metrics.holdout_auc > 0.9
    assert trained.metrics.null_auc is not None and abs(trained.metrics.null_auc - 0.5) < 0.15
    booster = xgb.Booster()
    booster.load_model(bytearray(trained.booster_ubj))
    assert booster.feature_names == list(FEATURE_NAMES)
    # The saved holdout fit graded on the same rows must reproduce the stored metric: this is the
    # path the champion gate uses to compare two models on one holdout.
    assert trained.holdout_booster_ubj is not None
    paired = booster_holdout_auc(trained.holdout_booster_ubj, examples, head, holdout_days=7)
    assert paired == pytest.approx(trained.metrics.holdout_auc, abs=1e-6)
    # A booster from another feature schema is not scorable on these examples: the gate must fall
    # back to the stored AUC instead of failing the champion asset every day.
    other_schema = xgb.XGBClassifier(n_estimators=2).fit(pd.DataFrame({"not_a_feature": [0, 1, 0, 1]}), [0, 1, 0, 1])
    other_ubj = bytes(other_schema.get_booster().save_raw("ubj"))
    assert booster_holdout_auc(other_ubj, examples, head, holdout_days=7) is None


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
    assert train_head(examples, head, holdout_days=7) is None


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
    folder = model_object_key("inbox_ranking", "2026-08-19", "")
    written = {folder + "open.ubj", folder + "open.holdout.ubj", folder + "metadata.json"}
    client = _FakeS3([*written, folder + "action.ubj", "inbox_ranking/inbox_ranking_models/v1/champion.json"])
    assert _delete_other_objects(client, "bucket", folder, written) == [folder + "action.ubj"]
    assert client.keys == written | {"inbox_ranking/inbox_ranking_models/v1/champion.json"}


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
    # The scoring sweep resolves the champion pointer and booster files by these keys.
    assert (
        model_object_key("inbox_ranking", "2026-08-19", "open.ubj")
        == "inbox_ranking/inbox_ranking_models/v1/dt=2026-08-19/open.ubj"
    )
    assert champion_object_key("inbox_ranking") == "inbox_ranking/inbox_ranking_models/v1/champion.json"
    assert snapshot_dates("2026-08-19", 2) == [
        datetime.date(2026, 8, 17),
        datetime.date(2026, 8, 18),
        datetime.date(2026, 8, 19),
    ]
