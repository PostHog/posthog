"""Find where a feature flag is checked in the team's GitHub repository and what each branch runs.

A read-only Tasks run clones the repository and answers with `FlagCodeAnalysisResult`. The flow
mirrors the experiments flag-cleanup PR (`products/experiments/backend/experiment_service.py`),
without opening a pull request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django.db import models

from pydantic import BaseModel, Field, ValidationError

from posthog.dataclasses import frozen

from products.feature_flags.backend.models import FeatureFlag, FeatureFlagCodeAnalysis
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

if TYPE_CHECKING:
    from posthog.models import User

# PostHog SDK calls that read a flag, across languages. The agent searches for these besides the key.
FLAG_SDK_CALLS = (
    "isFeatureEnabled, getFeatureFlag, getFeatureFlagPayload, getFeatureFlagResult, useFeatureFlagEnabled, "
    "useFeatureFlagVariantKey, useFeatureFlagPayload, useFeatureFlagResult, PostHogFeature, evaluateFlags, "
    "getFlag, isEnabled, feature_enabled, get_feature_flag, get_feature_flag_payload, evaluate_flags, "
    "get_flag, is_enabled, GetFeatureFlag, IsFeatureEnabled"
)


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
    snippet: str = Field(description="The branch body exactly as it appears in the file.")


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
        code: Literal["ai_not_approved", "ai_credits_exhausted", "no_repository", "already_running"],
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


def latest_code_analysis(flag: FeatureFlag) -> FeatureFlagCodeAnalysis | None:
    return (
        FeatureFlagCodeAnalysis.objects.filter(team_id=flag.team_id, feature_flag=flag).order_by("-created_at").first()
    )


def get_code_analysis_target(flag: FeatureFlag, requested_repository: str | None = None) -> CodeAnalysisTarget:
    """Repository the analysis reads: the requested one, else the one the last analysis used, else the
    environment's default flag cleanup repository, else the team's only connected repository.

    Several repositories and no choice, or no GitHub integration, means there is no target.
    """
    # Keeps the sandbox/LLM runtime the repo-selection module pulls in off the request import path.
    from products.tasks.backend.facade import repo_selection as tasks_repo_selection  # noqa: PLC0415

    # team_only: the candidates are shown to anyone who can see the flag, so a personal connection
    # must not leak someone's private repository names.
    github = tasks_repo_selection.resolve_team_github_integration(flag.team_id, team=flag.team, team_only=True)
    if github is None:
        return CodeAnalysisTarget(repository=None, source=CodeAnalysisRepositorySource.NO_INTEGRATION, candidates=())
    cached = {
        full_name.lower(): full_name
        for repo in github.list_all_cached_repositories(max_repos=1000)
        if (full_name := repo.get("full_name"))
    }
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


def _variant_keys(flag: FeatureFlag) -> list[str]:
    return [key for variant in flag.variants if isinstance(variant, dict) and (key := variant.get("key"))]


def build_code_analysis_prompt(flag: FeatureFlag, repository: str) -> tuple[str, str]:
    """Return (title, description): the task title and the agent's instructions.

    Only the flag key is interpolated. Keys are restricted to letters, digits, `-` and `_`, while the
    flag's name and description are free text a project member wrote, so they stay out of the prompt.
    """
    variants = _variant_keys(flag)
    outcomes = ", ".join(f'"{key}"' for key in variants) if variants else '"enabled" and "disabled"'
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
            "- Copy snippets exactly from the file. Use 1-based, inclusive line numbers.",
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
    return title, description


def start_code_analysis(
    flag: FeatureFlag, user: User, requested_repository: str | None = None
) -> FeatureFlagCodeAnalysis:
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

    previous = latest_code_analysis(flag)
    if previous is not None:
        run = _latest_run(previous)
        if run is not None and not run.is_terminal:
            raise CodeAnalysisError(
                "already_running", "This flag is already being analyzed. Wait for it to finish, then try again."
            )

    target = get_code_analysis_target(flag, requested_repository=requested_repository)
    if target.repository is None:
        raise CodeAnalysisError(
            "no_repository",
            "Choose a GitHub repository to analyze. If none are listed, connect GitHub in project settings.",
        )

    title, description = build_code_analysis_prompt(flag, target.repository)
    created = tasks_facade.create_and_run_task(
        team=flag.team,
        title=title,
        description=description,
        origin_product=tasks_facade.TaskOriginProduct.FEATURE_FLAGS,
        user_id=user.id,
        repository=target.repository,
        create_pr=False,
        github_read_access=True,
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


def _latest_run(analysis: FeatureFlagCodeAnalysis) -> TaskRunDTO | None:
    run = tasks_facade.get_latest_run_by_task([analysis.task_id]).get(str(analysis.task_id))
    # get_latest_run_by_task filters by task id only. After a project transfer the row can point at a
    # task in the old team, so treat that run as absent rather than leaking it across teams.
    if run is not None and run.team_id != analysis.team_id:
        return None
    return run


def get_code_analysis_status(flag: FeatureFlag, user: User) -> CodeAnalysisStatus | None:
    analysis = latest_code_analysis(flag)
    if analysis is None:
        return None
    run = _latest_run(analysis)
    result: FlagCodeAnalysisResult | None = None
    run_status = run.status if run else "queued"
    error_message = run.error_message if run else None
    if run is not None and run.is_terminal and run.output is not None:
        try:
            result = FlagCodeAnalysisResult.model_validate(run.output)
        except ValidationError:
            run_status = "failed"
            error_message = "The analysis finished, but its result couldn't be read. Run it again."
    elif run is not None and run.status == "completed":
        run_status = "failed"
        error_message = "The analysis finished without a result. Run it again."
    return CodeAnalysisStatus(
        analysis=analysis,
        run_status=run_status,
        is_terminal=run.is_terminal if run else False,
        error_message=error_message,
        result=result,
        can_view_task=tasks_facade.task_visible(analysis.task_id, flag.team_id, user.id),
    )
