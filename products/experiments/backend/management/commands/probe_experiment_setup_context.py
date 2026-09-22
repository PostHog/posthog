"""Score what `experiment-setup-context` tells an agent, over many projects at once.

Calls the providers in process, so neither the feature flag nor authentication applies.

Latency is only meaningful on a cold read. Three sections cache for an hour or more, keyed by team
and inputs, so a second run over the same projects measures the cache. Pass `--cold` to drop those
keys before each project.

    python manage.py probe_experiment_setup_context --limit 25 --target-event '$pageview' --cold

Precedent deviation by creation source needs the creation source, which only the production event
stream carries, so it is not measured here. That comparison runs over a different set of projects
for each source, so it cannot separate "agents configure worse" from "different projects use
agents". Do not read it as a verdict on a creation path until a within-project version exists.

The output carries ids, counts and booleans only, so a scorecard is safe to paste into an internal
discussion. `--per-team` adds one row per project, which is how a single slow project is found.
"""

import json
import dataclasses
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.experiments.backend.setup_context_probe import (
    SECTION_NAMES,
    DecisiveFacts,
    SetupContextProbe,
    SetupContextScorecard,
    teams_by_id,
    teams_with_recent_experiments,
)


class Command(BaseCommand):
    help = "Score the experiment setup context across projects"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            action="append",
            dest="team_ids",
            help="Probe this team only; repeatable. Without it, --limit picks teams by recent experiment.",
        )
        parser.add_argument(
            "--limit", type=int, default=10, help="How many teams with recent experiments to probe (default 10)"
        )
        parser.add_argument(
            "--target-event", help="Target event, so target_surface and the metric baseline run instead of skipping"
        )
        parser.add_argument("--metric-event", help="Metric event, so candidate_metric and the event match run")
        parser.add_argument(
            "--cold",
            action="store_true",
            help="Drop the cached sections before each team, so the latency is a real read",
        )
        parser.add_argument("--per-team", action="store_true", help="Also print one row per team")
        parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON instead of TSV")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["limit"] < 1:
            raise CommandError("--limit must be at least 1")
        teams = (
            teams_by_id(options["team_ids"]) if options["team_ids"] else teams_with_recent_experiments(options["limit"])
        )
        if not teams:
            raise CommandError("No teams to probe")

        probe = SetupContextProbe(
            target_event=options["target_event"],
            metric_event=options["metric_event"],
            cold=options["cold"],
        )
        scorecard = probe.run(teams)

        if options["as_json"]:
            self.print_json(scorecard, per_team=options["per_team"])
        else:
            self.print_tsv(scorecard, per_team=options["per_team"])

    def print_json(self, scorecard: SetupContextScorecard, *, per_team: bool) -> None:
        payload = dataclasses.asdict(scorecard)
        if not per_team:
            payload.pop("readings")
        self.stdout.write(json.dumps(payload, default=str))

    def print_tsv(self, scorecard: SetupContextScorecard, *, per_team: bool) -> None:
        self.stdout.write(
            f"teams\t{scorecard.teams}\tunreadable\t{scorecard.failed_teams}"
            f"\tlatency\t{'cold' if scorecard.cold else 'cached, not comparable'}"
        )

        self.stdout.write("\nsection\tok\tteams\tp50_ms\tp95_ms")
        for section in scorecard.sections:
            self.stdout.write(
                f"{section.name}\t{section.ok}\t{section.teams}"
                f"\t{self.milliseconds(section.p50_ms)}\t{self.milliseconds(section.p95_ms)}"
            )

        self.stdout.write("\nfact\tpresent\tmeasured")
        for fact in scorecard.facts:
            self.stdout.write(f"{fact.name}\t{fact.present}\t{fact.measured}")

        if not per_team:
            return
        self.stdout.write("\nteam_id\t" + "\t".join([*SECTION_NAMES, *self.fact_names()]))
        for reading in scorecard.readings:
            statuses = [
                reading.sections[name].status if name in reading.sections else "unread" for name in SECTION_NAMES
            ]
            facts = (
                [getattr(reading.facts, name) for name in self.fact_names()]
                if reading.facts is not None
                else ["unread"] * len(self.fact_names())
            )
            self.stdout.write(f"{reading.team_id}\t" + "\t".join(str(value) for value in [*statuses, *facts]))

    @staticmethod
    def fact_names() -> list[str]:
        return [field.name for field in dataclasses.fields(DecisiveFacts)]

    @staticmethod
    def milliseconds(value: float | None) -> str:
        return "-" if value is None else f"{value:.0f}"
