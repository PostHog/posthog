"""Open a "tidy up the experiment's feature flag" draft PR for one experiment, by hand.

Given an experiment and the repository its flag lives in, this builds a cleanup prompt from
the experiment's outcome and feature-flag variants (see ``flag_cleanup``), then hands it to
the Tasks engine, which runs a coding agent in a sandbox and opens a draft pull request that
removes the flag scaffolding.

This is the manual entry point; the automatic experiment-end trigger and UI come later. Use
``--dry-run`` first to read the exact prompt before spending a sandbox run.

    python manage.py open_experiment_cleanup_pr 123 --repository posthog/posthog --dry-run
    python manage.py open_experiment_cleanup_pr 123 --repository posthog/posthog --branch master
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models import User

from products.experiments.backend.flag_cleanup import CONCLUSION_LABELS, CleanupPlan, build_cleanup_prompt, cleanup_plan
from products.experiments.backend.models.experiment import Experiment
from products.tasks.backend.facade import api as tasks_facade


class Command(BaseCommand):
    help = "Open a draft 'clean up the experiment's feature flag' PR for one experiment."

    def add_arguments(self, parser) -> None:
        parser.add_argument("experiment_id", type=int, help="Experiment to tidy up.")
        parser.add_argument("--repository", required=True, help='Repo the flag lives in, as "org/repo".')
        parser.add_argument("--branch", default=None, help="Base branch for the PR (defaults to the repo default).")
        parser.add_argument(
            "--user-email", default=None, help="User to run the task as. Defaults to the experiment owner."
        )
        parser.add_argument(
            "--conclusion",
            default=None,
            choices=sorted(CONCLUSION_LABELS),
            help="Override the experiment's conclusion (to test on an experiment that isn't concluded).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print the prompt and the task that would start, without spending a sandbox run.",
        )

    def handle(self, *args, **options) -> None:
        experiment = self._get_experiment(options["experiment_id"])
        conclusion = options["conclusion"] or (experiment.conclusion or "")
        if not conclusion:
            raise CommandError("Experiment has no conclusion. End it first, or pass --conclusion to test.")

        flag_key = experiment.get_feature_flag_key()
        plan = cleanup_plan(conclusion, experiment.feature_flag.variants or [])
        title, description = build_cleanup_prompt(experiment, flag_key, plan)

        self._print_summary(experiment, flag_key, conclusion, plan, options["repository"], options["branch"])
        self.stdout.write("\n----- prompt -----")
        self.stdout.write(description)
        self.stdout.write("------------------\n")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no task started."))
            return

        # Only the real run needs a user (for the task owner + their GitHub integration).
        user = self._resolve_user(experiment, options["user_email"])
        self.stdout.write(f"Run as: {user.email} (id {user.id})")
        self.stdout.write(self.style.WARNING("Starting a real sandbox run (this spins up an agent and costs money)..."))
        created = tasks_facade.create_and_run_task(
            team=experiment.team,
            title=title,
            description=description,
            origin_product=tasks_facade.TaskOriginProduct.USER_CREATED,
            user_id=user.id,
            repository=options["repository"],
            branch=options["branch"],
            create_pr=True,
            interaction_origin="experiments",
            ai_stage="implementation",
        )
        run_id = created.latest_run.id if created.latest_run else None
        self.stdout.write(self.style.SUCCESS(f"Started task {created.task_id} (run {run_id})."))
        self.stdout.write(f"The agent will open a draft PR in {options['repository']} when it finishes.")

    def _get_experiment(self, experiment_id: int) -> Experiment:
        try:
            return Experiment.objects.select_related("feature_flag", "team", "created_by").get(id=experiment_id)
        except Experiment.DoesNotExist:
            raise CommandError(f"Experiment {experiment_id} not found.")

    def _resolve_user(self, experiment: Experiment, user_email: str | None) -> User:
        if user_email:
            user = User.objects.filter(email=user_email).first()
            if user is None:
                raise CommandError(f"No user with email {user_email}.")
            return user
        if experiment.created_by is None:
            raise CommandError("Experiment has no owner; pass --user-email.")
        return experiment.created_by

    def _print_summary(
        self,
        experiment: Experiment,
        flag_key: str,
        conclusion: str,
        plan: CleanupPlan,
        repository: str,
        branch: str | None,
    ) -> None:
        self.stdout.write(f"Experiment: {experiment.name} (id {experiment.id}, team {experiment.team_id})")
        self.stdout.write(f"Flag: {flag_key}")
        self.stdout.write(f"Conclusion: {conclusion}")
        self.stdout.write(f"Keep variant: {plan.keep_variant or '(decide per site)'}")
        self.stdout.write(f"Remove variants: {', '.join(plan.remove_variants) or '(none)'}")
        if not plan.confident:
            self.stdout.write(self.style.WARNING("Low confidence on the keep/remove decision — review the prompt."))
        self.stdout.write(f"Repository: {repository}  Branch: {branch or '(default)'}")
