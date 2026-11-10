"""Find where a feature flag is checked in the team's GitHub repository and what each branch runs.

A read-only Tasks run clones the repository and answers with `FlagCodeAnalysisResult`. The flow
mirrors the experiments flag-cleanup PR (`products/experiments/backend/experiment_service.py`),
without opening a pull request.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db import connection, models, transaction

from pydantic import BaseModel, Field, ValidationError

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.sdk_calls import FLAG_SDK_CALLS
from products.feature_flags.backend.models import FeatureFlag, FeatureFlagCodeAnalysis
from products.feature_flags.backend.task_profiles import CODE
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

if TYPE_CHECKING:
    from posthog.models import User

# The pattern the flag API enforces on flag keys.
SAFE_KEY = re.compile(r"[a-zA-Z0-9_-]+")


class CodeAnalysisRepositorySource(models.TextChoices):
    EXPLICIT = "explicit", "Explicit"
    PREVIOUS_ANALYSIS = "previous_analysis", "Previous analysis"
    TEAM_DEFAULT = "team_default", "Team default"
    SINGLE_REPO = "single_repo", "Single repository"
    AMBIGUOUS = "ambiguous", "Ambiguous"
    NO_INTEGRATION = "no_integration", "No integration"


class FlagCodeBranch(BaseModel):
    variant: str = Field(
        description=(
            'What the flag evaluates to on this branch: "enabled", "disabled", or a variant key. "all" when the '
            "same code runs for every outcome and only the flag value passed to it differs."
        )
    )
    start_line: int = Field(description="First line of the branch body, 1-based.")
    end_line: int = Field(description="Last line of the branch body, 1-based, inclusive.")
    snippet: str = Field(description="The branch body exactly as it appears in the file, with its leading whitespace.")


class FlagCodeReference(BaseModel):
    file: str = Field(description="Path of the file from the repository root.")
    check_line: int = Field(
        description="Line where the flag value decides which code runs (the if, ternary, switch, or call it is passed to), 1-based."
    )
    method: str = Field(description="SDK call or wrapper that reads the flag, e.g. isFeatureEnabled.")
    summary: str = Field(description="One sentence on what changes when the flag turns on at this site.")
    branches: list[FlagCodeBranch] = Field(
        description=(
            "One entry per outcome. A check with no else branch still lists the disabled outcome with an empty "
            'snippet. A single "all" entry when the same code runs for every outcome.'
        )
    )


class FlagCodeAnalysisResult(BaseModel):
    repository: str = Field(description="The repository that was analyzed, as org/repo.")
    commit_sha: str = Field(description="Output of `git rev-parse HEAD` in the analyzed checkout.")
    references: list[FlagCodeReference] = Field(description="Every place the flag is checked. Empty when none.")
    notes: str = Field(
        default="",
        description="At most three sentences on what a reader must know: dynamic keys, skipped files, ambiguous checks.",
    )


@frozen
class TaskPrompt:
    """The title and the agent instructions of a Tasks run."""

    title: str
    description: str


@frozen
class CodeAnalysisTarget:
    repository: str | None
    source: CodeAnalysisRepositorySource
    candidates: tuple[str, ...]


@frozen
class CodeAnalysisStatus:
    analysis: FeatureFlagCodeAnalysis
    run_status: str
    is_terminal: bool
    error_message: str | None
    result: FlagCodeAnalysisResult | None
    can_view_task: bool


class CodeAnalysisError(Exception):
    def __init__(
        self,
        code: Literal[
            "ai_not_approved",
            "ai_credits_exhausted",
            "no_repository",
            "already_running",
            "cleanup_unavailable",
            "cleanup_exists",
            "outcome_required",
            "invalid_outcome",
            "unsupported_key",
        ],
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def latest_code_analysis(flag: FeatureFlag) -> FeatureFlagCodeAnalysis | None:
    return (
        FeatureFlagCodeAnalysis.objects.filter(team_id=flag.team_id, feature_flag=flag).order_by("-created_at").first()
    )


def latest_cleanup_analysis(flag: FeatureFlag) -> FeatureFlagCodeAnalysis | None:
    """The newest analysis of the flag that started a cleanup pull request."""
    return (
        FeatureFlagCodeAnalysis.objects.filter(team_id=flag.team_id, feature_flag=flag, cleanup_task_id__isnull=False)
        .order_by("-created_at")
        .first()
    )


def lock_flag_code_work(flag: FeatureFlag) -> None:
    """Serialize analysis and cleanup requests for one flag until the transaction ends.

    One lock covers both, so a cleanup can't start while a new analysis is being created, or the reverse.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"feature_flag_code_analysis:{flag.id}"]
        )


def get_code_analysis_target(flag: FeatureFlag, requested_repository: str | None = None) -> CodeAnalysisTarget:
    """Repository the analysis reads: the requested one, else the one the last analysis used, else the
    environment's default flag cleanup repository, else the team's only connected repository.

    Several repositories and no choice, or no GitHub integration, means there is no target.
    """
    # Keeps the sandbox/LLM runtime the repo-selection module pulls in off the request import path.
    from products.tasks.backend.facade import repo_selection as tasks_repo_selection  # noqa: PLC0415

    # A stale snapshot is good enough to pick a repository, and this runs inside a page request.
    cached = tasks_repo_selection.team_repository_names(flag.team_id, team=flag.team, refresh_stale_snapshot=False)
    if not cached:
        return CodeAnalysisTarget(repository=None, source=CodeAnalysisRepositorySource.NO_INTEGRATION, candidates=())
    candidates = tuple(sorted(cached.values(), key=str.lower))

    if requested_repository:
        # GitHub installations can be shared across projects, so a name outside this team's
        # installation could reach another project's private repository.
        if requested_repository.lower() in cached:
            return CodeAnalysisTarget(
                repository=cached[requested_repository.lower()],
                source=CodeAnalysisRepositorySource.EXPLICIT,
                candidates=candidates,
            )
        return CodeAnalysisTarget(repository=None, source=CodeAnalysisRepositorySource.AMBIGUOUS, candidates=candidates)

    previous = latest_code_analysis(flag)
    if previous is not None and previous.repository.lower() in cached:
        return CodeAnalysisTarget(
            repository=cached[previous.repository.lower()],
            source=CodeAnalysisRepositorySource.PREVIOUS_ANALYSIS,
            candidates=candidates,
        )

    # The experiments facade imports the flag API through approvals, so a module-level import is circular.
    from products.experiments.backend.facade.api import get_team_experiments_settings  # noqa: PLC0415

    team_default = get_team_experiments_settings(flag.team_id).flag_cleanup_repository
    if team_default and team_default.lower() in cached:
        return CodeAnalysisTarget(
            repository=cached[team_default.lower()],
            source=CodeAnalysisRepositorySource.TEAM_DEFAULT,
            candidates=candidates,
        )

    if len(cached) == 1:
        return CodeAnalysisTarget(
            repository=candidates[0], source=CodeAnalysisRepositorySource.SINGLE_REPO, candidates=candidates
        )
    return CodeAnalysisTarget(repository=None, source=CodeAnalysisRepositorySource.AMBIGUOUS, candidates=candidates)


def _outcomes(flag: FeatureFlag) -> str:
    try:
        variants = flag.variants
    except ConfigFormatError:
        # Only a v1 document carries variants in a shape we read, so let the agent find them in the code.
        return "every outcome the code checks"
    keys = [variant.get("key") for variant in variants if isinstance(variant, dict)]
    if not keys:
        return '"enabled" and "disabled"'
    # Variant keys are free text in the flag API. Interpolate them only when they are as safe as a flag key.
    if not all(isinstance(key, str) and SAFE_KEY.fullmatch(key) for key in keys):
        return "every variant the code checks"
    return ", ".join(f'"{key}"' for key in keys)


def build_code_analysis_prompt(flag: FeatureFlag, repository: str) -> TaskPrompt:
    """Return the task title and the agent's instructions.

    Only keys are interpolated: the flag key, which `start_code_analysis` checks against `SAFE_KEY`,
    and variant keys that match the same pattern. The flag's name and description are free text a
    project member wrote, so they stay out of the prompt.
    """
    outcomes = _outcomes(flag)
    title = f"Analyze the code paths of feature flag {flag.key}"
    description = "\n".join(
        [
            f'Find every place this repository checks the PostHog feature flag "{flag.key}", and report what code runs for each outcome.',
            "",
            f"Repository: {repository}",
            f'Feature flag key: "{flag.key}"',
            f"Outcomes to report: {outcomes}",
            "",
            "## How to find the references",
            f'- Start with the exact key "{flag.key}", then follow every constant, enum, or config entry that holds it to the places that use it.',
            "- Inspect local flag helpers and wrapper components, such as a `useFlag('...')` hook or a `Flags.SOME_KEY` registry.",
            f"- Also search for PostHog SDK calls that read flags, e.g.: {FLAG_SDK_CALLS}.",
            "- Cover every directory that deploys on its own (server, browser, mobile, workers) and every language in the repository.",
            "- Report runtime checks only. Skip analytics properties, event payloads, tests, and documentation that mention the key.",
            "",
            "## What to report",
            "- Run `git rev-parse HEAD` and report the commit.",
            "- For each check, report the file, the check line, the SDK call or wrapper, and one branch per outcome.",
            "- The check line is where the flag value decides which code runs: the if, the ternary, the switch, or the call the value is passed to. It is not the line that reads the flag, unless both are the same line.",
            "- A branch is the code that runs for that outcome: the body of the if/else, the ternary arm, the switch case, or the rendered element.",
            "- When an outcome has no code of its own (an if with no else), list it with an empty snippet.",
            '- When the same code runs for every outcome and only the flag value passed to it differs (for example `classList.toggle(name, isOn)`), report one branch with variant "all" instead of repeating the code per outcome.',
            "- Copy snippets exactly from the file, one line per file line, keeping each line's leading whitespace. Use 1-based, inclusive line numbers.",
            "- Write the summary as one plain sentence about what changes for users or callers when the flag turns on.",
            "- If the key is built at runtime or a check is ambiguous, say so in notes rather than guessing.",
            "- Keep notes to at most three sentences. Leave out what the references already show.",
            "- If there are no references, return an empty list and say so in notes.",
            "",
            "## Rules",
            "- Read only. Do not edit files, create branches, commit, or open a pull request.",
            "- Do not change the flag in PostHog.",
        ]
    )
    return TaskPrompt(title=title, description=description)


def require_ai_allowed(flag: FeatureFlag) -> None:
    if flag.team.organization.is_ai_data_processing_approved is not True:
        raise CodeAnalysisError(
            "ai_not_approved",
            "AI data processing is turned off for this organization. An admin can turn it on in organization settings.",
        )
    if _ai_credits_exhausted(flag):
        raise CodeAnalysisError(
            "ai_credits_exhausted",
            "Your organization used all of its AI credits. Check your billing settings, then try again.",
        )


def start_code_analysis(
    flag: FeatureFlag, user: User, requested_repository: str | None = None
) -> FeatureFlagCodeAnalysis:
    # The key goes into the agent's prompt. Older flags predate the API's key validation, so a key with
    # other characters could carry instructions to the agent.
    if not SAFE_KEY.fullmatch(flag.key):
        raise CodeAnalysisError(
            "unsupported_key",
            "Code analysis works only with flag keys made of letters, digits, hyphens, and underscores.",
        )
    require_ai_allowed(flag)

    target = get_code_analysis_target(flag, requested_repository=requested_repository)
    if target.repository is None:
        raise CodeAnalysisError(
            "no_repository",
            "Choose a GitHub repository to analyze. If none are listed, connect GitHub in project settings.",
        )

    prompt = build_code_analysis_prompt(flag, target.repository)
    # The lock makes the running check and the new row one step, so two concurrent requests cannot both
    # start a billable run. The task's workflow starts on commit, so a rollback starts nothing.
    with transaction.atomic():
        lock_flag_code_work(flag)
        previous = latest_code_analysis(flag)
        if previous is not None:
            run = latest_run_for_task(previous.task_id, previous.team_id)
            if run is not None and not run.is_terminal:
                raise CodeAnalysisError(
                    "already_running", "This flag is already being analyzed. Wait for it to finish, then try again."
                )
        # A new analysis row would hide a cleanup run that is still opening its pull request.
        cleanup = latest_cleanup_analysis(flag)
        if cleanup is not None and cleanup.cleanup_task_id is not None:
            cleanup_run = latest_run_for_task(cleanup.cleanup_task_id, cleanup.team_id)
            if cleanup_run is not None and not cleanup_run.is_terminal:
                raise CodeAnalysisError(
                    "already_running",
                    "A cleanup pull request for this flag is being opened. Wait for it to finish, then try again.",
                )
        created = tasks_facade.create_and_run_task(
            team=flag.team,
            title=prompt.title,
            description=prompt.description,
            profile=CODE,
            user_id=user.id,
            repository=target.repository,
            create_pr=False,
            github_read_access=True,
            posthog_mcp_scopes="read_only",
            output_schema=FlagCodeAnalysisResult,
            interaction_origin="feature_flags",
        )
        return FeatureFlagCodeAnalysis.objects.create(
            team_id=flag.team_id,
            feature_flag=flag,
            task_id=created.task_id,
            repository=target.repository,
            created_by=user,
        )


def _ai_credits_exhausted(flag: FeatureFlag) -> bool:
    # Deferred because ee is optional, and a self-hosted build without it has no AI credits to check.
    try:
        from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited  # noqa: PLC0415
    except ImportError:
        return False
    return is_team_limited(flag.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def latest_run_for_task(task_id: UUID, team_id: int) -> TaskRunDTO | None:
    run = tasks_facade.get_latest_run_by_task([task_id]).get(str(task_id))
    # get_latest_run_by_task filters by task id only. After a project transfer the row can point at a
    # task in the old team, so treat that run as absent rather than leaking it across teams.
    if run is not None and run.team_id != team_id:
        return None
    return run


def get_code_analysis_status(flag: FeatureFlag, user: User) -> CodeAnalysisStatus | None:
    analysis = latest_code_analysis(flag)
    if analysis is None:
        return None
    run = latest_run_for_task(analysis.task_id, analysis.team_id)
    can_view_task = tasks_facade.task_visible(analysis.task_id, flag.team_id, user.id)
    # The run is created with its task, so a missing one can't be read, for example after a project transfer.
    # Report it as finished so the page offers a new analysis instead of waiting for a run that never starts.
    if run is None:
        return CodeAnalysisStatus(
            analysis=analysis,
            run_status="failed",
            is_terminal=True,
            error_message="The status of this analysis can't be read. Run it again.",
            result=None,
            can_view_task=can_view_task,
        )
    result: FlagCodeAnalysisResult | None = None
    run_status = run.status
    error_message = run.error_message
    # Only a completed run carries the structured result. The relay writes the agent's last message into
    # `output` after each turn, so a failed or canceled run has output that is not a result.
    if run.status == "completed" and run.output is None:
        run_status = "failed"
        error_message = "The analysis finished without a result. Run it again."
    elif run.status == "completed":
        try:
            result = FlagCodeAnalysisResult.model_validate(run.output)
        except ValidationError:
            run_status = "failed"
            error_message = "The analysis finished, but its result couldn't be read. Run it again."
    return CodeAnalysisStatus(
        analysis=analysis,
        run_status=run_status,
        is_terminal=run.is_terminal,
        error_message=error_message,
        result=result,
        can_view_task=can_view_task,
    )
