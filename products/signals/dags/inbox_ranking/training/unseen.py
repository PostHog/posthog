"""Unseen-performance read for the ranking model.

The trainer grades a candidate on a holdout cut from the same example set and then refits the
shipped booster on train plus holdout, so `holdout_auc` grades the recipe rather than the model
that ships. This module is the offline batch proxy for the number that is missing: each day it
samples reports that appear in no training example, scores them with the day's models, and grades
those scores at each head's horizon against a snapshot the model could not have seen.

The pool, the cohort, the label and the horizon come from the same `Head` definitions the trainer
uses, so the unseen AUC is directly comparable to the holdout AUC of the same head and model
version. Pure functions over frames; `training/dag.py` owns the S3 and telemetry plumbing.
"""

import datetime
from collections.abc import Collection, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import xgboost as xgb
from sklearn.metrics import roc_auc_score

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, feature_frame
from products.signals.dags.inbox_ranking.training.examples import STATE_COLUMNS, point_in_time_mask
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head

# How many unseen reports one day's read scores. Large enough that a head with a low base rate
# still collects positives over a few days, small enough that the event volume stays under the
# label streams this project already carries.
UNSEEN_SAMPLE_SIZE = 1000

CANDIDATE_ROLE = "candidate"
CHAMPION_ROLE = "champion"

# The scores Parquet is long (one row per report, model and head) so a head can be added without a
# schema change. Declared explicitly, so a day with no unseen report writes an empty object a
# reader can still open with the schema every other day has.
_SCORE_TYPES: dict[str, pa.DataType] = {
    "report_id": pa.string(),
    "team_id": pa.int64(),
    "report_created_at": pa.timestamp("us", tz="UTC"),
    "snapshot_date": pa.date32(),
    "model_version": pa.string(),
    "model_role": pa.string(),
    "feature_schema_version": pa.int64(),
    "head": pa.string(),
    "score": pa.float64(),
    "age_hours": pa.float64(),
    "label_at_scoring": pa.bool_(),
}
SCORES_SCHEMA = pa.schema(_SCORE_TYPES)
SCORE_COLUMNS = tuple(_SCORE_TYPES)

# Report-state columns copied onto a scored event next to the scores, so a calibration read can
# group on the raw inputs without joining the Parquet.
FEATURE_INPUT_COLUMNS = (
    "signal_count",
    "total_weight",
    "run_count",
    "title_chars",
    "summary_chars",
    "priority",
    "actionability",
)


@frozen
class UnseenModel:
    """One model to score the sample with, and the readable heads it can score."""

    model_version: str
    model_role: str
    feature_schema_version: int
    boosters: Mapping[str, bytes]


@frozen
class HeadGrade:
    head: str
    horizon_days: int
    # The partition the scores were written on, which is `horizon_days` before the grading day.
    scoring_partition: str
    model_version: str
    model_role: str
    rows: int
    positives: int
    base_rate: float | None
    auc: float | None
    # AUC of "newest first" on the same outcomes. A model that does not beat it has learned
    # nothing the inbox could not do by sorting on age.
    recency_auc: float | None

    def metrics(self) -> dict[str, float | None]:
        return {
            "rows": self.rows,
            "positives": self.positives,
            "base_rate": self.base_rate,
            "auc": self.auc,
            "recency_auc": self.recency_auc,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "head": self.head,
            "horizon_days": self.horizon_days,
            "scoring_partition": self.scoring_partition,
            "model_version": self.model_version,
            "model_role": self.model_role,
            **self.metrics(),
        }


def _auc(outcomes: np.ndarray, scores: np.ndarray) -> float | None:
    """AUC, or None when it is undefined: a single outcome class, or a ranking column that carries
    a non-finite value (a missing `age_hours` makes the recency baseline unrankable)."""
    if len(outcomes) == 0 or outcomes.sum() == 0 or outcomes.sum() == len(outcomes):
        return None
    if not np.isfinite(scores).all():
        return None
    return float(roc_auc_score(outcomes, scores))


def model_mismatch(metadata: Mapping[str, Any]) -> str | None:
    """Why the model cannot be scored against the current feature contract, or None when it can."""
    version = metadata.get("feature_schema_version")
    if version != FEATURE_SCHEMA_VERSION:
        return f"feature_schema_version {version} is not the serving contract's {FEATURE_SCHEMA_VERSION}"
    if tuple(metadata.get("feature_names") or ()) != FEATURE_NAMES:
        return "feature_names differ from the serving contract"
    return None


def readable_head_files(metadata: Mapping[str, Any]) -> dict[str, str]:
    """The `<head>.ubj` object name per readable head. Only a readable head is worth an unseen
    read; an unreadable one has no holdout AUC to compare the unseen AUC against."""
    return {
        entry["head"]: entry["file"]
        for entry in metadata.get("heads", [])
        if entry.get("readable") and entry.get("file") and entry.get("head") in HEADS_BY_NAME
    }


def unseen_pool(
    state: pd.DataFrame, snapshot_date: datetime.date, example_report_ids: Collection[object]
) -> pd.DataFrame:
    """The dt=D state rows no training example covers.

    A set difference against the example ids rather than a date rule, so the pool stays correct if
    the example builder changes. The two extra filters mirror `build_examples`: a backfilled state
    row carries current Postgres state rather than the state as of the day, and a row without
    `signal_count` has no features to score.
    """
    keep = ~state.index.isin(set(example_report_ids))
    keep &= state["signal_count"].notna().to_numpy()
    keep &= point_in_time_mask(state, snapshot_date).to_numpy()
    return state.loc[keep]


def sample_unseen(pool: pd.DataFrame, partition_key: str, *, size: int = UNSEEN_SAMPLE_SIZE) -> pd.DataFrame:
    """A uniform sample of the pool without replacement, seeded from the partition day so a re-run
    of the partition reproduces it. A pool at or below `size` is scored in full."""
    if len(pool) <= size:
        return pool
    rng = np.random.default_rng(int(partition_key.replace("-", "")))
    return pool.iloc[np.sort(rng.choice(len(pool), size=size, replace=False))]


def score_sample(
    sample: pd.DataFrame, labels: pd.DataFrame, models: Sequence[UnseenModel], *, snapshot_date: datetime.date
) -> pd.DataFrame:
    """One row per (report, model, head) in SCORE_COLUMNS order.

    Features are built exactly as `build_examples` builds them, so a report scored here sees the
    same vector it would have seen as a training example. `label_at_scoring` records whether the
    head's outcome had already happened on the scoring day; the grader drops those rows, the same
    way the example builder drops a scoring moment whose label is already 1.
    """
    rows = sample[list(STATE_COLUMNS)].copy()
    rows["age_hours"] = rows.pop("report_age_hours").astype(float)
    matrix = xgb.DMatrix(feature_frame(rows), feature_names=list(FEATURE_NAMES))
    aligned_labels = labels.reindex(sample.index)
    team_id = (
        sample["report_team_id"] if "report_team_id" in sample else pd.Series(None, index=sample.index, dtype=object)
    )
    frames = [
        pd.DataFrame(
            {
                "report_id": sample.index.to_numpy(),
                "team_id": pd.to_numeric(team_id, errors="coerce").astype("Int64").to_numpy(),
                "report_created_at": pd.to_datetime(rows["report_created_at"], utc=True).to_numpy(),
                "snapshot_date": snapshot_date,
                "model_version": model.model_version,
                "model_role": model.model_role,
                "feature_schema_version": model.feature_schema_version,
                "head": head_name,
                "score": _predict(booster_ubj, matrix),
                "age_hours": rows["age_hours"].to_numpy(),
                "label_at_scoring": HEADS_BY_NAME[head_name].label(aligned_labels).to_numpy(),
            }
        )
        for model in models
        for head_name, booster_ubj in model.boosters.items()
    ]
    if not frames:
        return pd.DataFrame(columns=list(SCORE_COLUMNS))
    return pd.concat(frames, ignore_index=True)[list(SCORE_COLUMNS)]


def _predict(booster_ubj: bytes, matrix: xgb.DMatrix) -> np.ndarray:
    booster = xgb.Booster()
    booster.load_model(bytearray(booster_ubj))
    return booster.predict(matrix)


def scores_table(scores: pd.DataFrame) -> pa.Table:
    if scores.empty:
        return SCORES_SCHEMA.empty_table()
    return pa.Table.from_pandas(scores[list(SCORE_COLUMNS)], schema=SCORES_SCHEMA, preserve_index=False)


def score_event_rows(scores: pd.DataFrame, sample: pd.DataFrame, *, unseen_pool_size: int) -> list[dict[str, object]]:
    """One dict per (report, model): every head's score as `p_<head>`, plus the raw feature inputs.

    The Parquet is long so that a head can be added without a schema change; an event is wide so a
    trends insight can aggregate a head's scores without a join.
    """
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for record in scores.to_dict("records"):
        key = (str(record["report_id"]), str(record["model_role"]))
        entry = rows.setdefault(
            key,
            {
                "report_id": record["report_id"],
                "team_id": _int_or_none(record["team_id"]),
                "report_created_at": _isoformat_or_none(record["report_created_at"]),
                "model_version": record["model_version"],
                "model_role": record["model_role"],
                "feature_schema_version": record["feature_schema_version"],
                "unseen_pool": unseen_pool_size,
                "sample_size": len(sample),
                "age_hours": float(record["age_hours"]),
                **{
                    column: _plain(sample[column].get(record["report_id"]))
                    for column in FEATURE_INPUT_COLUMNS
                    if column in sample
                },
            },
        )
        entry[f"p_{record['head']}"] = float(record["score"])
    return list(rows.values())


def missing_label_columns(labels: pd.DataFrame, head: Head) -> list[str]:
    """The head's label columns the grading snapshot lacks. A missing cumulative count reads as
    zero, which would grade every scored report a negative, so the head is skipped instead."""
    return [column for column in head.label_columns if column not in labels]


def graded_rows(head_scores: pd.DataFrame, labels: pd.DataFrame, head: Head) -> pd.DataFrame:
    """`head_scores` with `in_cohort` and `outcome` read from the later snapshot's labels.

    A row is in cohort when the head's outcome had not already happened on the scoring day, the
    report still has a labels row, and the head's cohort holds at the grading day. The cohort is
    read at the later snapshot for the same reason `build_examples` reads it there: the impression
    that puts a report in the cohort usually lands after the report is scored. An out-of-cohort row
    keeps its score with `outcome` null, so a calibration read can filter on the flag.
    """
    ids = pd.Index(head_scores["report_id"])
    aligned = labels.reindex(ids)
    aligned.index = head_scores.index
    in_cohort = (
        ids.isin(labels.index)
        & ~head_scores["label_at_scoring"].fillna(False).to_numpy(dtype=bool)
        & head.cohort(aligned).to_numpy()
    )
    if head.status_labels and "label_provenance_ok" in aligned:
        in_cohort &= aligned["label_provenance_ok"].fillna(False).to_numpy(dtype=bool)
    graded = head_scores.copy()
    graded["in_cohort"] = in_cohort
    graded["outcome"] = pd.array(head.label(aligned).to_numpy(dtype=bool), dtype="boolean")
    graded.loc[~in_cohort, "outcome"] = pd.NA
    return graded


def head_grades(graded: pd.DataFrame, head: Head, *, scoring_partition: str) -> list[HeadGrade]:
    """The unseen read per model that scored this head, over the in-cohort rows."""
    grades: list[HeadGrade] = []
    kept = graded[graded["in_cohort"]]
    for (model_version, model_role), rows in kept.groupby(["model_version", "model_role"], sort=True):
        outcomes = rows["outcome"].to_numpy(dtype=bool)
        grades.append(
            HeadGrade(
                head=head.name,
                horizon_days=head.horizon_days,
                scoring_partition=scoring_partition,
                model_version=str(model_version),
                model_role=str(model_role),
                rows=len(rows),
                positives=int(outcomes.sum()),
                base_rate=float(outcomes.mean()) if len(rows) else None,
                auc=_auc(outcomes, rows["score"].to_numpy(dtype=float)),
                recency_auc=_auc(outcomes, -rows["age_hours"].to_numpy(dtype=float)),
            )
        )
    return grades


def report_grade_rows(
    graded_by_head: Mapping[str, pd.DataFrame], *, horizon_days: int, scoring_partition: str
) -> list[dict[str, object]]:
    """One dict per (report, model) carrying every head graded at this horizon.

    Heads are grouped by horizon because they were all scored on the same day, so one event holds a
    report's whole outcome at that horizon.
    """
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for head_name, graded in sorted(graded_by_head.items()):
        for record in graded.to_dict("records"):
            key = (str(record["report_id"]), str(record["model_role"]))
            entry = rows.setdefault(
                key,
                {
                    "report_id": record["report_id"],
                    "team_id": _int_or_none(record["team_id"]),
                    "scoring_partition": scoring_partition,
                    "model_version": record["model_version"],
                    "model_role": record["model_role"],
                    "horizon_days": horizon_days,
                },
            )
            entry[f"in_cohort_{head_name}"] = bool(record["in_cohort"])
            entry[f"p_{head_name}"] = float(record["score"])
            if record["in_cohort"]:
                entry[f"outcome_{head_name}"] = bool(record["outcome"])
    return list(rows.values())


def _plain(value: Any) -> Any:
    """A numpy or pandas scalar as the plain Python value the capture client can serialize."""
    if value is None or pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _int_or_none(value: Any) -> int | None:
    plain = _plain(value)
    return None if plain is None else int(plain)


def _isoformat_or_none(value: Any) -> str | None:
    plain = _plain(value)
    return None if plain is None else pd.Timestamp(plain).isoformat()
