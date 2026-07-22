from django.core.management.base import BaseCommand

from products.tasks.backend.models import TaskArtifact, TaskRun


class Command(BaseCommand):
    help = (
        "Backfill TaskArtifact github_pr registry rows from historical TaskRun.output.pr_url "
        "values. Dry run by default; pass --live to write."
    )

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true", help="Write rows (default is a dry run)")
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to a single team")

    def handle(self, *args, **options):
        from products.tasks.backend.logic.services.living_artifacts import record_github_pr_artifact

        live: bool = options["live"]
        team_id: int | None = options["team_id"]

        runs = (
            TaskRun.objects.filter(output__pr_url__isnull=False, task__deleted=False)
            .select_related("task")
            .order_by("created_at")
        )
        if team_id is not None:
            runs = runs.filter(team_id=team_id)

        # One plan per (task, url) — the artifact's unique key, so each task that touched
        # a PR keeps its own provenance row. Runs are ordered oldest first, so the first
        # run seen is the row's creator (provenance + created_at) and the last one seen
        # supplies updated_at; a merge flag on any of the task's runs wins.
        plans: dict[tuple, dict] = {}
        for run in runs.iterator(chunk_size=500):
            output = run.output if isinstance(run.output, dict) else {}
            pr_url = output.get("pr_url")
            if not isinstance(pr_url, str) or not pr_url:
                continue
            plan = plans.setdefault((run.task_id, pr_url), {"first": run, "last": run, "merged": False})
            plan["last"] = run
            plan["merged"] = plan["merged"] or bool(output.get("pr_merged"))

        # A merge recorded on any task's run counts for every task touching that PR —
        # pooled up front so plan ordering can't create a sibling row as "open" after
        # the merged row's fan-out already ran.
        merged_urls = {(plan["first"].team_id, url) for (_, url), plan in plans.items() if plan["merged"]}

        created = skipped = failed = 0
        for (plan_task_id, pr_url), plan in plans.items():
            exists = (
                TaskArtifact.objects.for_team(plan["first"].team_id)
                .filter(task_id=plan_task_id, artifact_type=TaskArtifact.ArtifactType.GITHUB_PR, location__url=pr_url)
                .exists()
            )
            if exists:
                skipped += 1
                continue
            if not live:
                created += 1
                continue
            first_run, last_run = plan["first"], plan["last"]
            state = "merged" if (first_run.team_id, pr_url) in merged_urls else "open"
            artifact = record_github_pr_artifact(first_run, pr_url, state=state)
            if artifact is None:
                failed += 1
                continue
            # Real chronology instead of auto_now, else every backfilled PR lands at the
            # top of its channel's most-recently-updated artifact list at once.
            TaskArtifact.objects.for_team(first_run.team_id).filter(pk=artifact.pk).update(
                created_at=first_run.created_at, updated_at=last_run.updated_at or first_run.created_at
            )
            created += 1

        mode = "created" if live else "would create (dry run; pass --live to write)"
        self.stdout.write(f"{created} {mode}, {skipped} already exist, {failed} failed")
