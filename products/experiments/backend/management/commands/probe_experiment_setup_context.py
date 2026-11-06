"""Read every section of `experiment-setup-context` back for a project, from a shell.

A local tool with two jobs. It confirms that a seeded project reports the shape it was seeded with,
and it checks that every section still answers after `setup_context.py` changes.

    CLICKHOUSE_DATABASE=posthog python manage.py probe_experiment_setup_context \\
        --team-id 1 --target-event '$pageview' --metric-event '<event>' --cold

`CLICKHOUSE_DATABASE=posthog` is not optional. The setting defaults to `default`, and the real
value lives in `.env.services`, which a plain shell does not load.

It answers a narrow question: did the section answer, and was the fact there to read. It does not
measure whether the setup context helps an agent configure an experiment correctly, which needs an
eval that scores the created experiment across two arms. A coverage number over a whole region is
cheaper to get from one cross-team query than from this per-team loop, so this is not the way to
measure a fleet.

Calls the providers in process, so neither the feature flag nor authentication applies. It also
skips the access-control filtering the endpoint applies to the experiment and saved-metric
querysets, so the two list counts are upper bounds rather than what a scoped agent sees.

Latency is only meaningful on a cold read. Three sections cache for an hour or more, keyed by team
and inputs, so a second run over the same project measures the cache. `--cold` drops those keys,
which is the only write this command makes.

Without `--team-id`, `--limit` picks the projects that ran an experiment most recently, across the
whole instance and with no organization scoping.

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
