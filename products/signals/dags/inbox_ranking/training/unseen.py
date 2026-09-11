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

from products.signals.backend.ranking.features import NO_EXTRAS, Extras, FeatureSet, feature_set_by_name
from products.signals.dags.inbox_ranking.common import snapshot_bounds
from products.signals.dags.inbox_ranking.training.examples import point_in_time_mask, state_rows
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME, Head

# Stamped on every scored event, so a chart can tell this pool definition from a later one.
POOL_NAME = "newborn"
# The pool of a scores object written before the column existed: a seeded sample of the state rows
# the day's examples did not cover. The grader reads objects up to 14 days old, so a change of pool
# definition puts two populations in one AUC series unless the older one keeps its own name.
LEGACY_POOL_NAME = "sampled"

CANDIDATE_ROLE = "candidate"
CHAMPION_ROLE = "champion"

# The model family: which features and which learner, as against `model_version`, the partition day
# it was fit on. Both are in the identity, so two families trained on one day stay apart.
TABULAR_MODEL_NAME = "tabular_xgb"
# The families the unseen read scores and grades each day. A family with no metadata for the day is
# skipped, so an entry can be added here before its trainer writes its first candidate.
MODEL_FAMILIES: tuple[str, ...] = (TABULAR_MODEL_NAME,)

# A shuffle plus one AUC rather than a refit, so this sits far above the trainer's NULL_PERMUTATIONS.
NULL_PERMUTATIONS = 25
# Fixed, so re-grading the same rows reports the same band.
NULL_SEED = 0

# The scores Parquet is long (one row per report, model and head) so a head can be added without a
# schema change. Declared explicitly, so a day with no unseen report writes an empty object a
# reader can still open with the schema every other day has.
_SCORE_TYPES: dict[str, pa.DataType] = {
    "report_id": pa.string(),
    "team_id": pa.int64(),
    "report_created_at": pa.timestamp("us", tz="UTC"),
    "snapshot_date": pa.date32(),
    "pool": pa.string(),
    "model_name": pa.string(),
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
    """One model to score the pool with, the feature set it was fit on, and the readable heads it
    can score. Models that share a feature set share one matrix."""

    model_name: str
    model_version: str
    model_role: str
    feature_set: FeatureSet
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
    model_name: str
    model_version: str
    model_role: str
    rows: int
    positives: int
    base_rate: float | None
    auc: float | None
    # AUC of "newest first" on the same outcomes. A model that does not beat it has learned
    # nothing the inbox could not do by sorting on age.
    recency_auc: float | None
    # The chance line on the same rows (see ChanceBand): the band a per-day AUC has to clear.
    null_auc: float | None
    null_auc_std: float | None

    def metrics(self) -> dict[str, int | float | None]:
        return {
            "rows": self.rows,
            "positives": self.positives,
            "base_rate": self.base_rate,
            "auc": self.auc,
            "recency_auc": self.recency_auc,
            "null_auc": self.null_auc,
            "null_auc_std": self.null_auc_std,
            "null_permutations": NULL_PERMUTATIONS,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "head": self.head,
            "horizon_days": self.horizon_days,
            "scoring_partition": self.scoring_partition,
            "pool": self.pool,
            "model_name": self.model_name,
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


@frozen
class ChanceBand:
    """What a model with no signal scores on these outcomes.

    The mean is 0.5 by construction, so the value is the spread, which sizes the noise on a per-day
    unseen AUC. Both are None when the AUC is undefined, so the chance line has exactly the same
    gaps as `auc` and `recency_auc`.
    """

    auc: float | None
    auc_std: float | None


def chance_band(outcomes: np.ndarray, scores: np.ndarray) -> ChanceBand:
    """The AUC over NULL_PERMUTATIONS seeded permutations of `scores` against the same outcomes.

    Permuting the model's own scores rather than drawing fresh ones keeps the score distribution
    and its ties, so the band is the one this head's rows actually produce.

    Each draw is counted with its own reverse, which scores `1 - auc` because a tie pays 0.5 either
    way. The mean is therefore exactly 0.5 however few rows the head has. A plain sample mean lands
    near 0.5 on a large head but not on a small one, and two families on the same rows would then
    report different chance lines because their shuffles differed, which is a gap that means nothing.
    """
    rng = np.random.default_rng(NULL_SEED)
    aucs: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        auc = _auc(outcomes, rng.permutation(scores))
        if auc is not None:
            aucs.extend((auc, 1.0 - auc))
    if not aucs:
        return ChanceBand(auc=None, auc_std=None)
    return ChanceBand(auc=float(np.mean(aucs)), auc_std=float(np.std(aucs)))


def model_feature_set(metadata: Mapping[str, Any]) -> FeatureSet | None:
    """The feature set the model declares, or None when this build cannot produce it. Metadata
    written before the field existed declares nothing and reads as the tabular set."""
    return feature_set_by_name(metadata.get("feature_set"))


def model_mismatch(metadata: Mapping[str, Any]) -> str | None:
    """Why the model cannot be scored, or None when it can.

    A model is checked against its own declared set rather than one global contract, so a family
    on a richer set is not rejected for disagreeing with the tabular one.
    """
    feature_set = model_feature_set(metadata)
    if feature_set is None:
        return f"feature set {metadata.get('feature_set')} is not one this build can produce"
    version = metadata.get("feature_schema_version")
    if version != feature_set.schema_version:
        return f"feature_schema_version {version} is not {feature_set.name}'s {feature_set.schema_version}"
    if tuple(metadata.get("feature_names") or ()) != feature_set.feature_names:
        return f"feature_names differ from the {feature_set.name} feature set"
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


def empty_scores_write_allowed(existing_row_count: int | None) -> bool:
    """Whether a run that scored nothing may overwrite a partition's scores object.

    A partition whose candidate sits under the pre-family models layout loads no model and so
    scores nothing. Writing that empty result would destroy the rows the dt=D+horizon grade reads,
    and those rows cannot be rebuilt once the state snapshot they came from ages out. An unknown
    count (no object, or one written before the row-count stamp) is not a veto, which is the rule
    `partition_write_allowed` already applies to the emission log.
    """
    return not existing_row_count


def with_model_names(scores: pd.DataFrame) -> pd.DataFrame:
    """`scores` with a `model_name` column, filling the tabular family where it is absent.

    The grader reads scores objects up to 14 days old, so it still meets objects written before the
    column existed. Every one of those holds tabular XGBoost rows, and grading them under a null
    name would split the AUC series on the day the column arrived.
    """
    if "model_name" not in scores:
        return scores.assign(model_name=TABULAR_MODEL_NAME)
    return scores.assign(model_name=scores["model_name"].fillna(TABULAR_MODEL_NAME))


def score_pool(
    pool: pd.DataFrame,
    labels: pd.DataFrame,
    models: Sequence[UnseenModel],
    *,
    snapshot_date: datetime.date,
    extras: Extras = NO_EXTRAS,
) -> pd.DataFrame:
    """One row per (report, model, head) in SCORE_COLUMNS order, where a model is a
    (model_name, model_version, model_role).

    Features are built exactly as `build_examples` builds them, so a report scored here sees the
    same vector it would have seen as a training example. One matrix is built per feature set the
    models declare, and every model on that set scores against it. `label_at_scoring` records
    whether the head's outcome had already happened on the scoring day; the grader drops those
    rows, the same way the example builder drops a scoring moment whose label is already 1.
    """
    aligned_labels = labels.reindex(pool.index)
    team_id = pool["report_team_id"] if "report_team_id" in pool else pd.Series(None, index=pool.index, dtype=object)
    report_ids = pool.index.to_numpy()
    team_ids = pd.to_numeric(team_id, errors="coerce").astype("Int64").to_numpy()
    created_at = pd.to_datetime(pool["report_created_at"], utc=True).to_numpy()
    age_hours = pool["report_age_hours"].astype(float).to_numpy()
    matrices: dict[str, xgb.DMatrix] = {}
    frames: list[pd.DataFrame] = []
    for model in models:
        feature_set = model.feature_set
        if feature_set.name not in matrices:
            matrices[feature_set.name] = xgb.DMatrix(
                feature_set.build_matrix(state_rows(pool, feature_set), extras),
                feature_names=list(feature_set.feature_names),
            )
        matrix = matrices[feature_set.name]
        frames.extend(
            pd.DataFrame(
                {
                    "report_id": report_ids,
                    "team_id": team_ids,
                    "report_created_at": created_at,
                    "snapshot_date": snapshot_date,
                    "pool": POOL_NAME,
                    "model_name": model.model_name,
                    "model_version": model.model_version,
                    "model_role": model.model_role,
                    "feature_schema_version": feature_set.schema_version,
                    "head": head_name,
                    "score": _predict(booster_ubj, matrix),
                    "age_hours": age_hours,
                    "label_at_scoring": HEADS_BY_NAME[head_name].label(aligned_labels).to_numpy(),
                }
            )
            for head_name, booster_ubj in model.boosters.items()
        )
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
    rows: dict[tuple[str, str, str], dict[str, object]] = {}
    for record in scores.to_dict("records"):
        key = (str(record["report_id"]), str(record["model_name"]), str(record["model_role"]))
        if key not in rows:
            rows[key] = {
                "report_id": record["report_id"],
                "team_id": _int_or_none(record["team_id"]),
                "report_created_at": _isoformat_or_none(record["report_created_at"]),
                "model_name": record["model_name"],
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
    for (model_name, model_version, model_role), rows in kept.groupby(
        ["model_name", "model_version", "model_role"], sort=True
    ):
        outcomes = rows["outcome"].to_numpy(dtype=bool)
        scores = rows["score"].to_numpy(dtype=float)
        band = chance_band(outcomes, scores)
        grades.append(
            HeadGrade(
                head=head.name,
                horizon_days=head.horizon_days,
                scoring_partition=scoring_partition,
                pool=pool,
                model_name=str(model_name),
                model_version=str(model_version),
                model_role=str(model_role),
                rows=len(rows),
                positives=int(outcomes.sum()),
                base_rate=float(outcomes.mean()) if len(rows) else None,
                auc=_auc(outcomes, scores),
                recency_auc=_auc(outcomes, -rows["age_hours"].to_numpy(dtype=float)),
                null_auc=band.auc,
                null_auc_std=band.auc_std,
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
    rows: dict[tuple[str, str, str], dict[str, object]] = {}
    for head_name, graded in sorted(graded_by_head.items()):
        for record in graded.to_dict("records"):
            key = (str(record["report_id"]), str(record["model_name"]), str(record["model_role"]))
            entry = rows.setdefault(
                key,
                {
                    "report_id": record["report_id"],
                    "team_id": _int_or_none(record["team_id"]),
                    "scoring_partition": scoring_partition,
                    "pool": pool,
                    "model_name": record["model_name"],
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
