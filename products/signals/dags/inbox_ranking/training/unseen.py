"""Unseen-performance read for the ranking model.

The trainer grades a candidate on a holdout cut from the same example set and then refits the
shipped booster on train plus holdout, so `holdout_auc` grades the recipe rather than the model
that ships. This module is the offline batch proxy for the number that is missing: each day it
scores the reports born that day with the day's models, and grades those scores at each head's
horizon against a snapshot the model could not have seen.

The cohort, the label and the horizon come from the same `Head` definitions the trainer uses, so
the unseen AUC is directly comparable to the holdout AUC of the same head and model version. Pure
functions over frames; `training/dag.py` owns the S3 and telemetry plumbing.
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
from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.training.examples import STATE_COLUMNS, point_in_time_mask
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head

# Stamped on every scored event, so a chart can tell this pool definition from a later one.
POOL_NAME = "newborn"
# The pool of a scores object written before the column existed: a seeded sample of the state rows
# the day's examples did not cover. The grader reads objects up to 14 days old, so a change of pool
# definition puts two populations in one AUC series unless the older one keeps its own name.
LEGACY_POOL_NAME = "sampled"

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
    "pool": pa.string(),
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
    """One model to score the pool with, and the readable heads it can score."""

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
    # The pool definition the scored rows came from, carried so the AUC series can be read per pool
    # rather than split by hand on the day a definition changed.
    pool: str
    model_version: str
    model_role: str
    rows: int
    positives: int
    base_rate: float | None
    auc: float | None
    # AUC of "newest first" on the same outcomes. A model that does not beat it has learned
    # nothing the inbox could not do by sorting on age.
    recency_auc: float | None

    def metrics(self) -> dict[str, int | float | None]:
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
            "pool": self.pool,
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


def unseen_pool(state: pd.DataFrame, snapshot_date: datetime.date) -> pd.DataFrame:
    """The dt=D state rows of the reports created on D.

    A newborn has no scoring moment before D, and the dt=D examples reach no later than D minus the
    head's horizon, so no training example can cover it. Leakage-freedom is therefore structural
    rather than a set difference over whatever the example builder did that day, and the read stays
    on the fresh reports the inbox actually ranks. The two extra filters mirror `build_examples`: a
    backfilled state row carries current Postgres state rather than the state as of the day, and a
    row without `signal_count` has no features to score.
    """
    start, end = snapshot_bounds(snapshot_date.isoformat())
    created = pd.to_datetime(state["report_created_at"], utc=True)
    # Newborns first: the remaining filters then run over the slice, not every live report.
    newborn = state.loc[((created >= start) & (created < end)).to_numpy()]
    keep = newborn["signal_count"].notna().to_numpy()
    keep &= point_in_time_mask(newborn, snapshot_date).to_numpy()
    return newborn.loc[keep]


def leaked_report_ids(pool: pd.DataFrame, example_report_ids: Collection[object]) -> list[str]:
    """Pool reports a training example already covers.

    Empty while every head horizon stays above zero. A non-empty result means the example builder
    now reaches the partition day, so the read would grade a model on its own training data; the
    caller fails the asset instead of publishing that number.
    """
    covered = set(example_report_ids)
    return sorted(str(report_id) for report_id in pool.index if report_id in covered)


def scored_pool(scores: pd.DataFrame) -> str:
    """The pool definition a scores object was written under.

    One partition is written by one run, so the column holds a single value. An object written
    before the column existed is a sample of the old pool, and must not be graded as the current
    one.
    """
    if "pool" not in scores:
        return LEGACY_POOL_NAME
    values = scores["pool"].dropna().unique()
    return str(values[0]) if len(values) else LEGACY_POOL_NAME


def score_pool(
    pool: pd.DataFrame, labels: pd.DataFrame, models: Sequence[UnseenModel], *, snapshot_date: datetime.date
) -> pd.DataFrame:
    """One row per (report, model, head) in SCORE_COLUMNS order.

    Features are built exactly as `build_examples` builds them, so a report scored here sees the
    same vector it would have seen as a training example. `label_at_scoring` records whether the
    head's outcome had already happened on the scoring day; the grader drops those rows, the same
    way the example builder drops a scoring moment whose label is already 1.
    """
    rows = pool[list(STATE_COLUMNS)].copy()
    rows["age_hours"] = rows.pop("report_age_hours").astype(float)
    matrix = xgb.DMatrix(feature_frame(rows), feature_names=list(FEATURE_NAMES))
    aligned_labels = labels.reindex(pool.index)
    team_id = pool["report_team_id"] if "report_team_id" in pool else pd.Series(None, index=pool.index, dtype=object)
    report_ids = pool.index.to_numpy()
    team_ids = pd.to_numeric(team_id, errors="coerce").astype("Int64").to_numpy()
    created_at = pd.to_datetime(rows["report_created_at"], utc=True).to_numpy()
    age_hours = rows["age_hours"].to_numpy()
    frames = [
        pd.DataFrame(
            {
                "report_id": report_ids,
                "team_id": team_ids,
                "report_created_at": created_at,
                "snapshot_date": snapshot_date,
                "pool": POOL_NAME,
                "model_version": model.model_version,
                "model_role": model.model_role,
                "feature_schema_version": model.feature_schema_version,
                "head": head_name,
                "score": _predict(booster_ubj, matrix),
                "age_hours": age_hours,
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


def score_event_rows(scores: pd.DataFrame, pool: pd.DataFrame) -> list[dict[str, object]]:
    """One dict per (report, model): every head's score as `p_<head>`, plus the raw feature inputs.

    The Parquet is long so that a head can be added without a schema change; an event is wide so a
    trends insight can aggregate a head's scores without a join.
    """
    columns = [column for column in FEATURE_INPUT_COLUMNS if column in pool]
    inputs = {
        report_id: {column: _plain(value) for column, value in row.items()}
        for report_id, row in pool[columns].to_dict("index").items()
    }
    rows: dict[tuple[str, str], dict[str, object]] = {}
    for record in scores.to_dict("records"):
        key = (str(record["report_id"]), str(record["model_role"]))
        if key not in rows:
            rows[key] = {
                "report_id": record["report_id"],
                "team_id": _int_or_none(record["team_id"]),
                "report_created_at": _isoformat_or_none(record["report_created_at"]),
                "model_version": record["model_version"],
                "model_role": record["model_role"],
                "feature_schema_version": record["feature_schema_version"],
                "pool": POOL_NAME,
                "unseen_pool": len(pool),
                "age_hours": float(record["age_hours"]),
                **inputs.get(record["report_id"], {}),
            }
        rows[key][f"p_{record['head']}"] = float(record["score"])
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


def head_grades(graded: pd.DataFrame, head: Head, *, pool: str, scoring_partition: str) -> list[HeadGrade]:
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
                pool=pool,
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
    graded_by_head: Mapping[str, pd.DataFrame], *, pool: str, horizon_days: int, scoring_partition: str
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
                    "pool": pool,
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
