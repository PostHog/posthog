"""Local dev tool: bulk-seed a large volume of synthetic `SignalReport`s for query
performance testing of the reports list/sort/filter paths.

Unlike `seed_inbox_data` (which runs each report through the async agentic persist path to
produce realistic content), this command does straight `bulk_create`s — no LLM-shaped content,
no task runs — so it can drop tens of thousands of reports in seconds. The reports are uniform
by design: an even spread of priorities (P0–P4), a 50/50 actionable split, and trivial titles
(`perf-testing-report-N`). The point is volume, not realism — enough rows to exercise the
priority/actionability subqueries the inbox list builds (see `SignalReportViewSet`).

Each report gets a small, fixed set of artefacts mirroring a researched report's status log:
safety / priority / actionability judgments, a repo selection, suggested reviewers, and a signal
finding — the artefact types the list endpoint's correlated subqueries scan.

DEBUG only.

    python manage.py seed_perf_reports --team-id 1
    python manage.py seed_perf_reports --team-id 1 --count 50000 --clear
    python manage.py seed_perf_reports --team-id 1 --count 50000 --batch-size 5000
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact

_PRIORITIES = ["P0", "P1", "P2", "P3", "P4"]
# Ready-heavy: `ready` is the state users actually triage and the one the priority sort is run
# against most, so it dominates. The rest give the status filters something to bite on.
_STATUS_CYCLE = [
    SignalReport.Status.READY,
    SignalReport.Status.READY,
    SignalReport.Status.READY,
    SignalReport.Status.POTENTIAL,
    SignalReport.Status.CANDIDATE,
    SignalReport.Status.PENDING_INPUT,
    SignalReport.Status.RESOLVED,
]
_REPOSITORY = "posthog/posthog"


class Command(BaseCommand):
    help = "Bulk-seed synthetic signal reports + artefacts for query perf testing (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed reports for")
        parser.add_argument("--count", type=int, default=50_000, help="How many reports to create (default: 50000)")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete the team's existing signal reports (and their artefacts) before seeding",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5_000,
            help="Reports created per bulk_create chunk (default: 5000). Lower it if memory is tight.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        team = self._get_team(options["team_id"])
        count: int = options["count"]
        batch_size: int = options["batch_size"]

        if options["clear"]:
            self._clear_existing(team)

        created = 0
        artefacts_created = 0
        for start in range(0, count, batch_size):
            chunk = range(start, min(start + batch_size, count))
            reports = [self._build_report(team.id, i) for i in chunk]
            SignalReport.objects.bulk_create(reports, batch_size=batch_size)

            artefacts: list[SignalReportArtefact] = []
            for offset, report in enumerate(reports):
                artefacts.extend(self._build_artefacts(team.id, report, chunk.start + offset))
            SignalReportArtefact.objects.bulk_create(artefacts, batch_size=batch_size)

            created += len(reports)
            artefacts_created += len(artefacts)
            self.stdout.write(f"  · {created:>7}/{count} reports ({artefacts_created} artefacts)")

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} report(s) and {artefacts_created} artefact(s) for team {team.id} ({team.name})."
            )
        )

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

    def _clear_existing(self, team: Team) -> None:
        # Artefacts cascade on the report FK, so deleting reports clears them too.
        deleted, _ = SignalReport.objects.filter(team=team).delete()
        self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing signal report row(s) for team {team.id}"))

    def _build_report(self, team_id: int, index: int) -> SignalReport:
        signal_count = 1 + (index % 5)
        return SignalReport(
            team_id=team_id,
            status=_STATUS_CYCLE[index % len(_STATUS_CYCLE)],
            signal_count=signal_count,
            total_weight=float(signal_count),
            title=f"perf-testing-report-{index}",
            summary=f"Synthetic report {index} seeded for query performance testing.",
        )

    def _build_artefacts(self, team_id: int, report: SignalReport, index: int) -> list[SignalReportArtefact]:
        priority = _PRIORITIES[index % len(_PRIORITIES)]
        actionability = "immediately_actionable" if index % 2 == 0 else "not_actionable"

        contents: list[tuple[str, dict | list]] = [
            (SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT, {"choice": True, "explanation": ""}),
            (
                SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
                {
                    "signal_id": str(report.id),
                    "relevant_code_paths": ["products/signals/backend/views.py"],
                    "relevant_commit_hashes": {},
                    "data_queried": "",
                    "verified": True,
                },
            ),
            (
                SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                {"explanation": "Synthetic perf-test priority.", "priority": priority, "dollar_value": 1000.0},
            ),
            (
                SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                {
                    "explanation": "Synthetic perf-test actionability.",
                    "actionability": actionability,
                    "already_addressed": False,
                },
            ),
            (
                SignalReportArtefact.ArtefactType.REPO_SELECTION,
                {"repository": _REPOSITORY, "reason": "Synthetic perf-test repo selection."},
            ),
            (
                SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                [{"github_login": "perfbot", "github_name": "Perf Bot", "relevant_commits": []}],
            ),
        ]
        return [
            SignalReportArtefact(
                team_id=team_id,
                report_id=report.id,
                type=artefact_type,
                content=json.dumps(content),
            )
            for artefact_type, content in contents
        ]
