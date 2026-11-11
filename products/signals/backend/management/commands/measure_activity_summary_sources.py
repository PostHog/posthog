"""Measure the coverage and the signal of each activity summary input source. Writes no summary rows.

`--mode coverage` prints aggregate counts only. `--mode leave-one-out` calls the model and writes the
summaries to a local JSONL file, so it runs only for one organization that approved AI data processing.
"""

import json
import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models import Organization

from products.signals.backend.activity_summary.logic import MIN_UNITS
from products.signals.backend.activity_summary.measure import (
    candidate_pairs,
    coverage_report,
    leave_one_out_pair,
    leave_one_out_totals,
    measure_coverage,
    sample_pairs,
    scope_team_ids,
)
from products.signals.backend.activity_summary.render import WINDOW_DAYS

MODE_COVERAGE = "coverage"
MODE_LEAVE_ONE_OUT = "leave-one-out"
# Bounds the model calls of a leave-one-out run: up to three per pair.
DEFAULT_LEAVE_ONE_OUT_SAMPLE = 20


class Command(BaseCommand):
    help = "Measure how much the tasks and the activity log sources contribute to activity summaries."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=[MODE_COVERAGE, MODE_LEAVE_ONE_OUT], default=MODE_COVERAGE)
        parser.add_argument("--organization-id", type=str, help="Required for leave-one-out.")
        parser.add_argument("--team-id", type=int)
        parser.add_argument("--sample", type=int, help="Measure a random sample of this many pairs.")
        parser.add_argument("--seed", type=int, help="Seed of the pair sample, for a repeatable run.")
        parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
        parser.add_argument("--min-units", type=int, default=MIN_UNITS)
        parser.add_argument(
            "--output",
            type=Path,
            default=Path("activity_summary_leave_one_out.jsonl"),
            help="The local JSONL file of leave-one-out.",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        organization_id = options["organization_id"]
        if mode == MODE_LEAVE_ONE_OUT:
            if not organization_id:
                raise CommandError("leave-one-out sends real input to the model and needs --organization-id.")
            organization = Organization.objects.filter(id=organization_id).first()
            if organization is None or organization.is_ai_data_processing_approved is not True:
                raise CommandError("leave-one-out needs an organization that approved AI data processing.")

        now = timezone.now()
        start = now - datetime.timedelta(days=options["window_days"])
        team_ids = scope_team_ids(organization_id, options["team_id"])
        sample = options["sample"]
        if mode == MODE_LEAVE_ONE_OUT and sample is None:
            sample = DEFAULT_LEAVE_ONE_OUT_SAMPLE
        pairs = sample_pairs(candidate_pairs(team_ids, start, now), sample, options["seed"])
        self.stderr.write(f"teams: {len(team_ids)}, pairs: {len(pairs)}")

        if mode == MODE_COVERAGE:
            report = coverage_report(measure_coverage(pairs, start=start, now=now), min_units=options["min_units"])
            self.stdout.write(json.dumps(report.as_dict(), indent=2, sort_keys=True))
            return

        records = []
        with options["output"].open("w") as output:
            for pair in pairs:
                for record in leave_one_out_pair(pair, start=start, now=now, min_units=options["min_units"]):
                    output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    records.append(record)
        self.stderr.write(f"wrote {len(records)} records to {options['output']}")
        self.stdout.write(json.dumps(leave_one_out_totals(records), indent=2, sort_keys=True))
