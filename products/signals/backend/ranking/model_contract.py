"""Whether a published ranking model can be scored by this build.

The training dag and the serving store make the same decision about the same `metadata.json`, so
the rules live here, next to the feature sets they check against. The dag grades a model it can
score, and the server serves a model it can score; code copied between the two would let them
disagree about which models those are.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from products.signals.backend.ranking.features import FeatureSet, feature_set_by_name

# The late feature groups a fit zeroed on every row (`zero_unfitted_groups` in the nn dag). A model
# whose set has late feature groups records them, so serving zeroes the same groups for that version.
ZEROED_FEATURE_GROUPS_KEY = "zeroed_feature_groups"


def model_feature_set(metadata: Mapping[str, Any]) -> FeatureSet | None:
    """The feature set the model declares, or None when this build cannot produce it. Metadata
    that declares no set is left unscored."""
    return feature_set_by_name(metadata.get("feature_set"))


def model_mismatch(metadata: Mapping[str, Any]) -> str | None:
    """Why the model cannot be scored, or None when it can.

    A model is checked against its own declared set rather than one global contract, so a family
    on one set is not rejected for disagreeing with another set.
    """
    feature_set = model_feature_set(metadata)
    if feature_set is None:
        return f"feature set {metadata.get('feature_set')} is not one this build can produce"
    version = metadata.get("feature_schema_version")
    if version != feature_set.schema_version:
        return f"feature_schema_version {version} is not {feature_set.name}'s {feature_set.schema_version}"
    if tuple(metadata.get("feature_names") or ()) != feature_set.feature_names:
        return f"feature_names differ from the {feature_set.name} feature set"
    if feature_set.late_feature_groups:
        zeroed = metadata.get(ZEROED_FEATURE_GROUPS_KEY)
        if not isinstance(zeroed, list) or not set(zeroed) <= set(feature_set.late_feature_groups):
            return (
                f"{ZEROED_FEATURE_GROUPS_KEY} does not list late feature groups of the {feature_set.name} feature set"
            )
    return None


def zeroed_feature_groups(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    """The late feature groups the model's fit zeroed, which serving zeroes too. Read only from a
    model that `model_mismatch` accepts."""
    return tuple(metadata.get(ZEROED_FEATURE_GROUPS_KEY) or ())


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


def classification_thresholds(metadata: Mapping[str, Any]) -> dict[str, float]:
    """The saved refit threshold per head. A model saved before thresholds existed has none, and its
    grades then report null classification fields rather than a threshold read from the graded rows."""
    return {
        entry["head"]: float(entry["refit_classification_threshold"])
        for entry in metadata.get("heads", [])
        if entry.get("refit_classification_threshold") is not None
    }


def head_lifts(scores: Mapping[str, float], metadata: Mapping[str, Any]) -> dict[str, float]:
    """Each head's probability over its base rate, the saved refit threshold. A head without a
    positive saved threshold has no lift, and no other value may stand in for it."""
    thresholds = classification_thresholds(metadata)
    return {
        head: probability / thresholds[head] for head, probability in scores.items() if thresholds.get(head, 0.0) > 0.0
    }


def trained_head_files(metadata: Mapping[str, Any], known_heads: Collection[str]) -> dict[str, str]:
    """The model file per head the candidate fit, of the heads in `known_heads`: `<head>.ubj` for a
    per-head booster, and the one shared `model.onnx` for every head of an ONNX model.

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
