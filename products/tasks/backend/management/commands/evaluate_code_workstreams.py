import json

from django.core.management.base import BaseCommand, CommandError

from posthog.models.scoping import team_scope

from products.tasks.backend.models import CodePrSnapshot, CodeWorkstream
from products.tasks.backend.temporal.code_workstreams.activities.list_active_teams import list_active_code_teams
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import (
    LoadTeamPrUrlsInput,
    load_team_pr_urls,
)
from products.tasks.backend.temporal.code_workstreams.activities.poll_pull_requests import (
    _resolve_integration,
    poll_pull_requests_for_team,
)
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import (
    RebuildTeamWorkstreamsInput,
    rebuild_team_workstreams,
)


class Command(BaseCommand):
    help = "Run one code-workstreams evaluation cycle synchronously (no Temporal worker/schedule). Diagnostic + local testing."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, help="Team to evaluate. Omit to list active teams and exit.")
        parser.add_argument(
            "--skip-poll", action="store_true", help="Skip the GitHub PR poll (grouping/classify only)."
        )
        parser.add_argument(
            "--pr-url",
            type=str,
            help="Probe a single PR: print exactly what get_pull_request_snapshot returns (needs --team-id).",
        )

    def handle(self, *args, **options):
        team_id = options.get("team_id")

        if team_id is None:
            active = list_active_code_teams()
            self.stdout.write(f"Active code teams (recent task activity): {active.team_ids}")
            self.stdout.write("Re-run with --team-id <id> to evaluate one.")
            return

        if options.get("pr_url"):
            self._probe_pr(team_id, options["pr_url"])
            return

        self.stdout.write(f"== Evaluating team {team_id} ==")

        prs = load_team_pr_urls(LoadTeamPrUrlsInput(team_id=team_id))
        self.stdout.write(f"PR URLs found on recent task runs: {len(prs.prs)}")
        for ref in prs.prs[:10]:
            self.stdout.write(f"  - {ref.pr_url} (integration={ref.github_integration_id})")

        if options["skip_poll"]:
            self.stdout.write("Skipping GitHub poll (--skip-poll).")
        elif prs.prs:
            try:
                result = poll_pull_requests_for_team(team_id, prs.prs)
                self.stdout.write(
                    f"Polled {result.polled}, updated {result.updated}, rate_limited={result.rate_limited}"
                )
            except Exception as e:
                raise CommandError(f"PR poll failed: {type(e).__name__}: {e}") from e

        out = rebuild_team_workstreams(RebuildTeamWorkstreamsInput(team_id=team_id))
        self.stdout.write(f"Rebuilt: users={out.users}, workstreams={out.workstreams}, pruned={out.pruned}")

        with team_scope(team_id):
            snapshots = list(CodePrSnapshot.objects.filter(team_id=team_id))
            workstreams = list(CodeWorkstream.objects.filter(team_id=team_id))

        self.stdout.write(f"\nCodePrSnapshot rows: {len(snapshots)}")
        for s in snapshots[:25]:
            self.stdout.write(
                f"  {s.pr_url} state={s.state} ci={s.ci_status} review={s.review_decision} "
                f"threads={s.unresolved_threads} author={s.author_login}"
            )

        self.stdout.write(f"\nCodeWorkstream rows: {len(workstreams)}")
        for ws in workstreams[:25]:
            self.stdout.write(
                f"  [{ws.state}] {ws.key} → situations={ws.situations} (user={ws.user_id}, tasks={len(ws.tasks)})"
            )

        if not workstreams:
            self.stdout.write(
                "\nNo workstreams written. Likely causes: tasks have no PR URL and no (repository + run branch) "
                "grouping key, all of the team's recent tasks are still actively-running agents, or there are no "
                "task runs in the last 30 days for this team."
            )
        elif snapshots and all(
            s.ci_status == "none" and s.review_decision is None and s.unresolved_threads == 0 for s in snapshots
        ):
            self.stdout.write(
                "\nAll PR snapshots are empty (ci=none, no review, 0 threads). The GitHub poll reached GitHub but "
                "the data came back blank — likely the GitHub App installation lacks 'Checks: read' / 'Pull "
                "requests: read'. Run with --pr-url <one of the URLs above> to see the raw result + any GraphQL errors."
            )

    def _probe_pr(self, team_id: int, pr_url: str) -> None:
        prs = load_team_pr_urls(LoadTeamPrUrlsInput(team_id=team_id))
        ref = next((r for r in prs.prs if r.pr_url == pr_url), None)
        if ref is None:
            raise CommandError(
                f"{pr_url} is not among the team's recent task-run PR URLs ({len(prs.prs)} found). "
                "Is there a task run with output.pr_url == this URL in the last 30 days?"
            )
        self.stdout.write(
            f"Resolved PrRef: team_integration={ref.github_integration_id}, user_integration={ref.github_user_integration_id}"
        )
        integration = _resolve_integration(ref)
        if integration is None:
            raise CommandError(
                "No GitHub integration resolved for this PR: the task isn't linked to one, the team has no GitHub "
                "integration, and the task creator has no user GitHub integration. Connect GitHub (team or user)."
            )
        self.stdout.write(f"Resolved integration: {type(integration).__name__}")
        try:
            snapshot = integration.get_pull_request_snapshot(pr_url)
        except Exception as e:
            raise CommandError(f"get_pull_request_snapshot raised: {type(e).__name__}: {e}") from e
        self.stdout.write(json.dumps(snapshot, indent=2, default=str))
