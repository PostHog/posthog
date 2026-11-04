"""The recipe of a model version: everything that makes one day's fit comparable to the next.

`model_name` names a recipe, and `model_version` is the day it was fit on. A candidate's
`metadata.json` carries `recipe` (the inputs below, as a dict) and `recipe_hash`, a stable hash of
that dict. The recipe holds what a daily retrain keeps fixed: the learner, the feature set, the
learner's settings, each head's label definition and horizon, the example window and budget, and
the dataset version. It never holds dates, the `run_id`, row counts or metrics.

The promotion gate grades a candidate only against the served model of its own `model_name`, so two
recipes under one name would be compared as if they were one series. The candidate asset refuses
that: it compares its hash with the newest version of the same name, at or before its partition,
that has one, and fails before it writes the partition when they differ. The fix is a new `model_name`, not an override.
"""

import json
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from posthog import settings

from products.signals.backend.ranking.features import MIN_PROJECT_HISTORY_REPORTS, FeatureSet
from products.signals.dags.inbox_ranking.common import DATASET_VERSION
from products.signals.dags.inbox_ranking.dataset import project_vectors
from products.signals.dags.inbox_ranking.training.heads import Head

RECIPE_KEY = "recipe"
RECIPE_HASH_KEY = "recipe_hash"


def model_recipe(
    *,
    model_kind: str,
    feature_set: FeatureSet,
    heads: Sequence[Head],
    learner_params: Mapping[str, Any],
    project_vector_kinds: Sequence[str] = (),
) -> dict[str, Any]:
    """`learner_params` are the booster params for XGBoost, or the network config for `nn`."""
    return {
        "model_kind": model_kind,
        "feature_set": feature_set.name,
        "feature_schema_version": feature_set.schema_version,
        "project_vector_kinds": list(project_vector_kinds),
        # Both change the project inputs, so they matter only to a model that reads project vectors.
        "project_vector_settings": (
            {
                "history_limit": project_vectors.HISTORY_LIMIT,
                "min_history_reports": MIN_PROJECT_HISTORY_REPORTS,
            }
            if project_vector_kinds
            else {}
        ),
        "learner_params": dict(learner_params),
        "heads": {
            head.name: {
                "cohort": head.cohort.__name__,
                "label": head.label.__name__,
                "horizon_days": head.horizon_days,
                # Both drop example rows, so a change to either changes what the head is fit on.
                "label_columns": list(head.label_columns),
                "status_labels": head.status_labels,
            }
            for head in heads
        },
        "lookback_days": settings.INBOX_RANKING_TRAINING_LOOKBACK_DAYS,
        "holdout_days": settings.INBOX_RANKING_TRAINING_HOLDOUT_DAYS,
        "example_grain": feature_set.example_grain,
        "max_examples_per_head": feature_set.max_examples_per_head,
        "dataset_version": DATASET_VERSION,
    }


def recipe_hash(recipe: Mapping[str, Any]) -> str:
    canonical = json.dumps(recipe, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def with_recipe(metadata: Mapping[str, Any], recipe: Mapping[str, Any]) -> dict[str, Any]:
    return {**metadata, RECIPE_KEY: dict(recipe), RECIPE_HASH_KEY: recipe_hash(recipe)}


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        flat: dict[str, Any] = {}
        for key, inner in value.items():
            flat |= _flatten(inner, f"{path}.{key}" if path else str(key))
        return flat
    return {path: value}


def changed_recipe_keys(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The dotted paths whose values differ, such as `learner_params.epochs`."""
    before, after = _flatten(previous), _flatten(current)
    return sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))


def recipe_mismatch(model_name: str, recipe: Mapping[str, Any], previous: Mapping[str, Any] | None) -> str | None:
    """Why a candidate with `recipe` must not be written under `model_name`, or None when it may.

    `previous` is the metadata of the newest version of the name, at or before this partition, that
    has a hash. None
    means there is nothing to compare: the name is new, or its versions predate the hash."""
    if previous is None or previous.get(RECIPE_HASH_KEY) == recipe_hash(recipe):
        return None
    changed = changed_recipe_keys(previous.get(RECIPE_KEY) or {}, recipe)
    return (
        f"{model_name} recipe changed since {model_name}@{previous.get('model_version')} "
        f"(changed: {', '.join(changed) or 'unknown'}). A recipe change needs a new model_name in "
        "MODEL_FAMILIES, so the promotion gate never compares two recipes."
    )
