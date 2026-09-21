"""Scorers for the experiment setup-inference evals.

The deterministic scorers read the experiment the agent created from the database, not from the
tool calls, so a setting changed by a later `experiment-update` or set on the flag directly still
counts. A scorer that does not apply to a case returns `score=None`, which the engine leaves out
of the mean.

The two judges read the agent's final message: one checks that the summary separates confident
choices from guesses and open decisions, the other checks the case-specific facts it must name.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer

__all__ = [
    "BUCKETING_DEFAULT",
    "BUCKETING_PERSIST_OR_DEVICE_ID",
    "BucketingFitsSurface",
    "CreatedExperiment",
    "MetricWindowsHaveUnits",
    "PrimaryMetricShape",
    "RunningTimeStored",
    "SetupSummaryCallouts",
    "SetupSummaryTiers",
    "SharedMetricReused",
    "SingleFlagCreated",
    "bucketing_fits",
    "load_created_experiment",
    "primary_metric_matches",
    "windows_without_unit",
]

BUCKETING_DEFAULT = "default"
BUCKETING_PERSIST_OR_DEVICE_ID = "persist_or_device_id"
_WINDOWED_METRIC_TYPES = frozenset({"funnel", "mean", "ratio", "retention"})


@frozen
class CreatedExperiment:
    """The state of the experiment the agent created, read after the run."""

    experiment_id: int
    new_experiment_count: int
    inline_primary: tuple[dict[str, Any], ...]
    inline_secondary: tuple[dict[str, Any], ...]
    linked_primary: tuple[dict[str, Any], ...]
    """Queries of the shared metrics linked as primary."""
    linked_secondary: tuple[dict[str, Any], ...]
    linked_saved_metric_ids: tuple[int, ...]
    running_time_calculation: dict[str, Any]
    ensure_experience_continuity: bool
    bucketing_identifier: str
    new_flag_ids: tuple[int, ...]
    experiment_flag_id: int

    def primary_metrics(self) -> tuple[dict[str, Any], ...]:
        return (*self.inline_primary, *self.linked_primary)

    def all_metrics(self) -> tuple[dict[str, Any], ...]:
        return (*self.inline_primary, *self.inline_secondary, *self.linked_primary, *self.linked_secondary)


def load_created_experiment(seed: dict[str, Any]) -> CreatedExperiment | None:
    """Read the newest experiment the agent created in the case team. Synchronous ORM."""
    team_id = seed["team_id"]
    new_experiments = (
        Experiment.objects.filter(team_id=team_id)
        .exclude(deleted=True)
        .exclude(id__in=seed.get("preexisting_experiment_ids") or [])
        .select_related("feature_flag")
        .order_by("-created_at")
    )
    experiment = new_experiments.first()
    if experiment is None:
        return None

    linked_primary: list[dict[str, Any]] = []
    linked_secondary: list[dict[str, Any]] = []
    linked_ids: list[int] = []
    for link in ExperimentToSavedMetric.objects.filter(experiment=experiment).select_related("saved_metric"):
        linked_ids.append(link.saved_metric_id)
        query = link.saved_metric.query if isinstance(link.saved_metric.query, dict) else {}
        # A link without a type counts as primary, as it does in the product.
        is_primary = (link.metadata or {}).get("type", "primary") == "primary"
        (linked_primary if is_primary else linked_secondary).append(query)

    flag = experiment.feature_flag
    new_flag_ids = (
        FeatureFlag.objects.filter(team_id=team_id)
        .exclude(deleted=True)
        .exclude(id__in=seed.get("preexisting_flag_ids") or [])
        .values_list("id", flat=True)
    )
    return CreatedExperiment(
        experiment_id=experiment.id,
        new_experiment_count=new_experiments.count(),
        inline_primary=tuple(m for m in experiment.metrics or [] if isinstance(m, dict)),
        inline_secondary=tuple(m for m in experiment.metrics_secondary or [] if isinstance(m, dict)),
        linked_primary=tuple(linked_primary),
        linked_secondary=tuple(linked_secondary),
        linked_saved_metric_ids=tuple(linked_ids),
        running_time_calculation=experiment.running_time_calculation or {},
        ensure_experience_continuity=bool(flag.ensure_experience_continuity),
        bucketing_identifier=flag.bucketing_identifier or "distinct_id",
        new_flag_ids=tuple(new_flag_ids),
        experiment_flag_id=flag.id,
    )


def metric_event(metric: dict[str, Any]) -> str | None:
    """The event a metric measures: the last funnel step, the mean source, the retention completion."""
    metric_type = metric.get("metric_type")
    node: Any = None
    if metric_type == "funnel":
        series = metric.get("series") or []
        node = series[-1] if series else None
    elif metric_type == "mean":
        node = metric.get("source")
    elif metric_type == "retention":
        node = metric.get("completion_event")
    elif metric_type == "ratio":
        node = metric.get("numerator")
    return node.get("event") if isinstance(node, dict) else None


def windows_without_unit(metrics: Sequence[dict[str, Any]]) -> list[str]:
    """Describe each metric whose conversion window has no unit. A window without a unit is ignored."""
    return [
        f"{metric.get('metric_type')} metric on {metric_event(metric)!r}: conversion_window without conversion_window_unit"
        for metric in metrics
        if metric.get("metric_type") in _WINDOWED_METRIC_TYPES
        and metric.get("conversion_window") is not None
        and not metric.get("conversion_window_unit")
    ]


def primary_metric_matches(metric: dict[str, Any], spec: dict[str, Any]) -> bool:
    """`spec` keys: `metric_types` (required), and optionally `event`, `math`, `math_property`, and
    `requires_window` (a conversion window with a unit)."""
    if metric.get("metric_type") not in spec["metric_types"]:
        return False
    if spec.get("requires_window") and (
        metric.get("conversion_window") is None or not metric.get("conversion_window_unit")
    ):
        return False
    if "event" in spec and metric_event(metric) != spec["event"]:
        return False
    raw_source = metric.get("source")
    source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    if "math" in spec and source.get("math") != spec["math"]:
        return False
    if "math_property" in spec and source.get("math_property") != spec["math_property"]:
        return False
    return True


def bucketing_fits(created: CreatedExperiment, mode: str) -> tuple[bool, str]:
    continuity = created.ensure_experience_continuity
    device_id = created.bucketing_identifier == "device_id"
    state = f"ensure_experience_continuity={continuity}, bucketing_identifier={created.bucketing_identifier}"
    if mode == BUCKETING_DEFAULT:
        return (not continuity and not device_id), state
    if mode == BUCKETING_PERSIST_OR_DEVICE_ID:
        return (continuity or device_id), state
    raise ValueError(f"Unknown bucketing mode {mode!r}")


class _CreatedExperimentScorer(AsyncOnlyScorerMixin, Scorer):
    """Loads the created experiment once per call and hands it to `_score`.

    `applies_to_all` scorers run on every case. The rest run only when `expected` carries their
    name, and receive that value. Each scorer reads the experiment itself: one small read per
    scorer per case.
    """

    applies_to_all = False

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        raise NotImplementedError

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        expected_value = expected.get(self._name()) if isinstance(expected, dict) else None
        if not self.applies_to_all and expected_value is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable to this case"})
        seed = output.get("seed") if isinstance(output, dict) else None
        if not isinstance(seed, dict) or "team_id" not in seed:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seed with a team_id"})
        # The scorer runs on the event loop, and Django rejects sync ORM calls there.
        created = await asyncio.to_thread(load_created_experiment, seed)
        if created is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "The agent created no experiment"})
        return self._score(created, expected_value, seed)


class BucketingFitsSurface(_CreatedExperimentScorer):
    """`expected={"bucketing_fits_surface": "default" | "persist_or_device_id"}`.

    `default` is user-id bucketing without persistence. It is also the answer when a server
    evaluates the flag locally: persistence does not work there, and device-id bucketing would put
    the server and the browser in different variants.
    """

    def _name(self) -> str:
        return "bucketing_fits_surface"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        passed, state = bucketing_fits(created, expected_value)
        return Score(name=self._name(), score=float(passed), metadata={"expected": expected_value, "state": state})


class MetricWindowsHaveUnits(_CreatedExperimentScorer):
    """Every metric window carries a unit. Skipped when no metric has a window."""

    applies_to_all = True

    def _name(self) -> str:
        return "metric_windows_have_units"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        windowed = [m for m in created.all_metrics() if m.get("conversion_window") is not None]
        if not windowed:
            return Score(name=self._name(), score=None, metadata={"reason": "No metric sets a window"})
        problems = windows_without_unit(windowed)
        return Score(name=self._name(), score=0.0 if problems else 1.0, metadata={"problems": problems})


class PrimaryMetricShape(_CreatedExperimentScorer):
    """`expected={"primary_metric_shape": {"metric_types": [...], "event": ..., "requires_window": True, ...}}`.

    Passes when any primary metric, inline or shared, matches every key given.
    """

    def _name(self) -> str:
        return "primary_metric_shape"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        passed = any(primary_metric_matches(metric, expected_value) for metric in created.primary_metrics())
        return Score(
            name=self._name(),
            score=float(passed),
            metadata={
                "expected": expected_value,
                "primary_metrics": [
                    {"metric_type": m.get("metric_type"), "event": metric_event(m)} for m in created.primary_metrics()
                ],
            },
        )


class RunningTimeStored(_CreatedExperimentScorer):
    """`expected={"running_time_stored": True}`: a running time or sample size is saved on the experiment."""

    def _name(self) -> str:
        return "running_time_stored"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        calculation = created.running_time_calculation
        stored = any(
            calculation.get(key) is not None for key in ("recommended_running_time", "recommended_sample_size")
        )
        return Score(name=self._name(), score=float(stored), metadata={"running_time_calculation": calculation})


class SharedMetricReused(_CreatedExperimentScorer):
    """`expected={"shared_metric_reused": True}`: the seeded shared metric is linked, and no inline
    metric measures the same event."""

    def _name(self) -> str:
        return "shared_metric_reused"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        linked = seed.get("shared_metric_id") in created.linked_saved_metric_ids
        inline_duplicates = sum(
            1
            for metric in (*created.inline_primary, *created.inline_secondary)
            if metric_event(metric) == seed.get("conversion_event")
        )
        return Score(
            name=self._name(),
            score=float(linked and not inline_duplicates),
            metadata={
                "linked": linked,
                "linked_saved_metric_ids": list(created.linked_saved_metric_ids),
                "inline_duplicates": inline_duplicates,
            },
        )


class SingleFlagCreated(_CreatedExperimentScorer):
    """The only new flag is the experiment's own."""

    applies_to_all = True

    def _name(self) -> str:
        return "single_flag_created"

    def _score(self, created: CreatedExperiment, expected_value: Any, seed: dict[str, Any]) -> Score:
        passed = created.new_flag_ids == (created.experiment_flag_id,) and created.new_experiment_count == 1
        return Score(
            name=self._name(),
            score=float(passed),
            metadata={"new_flag_ids": list(created.new_flag_ids), "new_experiments": created.new_experiment_count},
        )


def _final_message(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    message = output.get("last_message")
    return message if isinstance(message, str) and message.strip() else None


class SetupSummaryTiers(JudgedScorer):
    """Runs on every case: the final message separates confident choices, guesses and open decisions."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="setup_summary_tiers",
            prompt_template="""
You are judging the summary an agent wrote after it created a draft A/B experiment for a user who was not available to answer questions.

User's request:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

A good summary lets the user review the draft quickly. Answer `yes` only if all of these hold:
1. It states the setup choices it made, including at least how users are assigned to variants (bucketing or persistence) and which metric is primary.
2. It makes clear which choices rest on evidence and which are guesses the user should check. Separate sections, labels, or explicit "please check" wording all qualify.
3. Where a choice depends on something the agent could not determine, it says so and says what would decide it, rather than presenting a guess as settled.
4. Choices are tied to facts about this project's data (traffic, logged-out share, event volume, existing metrics), not only to general best practice.

Answer `no` if the summary presents every choice with the same confidence, gives no reasons, or only lists what was created.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        last_message = _final_message(output)
        if last_message is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {"output": {"prompt": output.get("prompt", ""), "last_message": last_message}}


class SetupSummaryCallouts(JudgedScorer):
    """`expected={"setup_summary_callouts": ["fact the summary must state", ...]}`."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="setup_summary_callouts",
            prompt_template="""
You are judging the summary an agent wrote after it created a draft A/B experiment.

The summary must convey each of these points, in substance (paraphrasing is fine):
<points>
{{output.callouts}}
</points>

User's request:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` only if every point is conveyed. Extra points are fine. Answer `no` if any point is missing, contradicted, or only hinted at without the reason.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        callouts = expected.get(self._name()) if isinstance(expected, dict) else None
        if not callouts:
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable to this case"})
        last_message = _final_message(output)
        if last_message is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": output.get("prompt", ""),
                "last_message": last_message,
                "callouts": "\n".join(f"{index}. {point}" for index, point in enumerate(callouts, start=1)),
            }
        }
