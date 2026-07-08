"""Local dev tool: seed *billable* Signals reports for exercising the PR refund flow.

`seed_inbox_data` gives the inbox rich-looking reports; this command gives it billable ones —
reports whose implementation run carries a GitHub PR URL plus the `SignalReportTask` bridge row
the billing query is rooted on, with run timestamps chosen to reach each refund path.

Creates four reports per invocation (a report can only ever be refunded once, so re-run freely):

1. PR run today             → refund takes the `excluded` path (usage query skips the report)
2. PR run yesterday         → refund takes the `credited` path (Celery → billing dispute endpoint)
3. billing-exempt, with PR  → "Free" badge in the inbox; refund returns 400
4. no PR run yet            → valid target for `manage.py exempt_signal_report_billing`

The refund endpoints are gated on the `signals-pr-refunds` feature flag; the full local setup
(flag, local billing service, verification queries) is in the "Testing refunds locally" section
of products/signals/ARCHITECTURE.md.

DEBUG only.

    python manage.py seed_refund_test_data --team-id 1
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from posthog.models import OrganizationMembership, Team

from products.signals.backend.billing import first_billable_pr_run
from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.facade import api as tasks_facade

_DEFAULT_REPOSITORY = "posthog/posthog"


class Command(BaseCommand):
    help = "Seed billable Signals reports covering every refund/exemption path (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed reports for")
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="User to attribute tasks to (default: first member of the team's organization)",
        )
        parser.add_argument(
            "--repository",
            type=str,
            default=_DEFAULT_REPOSITORY,
            help=f"owner/repo used in the seeded PR URLs (default: {_DEFAULT_REPOSITORY})",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        team = self._get_team(options["team_id"])
        user_id = self._resolve_user_id(team, options["user_id"])
        repository = options["repository"]
        now = timezone.now()
        stamp = now.strftime("%m%d-%H%M%S")
        # PR numbers only need to look distinct in the UI; derive from the clock.
        pr_base = int(now.timestamp()) % 900_000

        excluded = self._seed_billable_report(
            team,
            user_id,
            title=f"[{stamp}] Refund test: excluded path (PR today)",
            repository=repository,
            pr_number=pr_base + 1,
        )
        credited = self._seed_billable_report(
            team,
            user_id,
            title=f"[{stamp}] Refund test: credited path (PR yesterday)",
            repository=repository,
            pr_number=pr_base + 2,
            run_created_at=now - timedelta(days=1),
        )
        exempt = self._seed_billable_report(
            team,
            user_id,
            title=f"[{stamp}] Refund test: billing-exempt (Free badge)",
            repository=repository,
            pr_number=pr_base + 3,
            exempt_reason=SignalReport.BillingExemptReason.POSTHOG_SYSTEM,
        )
        no_pr = self._make_report(team, title=f"[{stamp}] Refund test: no PR yet (exemption target)")

        self.stdout.write(f"1. excluded-path report: {excluded.id}")
        self.stdout.write(f"2. credited-path report: {credited.id}")
        self.stdout.write(f"3. exempt report:        {exempt.id}")
        self.stdout.write(f"4. no-PR report:         {no_pr.id}")
        self.stdout.write(f"   try: python manage.py exempt_signal_report_billing {team.id} {no_pr.id} posthog_system")
        self.stdout.write(
            self.style.SUCCESS(f"Seeded 4 refund-test reports for team {team.id} — open the inbox's Ready list.")
        )

    def _seed_billable_report(
        self,
        team: Team,
        user_id: int,
        *,
        title: str,
        repository: str,
        pr_number: int,
        run_created_at: datetime | None = None,
        exempt_reason: str | None = None,
    ) -> SignalReport:
        report = self._make_report(team, title=title)
        created = tasks_facade.create_and_run_task(
            team=team,
            title=f"impl: {title}",
            description="Synthetic implementation task seeded for refund testing.",
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            user_id=user_id,
            repository=repository,
            create_pr=False,
            start_workflow=False,
            signal_report_id=str(report.id),
            internal=False,
        )
        run = created.latest_run
        if run is None:
            raise CommandError(f"Task creation for report {report.id} produced no run")
        task_id, run_id = str(created.task_id), str(run.id)

        # Production ordering: the bridge row (and any exemption) is recorded when the task starts,
        # before the run can ship a billable PR — the exemption freeze rule depends on this.
        with transaction.atomic():
            record_implementation_task(
                team_id=team.id,
                report_id=str(report.id),
                task_id=task_id,
                run_id=run_id,
                billing_exempt_reason=exempt_reason,
            )
        tasks_facade.update_task_run(
            run_id,
            task_id,
            team.id,
            validated_data={
                "status": "completed",
                "output": {"pr_url": f"https://github.com/{repository}/pull/{pr_number}"},
            },
        )
        if run_created_at is not None:
            tasks_facade.set_task_run_created_at_for_seeding(run_id, task_id, team.id, created_at=run_created_at)

        billable = first_billable_pr_run(report.id)
        if billable is None:
            raise CommandError(f"Report {report.id} is not billable after seeding — bridge/run wiring broke")
        self.stdout.write(f"  · billable at {billable.created_at.isoformat()} ({billable.pr_url})")
        return report

    def _make_report(self, team: Team, *, title: str) -> SignalReport:
        return SignalReport.objects.create(
            team=team,
            status=SignalReport.Status.READY,
            signal_count=1,
            total_weight=1.0,
            title=title,
            summary="Seeded by seed_refund_test_data for refund-flow testing.",
        )

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.select_related("organization").get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

    def _resolve_user_id(self, team: Team, user_id: int | None) -> int:
        if user_id is not None:
            return user_id
        membership = (
            OrganizationMembership.objects.filter(organization_id=team.organization_id)
            .order_by("joined_at")
            .values_list("user_id", flat=True)
            .first()
        )
        if membership is None:
            raise CommandError(f"Team {team.id}'s organization has no members; pass --user-id explicitly")
        return membership
