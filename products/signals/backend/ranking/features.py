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
judgment artefacts. Embeddings wait for the score log to accrue (skill issue 14).
"""

import abc
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

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
    `age_hours`, so a set may read that without declaring it.
    """

    name: str
    schema_version: int
    feature_names: tuple[str, ...]
    state_columns: tuple[str, ...]

    @abc.abstractmethod
    def build_matrix(self, rows: pd.DataFrame, extras: Extras = NO_EXTRAS) -> pd.DataFrame:
        """The matrix for `rows`, one column per name in `feature_names` order.

        `rows` carries the state columns the set declared plus `age_hours`, indexed by report_id.
        `extras` carries the side inputs a set needs beyond report state.
        """


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

# Every set this build can produce, by name. A model that names a set absent from here cannot be
# scored, the same way a model whose feature names have moved on cannot.
FEATURE_SETS: Mapping[str, FeatureSet] = MappingProxyType({TABULAR_FEATURE_SET.name: TABULAR_FEATURE_SET})

# What a model written before `feature_set` was recorded was fit on: every one of those is tabular.
DEFAULT_FEATURE_SET = TABULAR_FEATURE_SET


def feature_set_by_name(name: str | None) -> FeatureSet | None:
    """The named set, the tabular default when the name is absent, or None when this build cannot
    produce it."""
    return DEFAULT_FEATURE_SET if name is None else FEATURE_SETS.get(name)
