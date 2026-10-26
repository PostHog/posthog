"""The model families: which features and which learner each one fits, and where.

A family is either a serving family or an experiment. A serving family can be served, enters the
serving manifest as a challenger, and gets online grades. An experiment trains in its own job
(`nn/experiments.py`), is graded only against its `baseline` on the same holdout, never enters the
manifest, and can never be promoted or pinned. An experiment stops training after its `expires`
day, so a modeling idea cannot grow into a permanent cost by accident. To serve an experiment's
recipe, register it as a serving family under a new `model_name`.
"""

import datetime
from collections.abc import Sequence

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    REPORT_EMBEDDINGS_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
    REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
    FeatureSet,
)
from products.signals.backend.ranking.serving_manifest import DEFAULT_MODEL_KIND, ONNX_MODEL_KIND

# The model family: which features and which learner, as against `model_version`, the partition day
# it was fit on. Both are in the identity, so two families trained on one day stay apart.
# A recipe change takes a new name (`training/recipe.py`). The versions of an earlier name stay
# servable by key, and their online grades keep their own series.
NN_MODEL_NAME = "nn_v3"
NN_WITH_PRIO_MODEL_NAME = "nn_with_prio_v2"
NN_WITH_PRIO_SOURCES_MODEL_NAME = "nn_with_prio_sources_v1"
# The Dagster code locations that train a family: `signals` on the main image, and `signals_ml` on
# the image that carries torch.
MAIN_LOCATION = "signals"
ML_LOCATION = "signals_ml"


@frozen
class ModelFamily:
    """One family the training jobs fit: its name, the feature set it is fit on, the learner a
    model store loads it with, and the Dagster code location whose assets train it.

    An experiment names the serving family it is graded against in `baseline`, and the last
    partition day it trains in `expires`. A serving family has neither."""

    name: str
    feature_set: FeatureSet
    learner: str = DEFAULT_MODEL_KIND
    location: str = MAIN_LOCATION
    experiment: bool = False
    baseline: str | None = None
    expires: datetime.date | None = None

    def __post_init__(self) -> None:
        if self.experiment and (self.baseline is None or self.expires is None):
            raise ValueError(f"experiment family {self.name} needs a baseline and an expires day")
        if not self.experiment and (self.baseline is not None or self.expires is not None):
            raise ValueError(f"serving family {self.name} cannot have a baseline or an expires day")

    def expired(self, day: datetime.date) -> bool:
        return self.expires is not None and day > self.expires


# The families the training jobs train, in the order they are trained. A
# family with no metadata for the day is skipped, so an entry can be added here before its trainer
# writes its first candidate, and a family that fails costs its own series rather than every one.
# `nn` is one multi-head network over the report vector and the team's project vectors. It needs
# torch, so the `signals_ml` location trains it. The main location fits no family. `nn` declares
# the report embeddings set, because that set builds its report input in training and at serving.
# `nn_with_prio_v2` is the same network with the report's priority levels as extra report inputs.
# `nn_with_prio_sources_v1` is an experiment: `nn_with_prio_v2` plus the source products of the
# report's signals as of the moment, graded against `nn_with_prio_v2`.
MODEL_FAMILIES: tuple[ModelFamily, ...] = (
    ModelFamily(
        name=NN_MODEL_NAME, feature_set=REPORT_EMBEDDINGS_FEATURE_SET, learner=ONNX_MODEL_KIND, location=ML_LOCATION
    ),
    ModelFamily(
        name=NN_WITH_PRIO_MODEL_NAME,
        feature_set=REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
    ),
    ModelFamily(
        name=NN_WITH_PRIO_SOURCES_MODEL_NAME,
        feature_set=REPORT_EMBEDDINGS_PRIORITY_SOURCES_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
        experiment=True,
        baseline=NN_WITH_PRIO_MODEL_NAME,
        expires=datetime.date(2026, 11, 11),
    ),
)
NN_FAMILY = next(family for family in MODEL_FAMILIES if family.name == NN_MODEL_NAME)
NN_WITH_PRIO_FAMILY = next(family for family in MODEL_FAMILIES if family.name == NN_WITH_PRIO_MODEL_NAME)


def serving_families(families: Sequence[ModelFamily] = MODEL_FAMILIES) -> tuple[ModelFamily, ...]:
    """The families the serving manifest, the promote job and the online grader can read."""
    return tuple(family for family in families if not family.experiment)


def experiment_families(families: Sequence[ModelFamily] = MODEL_FAMILIES) -> tuple[ModelFamily, ...]:
    """The families the experiments job trains, expired ones included. The job skips an expired one."""
    return tuple(family for family in families if family.experiment)


def experiment_names(families: Sequence[ModelFamily] = MODEL_FAMILIES) -> frozenset[str]:
    return frozenset(family.name for family in experiment_families(families))


def families_trained_in(location: str) -> tuple[ModelFamily, ...]:
    """The serving families whose candidate and champion assets live in `location`. The serving
    manifest and the online grader walk every serving family, so a family gains both wherever it
    trains."""
    return tuple(family for family in serving_families() if family.location == location)


def family_problems(families: Sequence[ModelFamily]) -> list[str]:
    """Why `families` is not a valid registry: a duplicate name, or an experiment whose baseline is
    not a serving family in the registry."""
    names = [family.name for family in families]
    problems = [f"family {name} is registered twice" for name in sorted({n for n in names if names.count(n) > 1})]
    serving = {family.name for family in serving_families(families)}
    problems += [
        f"experiment {family.name} names baseline {family.baseline}, which is not a serving family"
        for family in experiment_families(families)
        if family.baseline not in serving
    ]
    return problems


_PROBLEMS = family_problems(MODEL_FAMILIES)
if _PROBLEMS:
    raise ValueError("; ".join(_PROBLEMS))
