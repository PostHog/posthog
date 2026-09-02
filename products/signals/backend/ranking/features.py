"""Feature universe for the report-ranking model.

One ordered list of feature names, one function that turns a report-state row into that vector.
Training (`products/signals/dags/inbox_ranking/training/`) and serving (the scoring sweep in this
package) must build features through the same code, so the booster's `feature_names` match the
serving matrix by construction; the model's `metadata.json` records FEATURE_SCHEMA_VERSION and the
serving side refuses a booster whose version or feature names disagree with what it can produce.

v0 is tabular only: the report-state columns the dataset dag snapshots from Postgres plus the
report's age at the scoring moment. No report embedding and no impression-derived columns
(`source_products`), so the sweep needs nothing beyond the SignalReport row and its latest
judgment artefacts. Embeddings wait for the score log to accrue (skill issue 14).
"""

import math
from collections.abc import Mapping
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
