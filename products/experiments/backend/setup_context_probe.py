"""Measure what `experiment-setup-context` can actually tell an agent, across many projects.

Two numbers decide whether a section earns its tokens: how often it comes back `ok`, and how often
it carries a fact a rule branches on. A section that answers for every project but decides nothing
costs as much as one that times out.

Every fact reports a denominator as well as a count, because a fact whose section did not run is
unmeasured rather than absent. "0 of 25 projects cross identification" and "0 of 0" are different
answers, and only the second one means nothing was read.
"""

import logging
import dataclasses
from collections.abc import Iterable, Sequence
from math import ceil
from statistics import median
from typing import Final

from django.db.models import Max

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric
from products.experiments.backend.setup_context import (
    ExperimentSetupContext,
    PreviousExperiments,
    SdkLibCategory,
    SdkProfile,
    SetupContextInputs,
    SetupContextSectionStatus,
    SharedMetrics,
    TargetSurface,
    build_setup_context,
    clear_cached_sections,
)

logger = logging.getLogger(__name__)

SECTION_NAMES: Final[tuple[str, ...]] = (
    "team_defaults",
    "sdk_profile",
    "target_surface",
    "candidate_metric",
    "previous_experiments",
    "shared_metrics",
)

# The band where a surface crosses identification, which is the one place the bucketing rules ask
# for more than the user id. Kept in step with "Bucketing and persistence" in
# products/experiments/skills/creating-experiments/references/setup-decisions.md.
IDENTITY_BAND: Final[tuple[float, float]] = (0.1, 0.9)
# "Near 1" in the device-id bucketing step.
DEVICE_ID_SHARE_FLOOR: Final = 0.95


@frozen
class SectionReading:
    status: SetupContextSectionStatus
    # None for a section that never ran, which is every skipped section.
    duration_ms: float | None


@frozen
class DecisiveFacts:
    """Whether each fact a bucketing or precedent rule branches on was there to read."""

    sdk_libs_empty: bool
    libs_on_any_event_used: bool
    anonymous_share_null: bool
    anonymous_share_crosses_identification: bool
    device_id_bucketing_plausible: bool
    server_lib_reports_local_evaluation: bool
    previous_experiments_listed: int
    shared_metrics_listed: int


FACT_SECTIONS: Final[dict[str, tuple[str, ...]]] = {
    "sdk_libs_empty": ("sdk_profile",),
    "libs_on_any_event_used": ("sdk_profile",),
    "anonymous_share_null": ("target_surface",),
    "anonymous_share_crosses_identification": ("target_surface",),
    "device_id_bucketing_plausible": ("sdk_profile", "target_surface"),
    "server_lib_reports_local_evaluation": ("sdk_profile",),
    "previous_experiments_listed": ("previous_experiments",),
    "shared_metrics_listed": ("shared_metrics",),
}


@frozen
class TeamReading:
    team_id: int
    sections: dict[str, SectionReading]
    facts: DecisiveFacts | None
    failed: bool


@frozen
class SectionScore:
    name: str
    teams: int
    ok: int
    p50_ms: float | None
    p95_ms: float | None


@frozen
class FactCoverage:
    name: str
    present: int
    measured: int


@frozen
class SetupContextScorecard:
    teams: int
    failed_teams: int
    cold: bool
    sections: list[SectionScore]
    facts: list[FactCoverage]
    readings: list[TeamReading]


class SetupContextProbe:
    """Build the setup context for many projects and score what came back."""

    def __init__(
        self,
        *,
        target_event: str | None = None,
        metric_event: str | None = None,
        cold: bool = False,
    ) -> None:
        self.inputs = SetupContextInputs(target_event=target_event, metric_event=metric_event)
        self.cold = cold

    def run(self, teams: Sequence[Team]) -> SetupContextScorecard:
        return self.score([self.read_team(team) for team in teams])

    def read_team(self, team: Team) -> TeamReading:
        sections: dict[str, SectionReading] = {}

        def observe(name: str, status: SetupContextSectionStatus, duration_ms: float) -> None:
            sections[name] = SectionReading(status=status, duration_ms=duration_ms)

        try:
            if self.cold:
                clear_cached_sections(team, self.inputs)
            context = build_setup_context(
                team=team,
                inputs=self.inputs,
                experiments=Experiment.objects.filter(team_id=team.pk),
                saved_metrics=ExperimentSavedMetric.objects.filter(team_id=team.pk),
                on_section=observe,
            )
        except Exception:
            # One project that cannot be read must not end a sweep over hundreds.
            logger.exception("experiment_setup_context_probe_failed", extra={"team_id": team.pk})
            return TeamReading(team_id=team.pk, sections={}, facts=None, failed=True)

        for name in SECTION_NAMES:
            if name not in sections:
                sections[name] = SectionReading(status=getattr(context, name).status, duration_ms=None)
        return TeamReading(team_id=team.pk, sections=sections, facts=self.decisive_facts(context), failed=False)

    def decisive_facts(self, context: ExperimentSetupContext) -> DecisiveFacts:
        sdk_profile: SdkProfile | None = context.sdk_profile.data
        target_surface: TargetSurface | None = context.target_surface.data
        previous: PreviousExperiments | None = context.previous_experiments.data
        shared: SharedMetrics | None = context.shared_metrics.data

        anonymous_share = target_surface.anonymous_share if target_surface else None
        return DecisiveFacts(
            sdk_libs_empty=sdk_profile is not None and not sdk_profile.libs,
            libs_on_any_event_used=bool(sdk_profile and sdk_profile.libs_on_any_event),
            anonymous_share_null=target_surface is not None and anonymous_share is None,
            anonymous_share_crosses_identification=(
                anonymous_share is not None and IDENTITY_BAND[0] <= anonymous_share <= IDENTITY_BAND[1]
            ),
            device_id_bucketing_plausible=self.device_id_bucketing_plausible(sdk_profile, target_surface),
            server_lib_reports_local_evaluation=bool(
                sdk_profile
                and any(
                    lib.category == SdkLibCategory.SERVER and lib.locally_evaluated_share is not None
                    for lib in sdk_profile.libs
                )
            ),
            previous_experiments_listed=len(previous.experiments) if previous else 0,
            shared_metrics_listed=len(shared.metrics) if shared else 0,
        )

    @staticmethod
    def device_id_bucketing_plausible(sdk_profile: SdkProfile | None, target_surface: TargetSurface | None) -> bool:
        """Step 1 of the bucketing rules, read exactly as that step reads it.

        The surface's own share has to be near 1, at least one profiled SDK has to be one that
        reached the surface, and every such SDK has to be near 1 on its flag calls. An `any()` over
        the two lists merged would pass on one high row from an SDK the surface never sees.
        """
        if sdk_profile is None or target_surface is None:
            return False
        if target_surface.device_id_share is None or target_surface.device_id_share <= DEVICE_ID_SHARE_FLOOR:
            return False
        surface_libs = {lib.lib for lib in target_surface.libs}
        matching = [lib for lib in sdk_profile.libs if lib.lib in surface_libs]
        return bool(matching) and all(lib.device_id_share > DEVICE_ID_SHARE_FLOOR for lib in matching)

    def score(self, readings: Sequence[TeamReading]) -> SetupContextScorecard:
        read = [reading for reading in readings if not reading.failed]
        return SetupContextScorecard(
            teams=len(readings),
            failed_teams=len(readings) - len(read),
            cold=self.cold,
            sections=[self.score_section(name, read) for name in SECTION_NAMES],
            facts=[self.score_fact(field.name, read) for field in dataclasses.fields(DecisiveFacts)],
            readings=list(readings),
        )

    def score_section(self, name: str, readings: Sequence[TeamReading]) -> SectionScore:
        present = [reading.sections[name] for reading in readings if name in reading.sections]
        durations = sorted(section.duration_ms for section in present if section.duration_ms is not None)
        return SectionScore(
            name=name,
            teams=len(present),
            ok=sum(1 for section in present if section.status == SetupContextSectionStatus.OK),
            p50_ms=median(durations) if durations else None,
            p95_ms=self.percentile(durations, 0.95),
        )

    def score_fact(self, name: str, readings: Sequence[TeamReading]) -> FactCoverage:
        measured = [reading for reading in readings if reading.facts is not None and self.fact_measured(reading, name)]
        return FactCoverage(
            name=name,
            present=sum(1 for reading in measured if bool(getattr(reading.facts, name))),
            measured=len(measured),
        )

    @staticmethod
    def fact_measured(reading: TeamReading, name: str) -> bool:
        return all(
            section in reading.sections and reading.sections[section].status == SetupContextSectionStatus.OK
            for section in FACT_SECTIONS[name]
        )

    @staticmethod
    def percentile(sorted_values: Sequence[float], share: float) -> float | None:
        if not sorted_values:
            return None
        # Nearest-rank, so a handful of projects still gives an honest tail rather than an average.
        index = min(len(sorted_values) - 1, max(0, ceil(share * len(sorted_values)) - 1))
        return sorted_values[index]


def teams_with_recent_experiments(limit: int) -> list[Team]:
    """Projects that ran an experiment most recently, which are the ones a rule change reaches."""
    team_ids = list(
        Experiment.objects.exclude(deleted=True)
        .values("team_id")
        .annotate(last_experiment_at=Max("created_at"))
        .order_by("-last_experiment_at")
        .values_list("team_id", flat=True)[:limit]
    )
    by_id = {team.pk: team for team in Team.objects.filter(pk__in=team_ids)}
    return [by_id[team_id] for team_id in team_ids if team_id in by_id]


def teams_by_id(team_ids: Iterable[int]) -> list[Team]:
    return list(Team.objects.filter(pk__in=list(team_ids)))
