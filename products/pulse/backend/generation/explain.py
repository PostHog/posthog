from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from django.db.models import F, Q
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from posthog.models.team import Team

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.pulse.backend.sources.annotations import annotation_marker_summary, annotations_in_period

MAX_CANDIDATES_PER_KIND = 10
LABEL_MAX_CHARS = 100

CandidateKind = Literal["flag", "experiment", "annotation"]


@dataclass(frozen=True)
class CausalCandidate:
    """A deterministic hypothesis for why a metric moved — collected, never inferred.

    `label` and `detail` carry untrusted free text (flag keys, experiment names, annotation
    content); they are sanitized once at the prompt-render boundary, collectors stay raw.
    `ref` is a citation-ready evidence ref like `flag:123` (numeric ids — that's what the
    frontend scenes link by).
    """

    kind: CandidateKind
    ref: str
    label: str
    happened_at: str
    detail: str


def collect_causal_candidates(team: Team, period_days: int) -> list[CausalCandidate]:
    now = timezone.now()
    period_start = now - timedelta(days=period_days)
    return [
        *_flag_candidates(team, period_start),
        *_experiment_candidates(team, period_start, now),
        *_annotation_candidates(team, period_start, now),
    ]


def _flag_candidates(team: Team, period_start: datetime) -> list[CausalCandidate]:
    # updated_at moves on ANY save (auto_now), not just rollout changes — accepted v1 noise;
    # precise change attribution would need the activity log. No upper bound: auto_now can't
    # be in the future.
    flags = (
        FeatureFlag.objects.filter(team=team, deleted=False)
        .annotate(changed_at=Coalesce(F("updated_at"), F("created_at")))
        .filter(changed_at__gte=period_start)
        .order_by("-changed_at")[:MAX_CANDIDATES_PER_KIND]
    )
    return [
        CausalCandidate(
            kind="flag",
            ref=f"flag:{flag.id}",
            label=flag.key[:LABEL_MAX_CHARS],
            happened_at=f"{flag.changed_at:%Y-%m-%d}",
            detail=(
                f"Feature flag {'created' if flag.created_at >= period_start else 'updated'} in the period; "
                f"currently {'active' if flag.active else 'inactive'}."
            ),
        )
        for flag in flags
    ]


def _experiment_candidates(team: Team, period_start: datetime, now: datetime) -> list[CausalCandidate]:
    in_period = Q(start_date__gte=period_start, start_date__lte=now) | Q(end_date__gte=period_start, end_date__lte=now)
    experiments = (
        Experiment.objects.filter(team=team)
        .exclude(deleted=True)
        .filter(in_period)
        # Postgres GREATEST ignores NULLs, so this orders by the most recent boundary event.
        .annotate(latest_event=Greatest(F("start_date"), F("end_date")))
        .order_by("-latest_event")[:MAX_CANDIDATES_PER_KIND]
    )
    candidates: list[CausalCandidate] = []
    for experiment in experiments:
        # An experiment that both launched and stopped inside the period yields two candidates —
        # each boundary is its own event a movement could line up with.
        if experiment.start_date is not None and period_start <= experiment.start_date <= now:
            candidates.append(_experiment_candidate(experiment, "launched", experiment.start_date))
        if experiment.end_date is not None and period_start <= experiment.end_date <= now:
            candidates.append(_experiment_candidate(experiment, "stopped", experiment.end_date))
    candidates.sort(key=lambda candidate: candidate.happened_at, reverse=True)
    return candidates[:MAX_CANDIDATES_PER_KIND]


def _experiment_candidate(experiment: Experiment, event: str, happened_at: datetime) -> CausalCandidate:
    return CausalCandidate(
        kind="experiment",
        ref=f"experiment:{experiment.id}",
        label=experiment.name[:LABEL_MAX_CHARS],
        happened_at=f"{happened_at:%Y-%m-%d}",
        detail=f"Experiment {event} on {happened_at:%Y-%m-%d}.",
    )


def _annotation_candidates(team: Team, period_start: datetime, now: datetime) -> list[CausalCandidate]:
    # Same rows the annotations source emits as context items — the shared query keeps visibility
    # semantics in one place; candidates re-shape them with the proximity semantics explain needs.
    # Extending the annotations product's get_annotations_for_ai_context is a recorded follow-up.
    return [
        CausalCandidate(
            kind="annotation",
            ref=f"annotation:{annotation.id}",
            label=annotation.content[:LABEL_MAX_CHARS],
            happened_at=f"{annotation.effective_date:%Y-%m-%d}",
            detail=f"Annotation {annotation_marker_summary(annotation)}.",
        )
        for annotation in annotations_in_period(team, period_start, now, MAX_CANDIDATES_PER_KIND)
    ]
