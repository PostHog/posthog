"""Whether a published ranking model can be scored by this build.

The training dag and the serving store make the same decision about the same `metadata.json`, so
the rules live here, next to the feature sets they check against. The dag grades a model it can
score, and the server serves a model it can score; code copied between the two would let them
disagree about which models those are.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from products.signals.backend.ranking.features import FeatureSet, feature_set_by_name


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


def booster_mismatch(head: str, booster_feature_names: Sequence[str] | None, feature_set: FeatureSet) -> str | None:
    """Why one loaded head booster cannot take the feature set's matrix, or None when it can.

    `model_mismatch` reads only the metadata record. A booster file replaced under an unchanged
    `metadata.json` passes that check, so a loader asks the booster itself as well.
    """
    if tuple(booster_feature_names or ()) != feature_set.feature_names:
        return f"{head} booster feature_names differ from the {feature_set.name} feature set"
    return None


def readable_head_names(metadata: Mapping[str, Any]) -> frozenset[str]:
    """The heads of a model whose holdout AUC could be read."""
    return frozenset(entry["head"] for entry in metadata.get("heads", []) if entry.get("readable"))


def trained_head_files(metadata: Mapping[str, Any], known_heads: Collection[str]) -> dict[str, str]:
    """The `<head>.ubj` object name per head the candidate fit, of the heads in `known_heads`.

    Every trained head is scored, readable or not. A rare head never clears `min_holdout_positives`
    on one day's holdout, and the pooled newborn grade over many days is the only read that can
    ever give it a number; gating the scoring on readability means that read never starts. An
    unreadable head has no holdout AUC to compare against, so read its grade on its own, and the
    promotion gate still ignores it.

    The dag passes the heads it defines. The server passes the heads its manifest entry names,
    because the dag already chose those with this same function.
    """
    return {
        entry["head"]: entry["file"]
        for entry in metadata.get("heads", [])
        if entry.get("file") and entry.get("head") in known_heads
    }
