"""Measure what `experiment-setup-context` can actually tell an agent, across many projects.

Two numbers decide whether a section earns its tokens: how often it comes back `ok`, and how often
it carries a fact a rule branches on. A section that answers for every project but decides nothing
is as useless as one that times out. `SetupContextScorecard` reports both, so a later iteration can
compare the same two quantities instead of writing production SQL again.

Two more quantities belong to the same measurement and cannot live here:

- Precedent deviation by creation source. For experiments created in a project that already has at
  least five, how often the new one differs from that project's strong majority on persistence,
  bucketing, custom exposure, test-account filter, shared-metric reuse and primary metric type.
  It needs the creation source, which only the production event stream carries, so it is run as
  read-only production SQL. That comparison runs over a different set of projects for each source,
  so it cannot separate "agents configure worse" from "different projects use agents". Treat it as
  a signal to investigate, never as a verdict on a creation path, until a within-project version
  exists that reads only projects creating through both an agent and the UI.
- Launched experiments with zero, and with under 100, analyzed exposures four days after launch.
  This is the harm measure, and `PreviousExperimentsSummary` already counts both over a project's
  listed experiments.

The output carries ids, counts and booleans only. No experiment name, metric name or other
user-authored string reaches it, so a scorecard is safe to paste into an internal discussion.
"""

import logging
import dataclasses
from collections.abc import Iterable, Sequence
from statistics import median

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
)

logger = logging.getLogger(__name__)

SECTION_NAMES: tuple[str, ...] = (
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
IDENTITY_BAND = (0.1, 0.9)
# "Near 1" in the device-id bucketing step.
DEVICE_ID_SHARE_FLOOR = 0.95


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
    server_lib_evaluates_locally: bool
    previous_experiment_count: int
    shared_metric_count: int


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
class SetupContextScorecard:
    teams: int
    failed_teams: int
    sections: list[SectionScore]
    # Fact name to the number of teams it held for. An int fact counts the teams above zero.
    fact_coverage: dict[str, int]
    readings: list[TeamReading]


class SetupContextProbe:
    """Build the setup context for many projects and score what came back."""

    def __init__(self, *, target_event: str | None = None, metric_event: str | None = None) -> None:
        self.inputs = SetupContextInputs(target_event=target_event, metric_event=metric_event)

    def run(self, teams: Sequence[Team]) -> SetupContextScorecard:
        readings = [self.read_team(team) for team in teams]
        return self.score(readings)

    def read_team(self, team: Team) -> TeamReading:
        sections: dict[str, SectionReading] = {}

        def observe(name: str, status: SetupContextSectionStatus, duration_ms: float) -> None:
            sections[name] = SectionReading(status=status, duration_ms=duration_ms)

        try:
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
        device_id_shares = [
            *(lib.device_id_share for lib in (sdk_profile.libs if sdk_profile else [])),
            *(lib.device_id_share for lib in (target_surface.libs if target_surface else [])),
        ]
        return DecisiveFacts(
            sdk_libs_empty=sdk_profile is not None and not sdk_profile.libs,
            libs_on_any_event_used=bool(sdk_profile and sdk_profile.libs_on_any_event),
            anonymous_share_null=target_surface is not None and anonymous_share is None,
            anonymous_share_crosses_identification=(
                anonymous_share is not None and IDENTITY_BAND[0] <= anonymous_share <= IDENTITY_BAND[1]
            ),
            device_id_bucketing_plausible=any(share > DEVICE_ID_SHARE_FLOOR for share in device_id_shares),
            server_lib_evaluates_locally=bool(
                sdk_profile
                and any(
                    lib.category == SdkLibCategory.SERVER and lib.locally_evaluated_share is not None
                    for lib in sdk_profile.libs
                )
            ),
            previous_experiment_count=len(previous.experiments) if previous else 0,
            shared_metric_count=len(shared.metrics) if shared else 0,
        )

    def score(self, readings: Sequence[TeamReading]) -> SetupContextScorecard:
        read = [reading for reading in readings if not reading.failed]
        return SetupContextScorecard(
            teams=len(readings),
            failed_teams=len(readings) - len(read),
            sections=[self.score_section(name, read) for name in SECTION_NAMES],
            fact_coverage=self.count_facts(read),
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

    @staticmethod
    def percentile(sorted_values: Sequence[float], share: float) -> float | None:
        if not sorted_values:
            return None
        # Nearest-rank, so a handful of projects still gives an honest tail rather than an average.
        index = min(len(sorted_values) - 1, int(round(share * (len(sorted_values) - 1))))
        return sorted_values[index]

    @staticmethod
    def count_facts(readings: Sequence[TeamReading]) -> dict[str, int]:
        facts = [reading.facts for reading in readings if reading.facts is not None]
        if not facts:
            return {}
        return {
            field.name: sum(1 for fact in facts if bool(getattr(fact, field.name)))
            for field in dataclasses.fields(DecisiveFacts)
        }


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
