"""Feature universes for the report-ranking model.

A `FeatureSet` is one universe: its name, its schema version, its ordered feature names, the
report-state columns it reads, and `build_matrix`, which turns a frame of those rows into the
matrix. A model records the set it was fit on in its `metadata.json`, so a run can hold several
sets at once: the examples Parquet, the training matrix and the scoring matrix are all built per
set, and a model whose declared set this build cannot produce is left unscored.

The tabular set is the first one. Training (`products/signals/dags/inbox_ranking/training/`) and
serving (the scoring sweep in this package) must build features through the same code, so the
booster's `feature_names` match the serving matrix by construction. The sweep reads the tabular
contract directly as FEATURE_NAMES / `feature_vector` / FEATURE_SCHEMA_VERSION.

The tabular set is: the report-state columns the dataset dag snapshots from Postgres plus the
report's age at the scoring moment. No report embedding and no impression-derived columns
(`source_products`), so the sweep needs nothing beyond the SignalReport row and its latest
judgment artefacts. The report-embeddings set is the second one, and the sweep does not serve it:
it is an offline candidate graded on the unseen read, and serving it needs the report vector at
scoring time (skill issue 14).
"""

import abc
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

FEATURE_SCHEMA_VERSION = 1

PRIORITY_VALUES = ("P0", "P1", "P2", "P3", "P4")
ACTIONABILITY_VALUES = ("immediately_actionable", "requires_human_input", "not_actionable")

NUMERIC_FEATURES = (
    "signal_count",
    "total_weight",
    "run_count",
    "title_chars",
    "summary_chars",
    "age_hours",
)

FEATURE_NAMES: tuple[str, ...] = (
    *NUMERIC_FEATURES,
    "priority_known",
    *(f"priority_{value}" for value in PRIORITY_VALUES),
    "actionability_known",
    *(f"actionability_{value}" for value in ACTIONABILITY_VALUES),
)

# The report-state columns `feature_frame` reads. `age_hours` is not one of them: it is the
# report's age at the scoring moment, derived from the snapshot's own clock, and the caller adds
# it to the rows of every set.
TABULAR_STATE_COLUMNS: tuple[str, ...] = (
    "signal_count",
    "total_weight",
    "run_count",
    "title_chars",
    "summary_chars",
    "priority",
    "actionability",
)

# Side inputs a set may read next to the report-state rows, keyed by name and indexed by
# report_id. The tabular set needs none.
Extras = Mapping[str, pd.DataFrame]
NO_EXTRAS: Extras = MappingProxyType({})

# The report vector, under this key in `extras`: the dataset dag's `inbox_report_embeddings`
# snapshot, indexed by report_id, with the vector in `EMBEDDING_COLUMN`.
REPORT_EMBEDDINGS_EXTRA = "report_embeddings"
EMBEDDING_COLUMN = "embedding_small"
# The width of text-embedding-3-small-1536, the model the report documents are embedded with. A
# row whose vector is a different length is not this model's, so it is treated as missing.
EMBEDDING_DIMENSIONS = 1536

# How many rows one report contributes to a head's examples.
# `scoring_moment` is one row per (report, snapshot): the serving situation replayed over the
# snapshots of the lookback. `report` is one row per report, at the first snapshot of the window
# where it is a usable scoring moment, which is the grain of the newborn pool the unseen read
# grades.
SCORING_MOMENT_GRAIN = "scoring_moment"
REPORT_GRAIN = "report"


def _number(value: Any) -> float:
    if value is None:
        return math.nan
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def feature_vector(row: Mapping[str, Any]) -> list[float]:
    """The feature vector for one scoring moment, in FEATURE_NAMES order.

    `row` carries the report-state columns (`signal_count`, `total_weight`, `run_count`,
    `title_chars`, `summary_chars`, `priority`, `actionability`) and `age_hours`, the report's age
    at the moment being scored. Missing numerics become NaN (XGBoost learns a default direction);
    missing categoricals set the `*_known` flag to 0 with every one-hot at 0.
    """
    values = [_number(row.get(name)) for name in NUMERIC_FEATURES]
    priority = row.get("priority")
    values.append(1.0 if priority in PRIORITY_VALUES else 0.0)
    values.extend(1.0 if priority == value else 0.0 for value in PRIORITY_VALUES)
    actionability = row.get("actionability")
    values.append(1.0 if actionability in ACTIONABILITY_VALUES else 0.0)
    values.extend(1.0 if actionability == value else 0.0 for value in ACTIONABILITY_VALUES)
    return values


def feature_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """Vectorized `feature_vector` over a frame of report-state rows, columns in FEATURE_NAMES order.

    Must agree with `feature_vector` row for row (a test pins it): training builds matrices here,
    the sweep scores one report at a time through `feature_vector`.
    """
    out = pd.DataFrame(index=rows.index)
    for name in NUMERIC_FEATURES:
        out[name] = pd.to_numeric(rows[name], errors="coerce").astype(float) if name in rows else math.nan
    priority = rows["priority"] if "priority" in rows else pd.Series(None, index=rows.index, dtype=object)
    out["priority_known"] = priority.isin(PRIORITY_VALUES).astype(float)
    for value in PRIORITY_VALUES:
        out[f"priority_{value}"] = (priority == value).astype(float)
    actionability = (
        rows["actionability"] if "actionability" in rows else pd.Series(None, index=rows.index, dtype=object)
    )
    out["actionability_known"] = actionability.isin(ACTIONABILITY_VALUES).astype(float)
    for value in ACTIONABILITY_VALUES:
        out[f"actionability_{value}"] = (actionability == value).astype(float)
    return out[list(FEATURE_NAMES)]


class FeatureSet(abc.ABC):
    """One feature universe a model can be fit on and scored with.

    `state_columns` are the report-state columns `build_matrix` reads. The caller always adds
    `age_hours`, so a set may read that without declaring it. `example_grain` and
    `max_examples_per_head` size the set's example population: a set 1536 columns wide cannot
    afford the row count a set 15 columns wide can.
    """

    name: str
    schema_version: int
    feature_names: tuple[str, ...]
    state_columns: tuple[str, ...]
    example_grain: str = SCORING_MOMENT_GRAIN
    # Rows one head's examples may keep, or None for every row the grain produces.
    max_examples_per_head: int | None = None

    @abc.abstractmethod
    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        """The matrix for `rows`, one column per name in `feature_names` order.

        `rows` carries the state columns the set declared plus `age_hours`, indexed by report_id.
        `extras` carries the side inputs a set needs beyond report state.
        """

    def buildable(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.Series:
        """True for each row of `rows` this set can build a real vector for; every row by default.

        A set reading a side input has rows it cannot cover, and the example builder keeps only the
        rows that are True, so a training row never carries an all-missing vector. The scorer does
        not filter on this: every family scores the whole pool, or the grades stop being paired.
        """
        return pd.Series(True, index=rows.index)


class TabularFeatureSet(FeatureSet):
    """The v0 set: the report-state counters, the title and summary lengths, the report's age, and
    the one-hot priority and actionability. This is the set `feature_vector` serves."""

    name = "tabular"
    schema_version = FEATURE_SCHEMA_VERSION
    feature_names = FEATURE_NAMES
    state_columns = TABULAR_STATE_COLUMNS

    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        return feature_frame(rows)


TABULAR_FEATURE_SET = TabularFeatureSet()


class ReportEmbeddingsFeatureSet(FeatureSet):
    """The report's own embedding vector, and nothing else, at one example per report.

    Two modelling calls this set records, both open questions on the issue that asked for it
    (posthog#98243):

    Embedding only, no age. Age is the whole signal of the `recency_auc` line the unseen read
    already reports next to every grade, so leaving it out keeps the uplift claim clean: a gap to
    that line is content, not recency. A set that mixes the two is a third family, not a variant.

    One example per report, not one per scoring moment. A day's newborns over the whole lookback,
    times 1536 floats, is gigabytes of Parquet per partition and more than the training pod holds,
    which is what rules the moment grain out at this width. The first snapshot where a report is a
    usable scoring moment is also the grain of the newborn pool the unseen read grades, so the
    training population matches the graded one. `max_examples_per_head` bounds what is left; the
    lookback stays the tabular set's, so positives still accrue over the whole window.

    Vectors arrive through `extras`, from the dt=D `inbox_report_embeddings` snapshot. A report the
    snapshot has no vector for is not buildable: the source table's TTL runs from report creation,
    so a long-lived report loses its vector while still live, and an all-missing row would teach the
    booster nothing but the base rate.
    """

    name = "report_embeddings"
    schema_version = 1
    # Position order, so `emb_i` is the vector's ith component in every matrix this set builds.
    feature_names = tuple(f"emb_{index}" for index in range(EMBEDDING_DIMENSIONS))
    state_columns = ()
    example_grain = REPORT_GRAIN
    # 1536 float32 columns, so a head's Parquet slice and its training matrix both scale with this.
    # Sized so every head of this family fits one partition's examples object and the fits stay
    # inside the training job's runtime budget, with the budget spent on positives first.
    max_examples_per_head = 25_000

    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        vectors = self._aligned_vectors(rows, extras)
        buildable = self._is_vector(vectors).to_numpy()
        matrix = np.full((len(rows), EMBEDDING_DIMENSIONS), np.nan, dtype=np.float32)
        if buildable.any():
            matrix[buildable] = np.vstack(vectors.to_numpy()[buildable])
        return pd.DataFrame(matrix, index=rows.index, columns=list(self.feature_names))

    def buildable(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.Series:
        return self._is_vector(self._aligned_vectors(rows, extras))

    def _aligned_vectors(self, rows: pd.DataFrame, extras: Extras) -> pd.Series:
        """The vector per row of `rows`, or a missing value where the snapshot has none."""
        vectors = extras.get(REPORT_EMBEDDINGS_EXTRA)
        if vectors is None or EMBEDDING_COLUMN not in vectors:
            return pd.Series(None, index=rows.index, dtype=object)
        return vectors[EMBEDDING_COLUMN].reindex(rows.index)

    @staticmethod
    def _is_vector(vectors: pd.Series) -> pd.Series:
        # An isinstance check rather than a null check: `reindex` fills a missing row with NaN,
        # which is neither None nor a vector, and a wrong-length row is another model's.
        return vectors.map(
            lambda vector: isinstance(vector, list | np.ndarray) and len(vector) == EMBEDDING_DIMENSIONS
        ).astype(bool)


REPORT_EMBEDDINGS_FEATURE_SET = ReportEmbeddingsFeatureSet()

# Every set this build can produce, by name. A model that names a set absent from here cannot be
# scored, the same way a model whose feature names have moved on cannot.
FEATURE_SETS: Mapping[str, FeatureSet] = MappingProxyType(
    {
        TABULAR_FEATURE_SET.name: TABULAR_FEATURE_SET,
        REPORT_EMBEDDINGS_FEATURE_SET.name: REPORT_EMBEDDINGS_FEATURE_SET,
    }
)

# What a model written before `feature_set` was recorded was fit on: every one of those is tabular.
DEFAULT_FEATURE_SET = TABULAR_FEATURE_SET


def feature_set_by_name(name: str | None) -> FeatureSet | None:
    """The named set, the tabular default when the name is absent, or None when this build cannot
    produce it."""
    return DEFAULT_FEATURE_SET if name is None else FEATURE_SETS.get(name)
