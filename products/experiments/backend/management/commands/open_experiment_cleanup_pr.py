"""Open a "tidy up the experiment's feature flag" draft PR for one experiment.

Internal spike — the first slice of the experiment-end -> cleanup-PR feature. Given an
experiment and the repository its flag lives in, this builds a cleanup prompt from the
experiment's outcome and feature-flag variants, then hands it to the Tasks engine, which
runs an autonomous coding agent in a sandbox and opens a draft pull request that removes
the flag scaffolding.

There is no automatic trigger and no UI yet — you run it by hand against a repo the team
has a GitHub integration for. The only unknown this proves is PR quality; everything it
calls already works. Use ``--dry-run`` first to read the exact prompt before spending a
sandbox run.

    python manage.py open_experiment_cleanup_pr 123 --repository posthog/posthog --dry-run
    python manage.py open_experiment_cleanup_pr 123 --repository posthog/posthog --branch master
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

from posthog.models import User

from products.experiments.backend.models.experiment import Experiment
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from products.feature_flags.backend.models.feature_flag import FeatureFlag


CONCLUSION_LABELS = {
    "won": "won",
    "lost": "lost",
    "inconclusive": "inconclusive",
    "stopped_early": "stopped early",
    "invalid": "invalid",
}

# PostHog SDK calls that read a flag, across languages — what the agent greps for.
FLAG_SDK_CALLS = (
    "isFeatureEnabled, getFeatureFlag, getFeatureFlagPayload, useFeatureFlag, useActiveFeatureFlags, "
    "onFeatureFlags, posthog.isFeatureEnabled, posthog.getFeatureFlag, feature_enabled, get_feature_flag"
)


@dataclass(frozen=True)
class CleanupPlan:
    keep_variant: str | None
    remove_variants: list[str]
    rationale: str
    confident: bool


def _variants(feature_flag: FeatureFlag) -> list[dict]:
    return feature_flag.variants or []


def _variant_keys(feature_flag: FeatureFlag) -> list[str]:
    return [v["key"] for v in _variants(feature_flag) if v.get("key")]


def _fully_rolled_out_variant(feature_flag: FeatureFlag) -> str | None:
    """After "ship a variant", the winner sits at 100% — return it if exactly one does."""
    at_100 = [v["key"] for v in _variants(feature_flag) if v.get("rollout_percentage") == 100 and v.get("key")]
    return at_100[0] if len(at_100) == 1 else None


def _cleanup_plan(conclusion: str, feature_flag: FeatureFlag) -> CleanupPlan:
    """Decide which variant's code path to keep, from the outcome and the flag's variants.

    "won" keeps the shipped variant (the one rolled out to 100%); a plain win with nothing
    shipped falls back to the single non-control variant as a best guess. Every other
    outcome rolls back to the baseline ("control"). Anything uncertain is marked so the
    operator (and the PR) flag it for human review rather than guessing silently.
    """
    keys = _variant_keys(feature_flag)
    non_control = [k for k in keys if k != "control"]
    has_control = "control" in keys

    def plan(keep: str | None, rationale: str, confident: bool) -> CleanupPlan:
        return CleanupPlan(
            keep_variant=keep,
            remove_variants=[k for k in keys if k != keep],
            rationale=rationale,
            confident=confident,
        )

    if conclusion == "won":
        shipped = _fully_rolled_out_variant(feature_flag)
        if shipped:
            return plan(
                shipped,
                f'The experiment won and variant "{shipped}" was shipped (100% rollout). Keep it as the new default.',
                True,
            )
        if len(non_control) == 1:
            return plan(
                non_control[0],
                f'The experiment won but no variant is at 100% rollout. Best guess: keep the winning variant "{non_control[0]}". Confirm which variant you kept in the PR.',
                False,
            )
        return plan(
            None,
            "The experiment won, but the winning variant can't be determined automatically (more than one non-control variant). Decide per code site and explain your choice in the PR.",
            False,
        )

    keep = "control" if has_control else (keys[0] if keys else None)
    if conclusion in ("lost", "invalid"):
        return plan(
            keep,
            f'The experiment {CONCLUSION_LABELS.get(conclusion, conclusion)}. Roll back to the baseline: keep "{keep}" and remove the feature.',
            True,
        )
    return plan(
        keep,
        f'The experiment was {CONCLUSION_LABELS.get(conclusion, conclusion)}. Defaulting to the baseline "{keep}" — confirm this is the rollback you want.',
        False,
    )


def build_cleanup_prompt(experiment: Experiment, flag_key: str, plan: CleanupPlan) -> tuple[str, str]:
    """Return (title, description) — the task title and the agent's full instructions."""
    title = f"Clean up feature flag {flag_key} after experiment {experiment.id}"
    remove = ", ".join(f'"{k}"' for k in plan.remove_variants) or "(none)"
    keep_line = (
        f'- Keep the code path for variant "{plan.keep_variant}".'
        if plan.keep_variant
        else "- Keep the winning variant's code path (decide per site — see the note below)."
    )
    variants = ", ".join(_variant_keys(experiment.feature_flag)) or "(boolean / none)"

    description = "\n".join(
        [
            "Remove the scaffolding for a PostHog experiment feature flag that is no longer needed, and open a draft pull request.",
            "",
            f'Experiment: "{experiment.name}" (id {experiment.id})',
            f"Outcome: {CONCLUSION_LABELS.get(experiment.conclusion or '', experiment.conclusion or 'unknown')}",
            f'Feature flag key: "{flag_key}"',
            f"Flag variants: {variants}",
            "",
            "## What to change",
            f'Remove all references to the feature flag "{flag_key}" from this codebase and keep the correct code path.',
            keep_line,
            f"- Remove the code paths for variant(s): {remove}.",
            f'- Remove every check of the flag "{flag_key}" itself.',
            "",
            f"Why: {plan.rationale}",
            "",
            "## How to find the references",
            f'Search the repo for the flag key "{flag_key}" and for PostHog SDK calls that read flags, e.g.:',
            f"  {FLAG_SDK_CALLS}",
            "Cover every language used in the repo (JS/TS, Python, Go, Ruby, PHP, etc.).",
            "",
            "## Rules",
            "- For the kept variant: keep that branch's body, delete the surrounding flag check and the other branches.",
            "- Boolean-style checks: keep the enabled path's body and drop the if-check (and any else branch).",
            "- Remove the now-dead code you create: orphaned branches, unused imports, unused helpers.",
            "- Code only. Do NOT change the flag in PostHog, and do NOT touch unrelated code.",
            "- If the correct path is genuinely ambiguous at a site, leave it unchanged and list it in the PR description for a human to review.",
            "",
            "## Output",
            f'Open a draft pull request titled "{title}". In the description, summarise what you removed and anything you left for manual review.',
        ]
    )
    return title, description


class Command(BaseCommand):
    help = "Open a draft 'clean up the experiment's feature flag' PR for one experiment (internal spike)."

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
        plan = _cleanup_plan(conclusion, experiment.feature_flag)
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
