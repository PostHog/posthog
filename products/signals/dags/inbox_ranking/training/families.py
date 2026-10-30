"""The model families: which features and which learner each one fits, and where.

A family is either a serving family or an experiment. A serving family can be served, enters the
serving manifest as a challenger, and gets online grades. An experiment trains in its own job
(`nn/experiments.py`), is graded only against its `baseline` on the same holdout, never enters the
manifest, and can never be promoted or pinned. An experiment stops training after its `expires`
day, so a modeling idea cannot grow into a permanent cost by accident. To serve an experiment's
recipe, register it as a serving family under a new `model_name`.

A family has a grain. A report-grain family scores one row per report, as the inbox reads it. A
pair-grain family scores one row per (report, impressed user) from `inbox_ranking_nn_pair_examples`,
and is experiment-only until a serving design reads a personal score. Its baseline is another pair
experiment, and its optional `reference` is a report-grain serving family fit on the same days and
graded on the same holdout pairs, so it answers "better than the report-level score".
"""

import datetime
from collections.abc import Sequence
from typing import Final, Literal

from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import (
    ALL_PROJECT_VECTOR_KINDS,
    PAIR_BASE_FEATURE_SET,
    PAIR_USER_HISTORY_FEATURE_SET,
    PROJECT_VECTOR_KINDS,
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
NN_WITH_PRIO_FIXED_MODEL_NAME = "nn_with_prio_fixed_v1"
NN_WITH_PRIO_FIXED_NODISMISS_MODEL_NAME = "nn_with_prio_fixed_nodismiss_v1"
FIXED_EXPERIMENT_EXPIRES = datetime.date(2026, 11, 27)
NN_PAIR_BASE_MODEL_NAME = "nn_pair_base_v1"
NN_PAIR_USER_MODEL_NAME = "nn_pair_user_v1"
PAIR_EXPERIMENT_EXPIRES = datetime.date(2026, 11, 25)
# The Dagster code locations that train a family: `signals` on the main image, and `signals_ml` on
# the image that carries torch.
MAIN_LOCATION = "signals"
ML_LOCATION = "signals_ml"
REPORT_GRAIN: Final = "report"
PAIR_GRAIN: Final = "pair"
Grain = Literal["report", "pair"]
# The heads a pair-grain family can declare: the pair examples carry these labels only.
PAIR_HEAD_NAMES = ("open", "action")


@frozen
class ModelFamily:
    """One family the training jobs fit: its name, the feature set it is fit on, the learner a
    model store loads it with, and the Dagster code location whose assets train it.

    An experiment names the serving family it is graded against in `baseline`, and the last
    partition day it trains in `expires`. A serving family has neither.

    `project_vector_kinds` are the team context kinds the network reads, in its input order. Only a
    report-grain experiment can change them. The pair lane reads `PROJECT_VECTOR_KINDS` only.

    A pair-grain family is always an experiment and declares its `heads` from `PAIR_HEAD_NAMES`. Its
    `baseline` is another pair experiment, and it names a `baseline`, a `reference`, or both: the
    first pair family of a comparison has no pair baseline and is graded against the reference only."""

    name: str
    feature_set: FeatureSet
    learner: str = DEFAULT_MODEL_KIND
    location: str = MAIN_LOCATION
    experiment: bool = False
    baseline: str | None = None
    expires: datetime.date | None = None
    grain: Grain = REPORT_GRAIN
    # A pair-grain family's heads. A report-grain family trains every `nn` head and declares none.
    heads: tuple[str, ...] = ()
    reference: str | None = None
    project_vector_kinds: tuple[str, ...] = PROJECT_VECTOR_KINDS

    def __post_init__(self) -> None:
        self._check_project_vector_kinds()
        if self.grain == PAIR_GRAIN:
            self._check_pair()
            return
        if self.heads or self.reference is not None:
            raise ValueError(f"report-grain family {self.name} cannot declare heads or a reference")
        if self.experiment and (self.baseline is None or self.expires is None):
            raise ValueError(f"experiment family {self.name} needs a baseline and an expires day")
        if not self.experiment and (self.baseline is not None or self.expires is not None):
            raise ValueError(f"serving family {self.name} cannot have a baseline or an expires day")

    def _check_project_vector_kinds(self) -> None:
        kinds = self.project_vector_kinds
        if not kinds or len(set(kinds)) != len(kinds) or not set(kinds) <= set(ALL_PROJECT_VECTOR_KINDS):
            raise ValueError(
                f"family {self.name} declares project vector kinds {list(kinds)}; pick distinct kinds from "
                f"{list(ALL_PROJECT_VECTOR_KINDS)}"
            )
        if kinds != PROJECT_VECTOR_KINDS and (not self.experiment or self.grain == PAIR_GRAIN):
            raise ValueError(
                f"family {self.name} declares project vector kinds {list(kinds)}; only a report-grain experiment "
                f"can read other kinds than {list(PROJECT_VECTOR_KINDS)}"
            )

    def _check_pair(self) -> None:
        if not self.experiment:
            raise ValueError(
                f"pair-grain family {self.name} must be an experiment: no serving design reads a pair score yet"
            )
        if self.expires is None:
            raise ValueError(f"experiment family {self.name} needs an expires day")
        if self.baseline is None and self.reference is None:
            raise ValueError(f"pair experiment {self.name} needs a baseline, a reference, or both")
        if not self.heads or len(set(self.heads)) != len(self.heads) or not set(self.heads) <= set(PAIR_HEAD_NAMES):
            raise ValueError(
                f"pair experiment {self.name} declares heads {list(self.heads)}; pick distinct heads from "
                f"{list(PAIR_HEAD_NAMES)}"
            )

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
# `nn_with_prio_fixed_v1` adds a `fixed` project vector to `nn_with_prio_v2`, because fixes reach
# teams whose UI kinds are thin. `nn_with_prio_fixed_nodismiss_v1` swaps `dismiss` for `fixed`.
# `nn_pair_base_v1` and `nn_pair_user_v1` are the user-history comparison at pair grain: one network,
# one input shape, the same pairs and seeds, and the same reviewer flag. The base holds every
# user-history input at zero, so `nn_pair_user_v1` against it is the uplift of the user's history
# alone. Both are also read against the report-level `nn_with_prio_v2`.
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
    ModelFamily(
        name=NN_WITH_PRIO_FIXED_MODEL_NAME,
        feature_set=REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
        experiment=True,
        baseline=NN_WITH_PRIO_MODEL_NAME,
        expires=FIXED_EXPERIMENT_EXPIRES,
        project_vector_kinds=("typical", "open", "action", "dismiss", "fixed"),
    ),
    ModelFamily(
        name=NN_WITH_PRIO_FIXED_NODISMISS_MODEL_NAME,
        feature_set=REPORT_EMBEDDINGS_PRIORITY_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
        experiment=True,
        baseline=NN_WITH_PRIO_MODEL_NAME,
        expires=FIXED_EXPERIMENT_EXPIRES,
        project_vector_kinds=("typical", "open", "action", "fixed"),
    ),
    ModelFamily(
        name=NN_PAIR_BASE_MODEL_NAME,
        feature_set=PAIR_BASE_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
        experiment=True,
        expires=PAIR_EXPERIMENT_EXPIRES,
        grain=PAIR_GRAIN,
        heads=PAIR_HEAD_NAMES,
        reference=NN_WITH_PRIO_MODEL_NAME,
    ),
    ModelFamily(
        name=NN_PAIR_USER_MODEL_NAME,
        feature_set=PAIR_USER_HISTORY_FEATURE_SET,
        learner=ONNX_MODEL_KIND,
        location=ML_LOCATION,
        experiment=True,
        baseline=NN_PAIR_BASE_MODEL_NAME,
        expires=PAIR_EXPERIMENT_EXPIRES,
        grain=PAIR_GRAIN,
        heads=PAIR_HEAD_NAMES,
        reference=NN_WITH_PRIO_MODEL_NAME,
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


def _baseline_problem(family: ModelFamily, by_name: dict[str, ModelFamily], serving: set[str]) -> str | None:
    if family.baseline is None:
        return None
    baseline = by_name.get(family.baseline)
    if baseline is not None and baseline.grain != family.grain:
        return (
            f"experiment {family.name} is {family.grain} grain and its baseline {baseline.name} is "
            f"{baseline.grain} grain"
        )
    if family.grain == REPORT_GRAIN and family.baseline not in serving:
        return f"experiment {family.name} names baseline {family.baseline}, which is not a serving family"
    if family.grain == PAIR_GRAIN and (baseline is None or not baseline.experiment):
        return f"experiment {family.name} names baseline {family.baseline}, which is not a registered pair experiment"
    return None


def _baseline_cycle(family: ModelFamily, by_name: dict[str, ModelFamily]) -> list[str] | None:
    """The baseline chain from `family` back to itself, or None when the chain ends."""
    chain = [family.name]
    current = family
    while current.baseline is not None and current.baseline in by_name:
        if current.baseline in chain:
            return [*chain, current.baseline] if current.baseline == family.name else None
        chain.append(current.baseline)
        current = by_name[current.baseline]
    return None


def family_problems(families: Sequence[ModelFamily]) -> list[str]:
    """Why `families` is not a valid registry: a duplicate name, an experiment whose baseline is not
    a serving family of its grain (a pair experiment's is another registered pair experiment), a
    baseline of the other grain, a baseline cycle, or a reference that is not a report-grain serving
    family."""
    names = [family.name for family in families]
    problems = [f"family {name} is registered twice" for name in sorted({n for n in names if names.count(n) > 1})]
    by_name = {family.name: family for family in families}
    serving = {family.name for family in serving_families(families)}
    for family in experiment_families(families):
        problem = _baseline_problem(family, by_name, serving)
        if problem is not None:
            problems.append(problem)
        cycle = _baseline_cycle(family, by_name)
        if cycle is not None:
            problems.append(f"experiment {family.name} has a baseline cycle: {' -> '.join(cycle)}")
        reference = by_name.get(family.reference) if family.reference is not None else None
        if family.reference is not None and (
            reference is None or reference.experiment or reference.grain != REPORT_GRAIN
        ):
            problems.append(
                f"experiment {family.name} names reference {family.reference}, which is not a report-grain "
                "serving family"
            )
    return problems


_PROBLEMS = family_problems(MODEL_FAMILIES)
if _PROBLEMS:
    raise ValueError("; ".join(_PROBLEMS))
