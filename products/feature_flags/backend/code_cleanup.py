"""Open a draft pull request that removes a stale flag's checks from the code.

The cleanup starts from the flag's latest code analysis: it targets the repository the analysis read
and hands the agent the checks the analysis found. The work runs as a Tasks run that opens the pull
request, the same way the experiments flag-cleanup PR does
(`products/experiments/backend/experiment_service.py`).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import models, transaction

from posthog.dataclasses import frozen

from products.feature_flags.backend.code_analysis import (
    SAFE_KEY,
    CodeAnalysisError,
    CodeAnalysisStatus,
    FlagCodeAnalysisResult,
    TaskPrompt,
    get_code_analysis_status,
    get_code_analysis_target,
    latest_cleanup_analysis,
    latest_code_analysis,
    latest_run_for_task,
    lock_flag_code_work,
    require_ai_allowed,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.flag_status import FeatureFlagStatus, FeatureFlagStatusChecker
from products.feature_flags.backend.models import FeatureFlag, FeatureFlagCodeAnalysis
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from posthog.models import User

ENABLED = "enabled"
DISABLED = "disabled"

# File paths come from the analysis agent's output. Only plain paths reach the cleanup prompt, so text
# the agent copied from the repository cannot add instructions there.
_SAFE_PATH = re.compile(r"[\w./@+-]{1,300}")
_SAFE_COMMIT = re.compile(r"[0-9a-f]{7,40}")
# The prompt lists at most this many checks. The agent searches the repository again in any case.
_MAX_PROMPT_REFERENCES = 50


class CodeCleanupUnavailableReason(models.TextChoices):
    ANALYSIS_NOT_READY = "analysis_not_ready", "Analysis not ready"
    NO_REFERENCES = "no_references", "No references"
    NOT_STALE = "not_stale", "Not stale"
    UNSUPPORTED_CONFIG = "unsupported_config", "Unsupported configuration"


@frozen
class CodeCleanupAvailability:
    unavailable_reason: CodeCleanupUnavailableReason | None
    suggested_outcome: str | None
    outcome_options: tuple[str, ...]


@frozen
class CodeCleanupRun:
    task_id: UUID
    run_status: str
    is_terminal: bool
    pr_url: str | None
    error_message: str | None
    can_view_task: bool


def _outcome_options(flag: FeatureFlag) -> tuple[str, ...] | None:
    """Outcomes the code can keep, or None when the flag's configuration can't be read safely."""
    # The cleanup run can push code, so check the key again: older flags predate the key validation.
    if not SAFE_KEY.fullmatch(flag.key):
        return None
    try:
        variants = flag.variants
    except ConfigFormatError:
        return None
    raw_keys = [variant.get("key") for variant in variants if isinstance(variant, dict)]
    if not raw_keys:
        return (ENABLED, DISABLED)
    # Variant keys go into the prompt, so they must be as safe as a flag key.
    # A variant named like a boolean outcome would get the boolean instruction in the prompt.
    keys = [
        key for key in raw_keys if isinstance(key, str) and SAFE_KEY.fullmatch(key) and key not in (ENABLED, DISABLED)
    ]
    if len(keys) != len(raw_keys):
        return None
    return (DISABLED, *keys)


def _suggested_outcome(flag: FeatureFlag) -> str | None:
    """The outcome every user gets today, which is the code to keep. None when users get different outcomes."""
    # With no release conditions nothing matches, so every user gets false. The status checker counts this
    # shape as fully rolled out, which is right for staleness but not for which code runs.
    if not flag.conditions:
        return DISABLED
    # Early access enrollment and holdouts serve some users outside the release conditions.
    if flag.has_feature_enrollment or flag.holdout:
        return None
    checker = FeatureFlagStatusChecker(feature_flag=flag)
    is_fully_rolled_out, _ = checker.is_flag_fully_rolled_out(flag)
    if is_fully_rolled_out:
        return checker.sole_served_variant(flag) if flag.variants else ENABLED
    if checker.get_rollout_summary(flag).max_rollout_percentage == 0:
        return DISABLED
    return None


def get_cleanup_availability(flag: FeatureFlag, analysis_status: CodeAnalysisStatus) -> CodeCleanupAvailability:
    def unavailable(reason: CodeCleanupUnavailableReason) -> CodeCleanupAvailability:
        return CodeCleanupAvailability(unavailable_reason=reason, suggested_outcome=None, outcome_options=())

    if analysis_status.result is None:
        return unavailable(CodeCleanupUnavailableReason.ANALYSIS_NOT_READY)
    if not analysis_status.result.references:
        return unavailable(CodeCleanupUnavailableReason.NO_REFERENCES)
    flag_status, _ = FeatureFlagStatusChecker(feature_flag=flag).get_status()
    if flag_status != FeatureFlagStatus.STALE:
        return unavailable(CodeCleanupUnavailableReason.NOT_STALE)
    options = _outcome_options(flag)
    if options is None:
        return unavailable(CodeCleanupUnavailableReason.UNSUPPORTED_CONFIG)
    return CodeCleanupAvailability(
        unavailable_reason=None, suggested_outcome=_suggested_outcome(flag), outcome_options=options
    )


def get_cleanup_run(flag: FeatureFlag, user: User) -> CodeCleanupRun | None:
    """The flag's latest cleanup run, from whichever analysis started it.

    A newer analysis doesn't hide a cleanup, so the page keeps its pull request and can't open a second one.
    """
    analysis = latest_cleanup_analysis(flag)
    if analysis is None or analysis.cleanup_task_id is None:
        return None
    run = latest_run_for_task(analysis.cleanup_task_id, analysis.team_id)
    # The run is created with its task, so a missing one is unreadable, for example after a project
    # transfer. Treat it as absent so it can't block a new request forever.
    if run is None:
        return None
    return CodeCleanupRun(
        task_id=analysis.cleanup_task_id,
        run_status=run.status,
        is_terminal=run.is_terminal,
        pr_url=run.pr_url,
        error_message=run.error_message,
        can_view_task=tasks_facade.task_visible(analysis.cleanup_task_id, analysis.team_id, user.id),
    )


def _keep_instruction(outcome: str) -> str:
    if outcome == ENABLED:
        return "Keep the code that runs when the flag is enabled. Remove the code that runs when it is disabled."
    if outcome == DISABLED:
        return (
            "Keep the code that runs when the flag is disabled or evaluates to false. Remove the code that runs "
            "when it is enabled or set to any variant."
        )
    return f'Keep the code that runs for the variant "{outcome}". Remove the code for every other outcome.'


def _reference_lines(result: FlagCodeAnalysisResult) -> list[str]:
    lines = [
        f"- {reference.file}:{reference.check_line}"
        for reference in result.references[:_MAX_PROMPT_REFERENCES]
        if _SAFE_PATH.fullmatch(reference.file)
    ]
    return lines or ["- (none that can be listed here, so search the repository)"]


def build_code_cleanup_prompt(
    flag: FeatureFlag, repository: str, keep_outcome: str, result: FlagCodeAnalysisResult
) -> TaskPrompt:
    """Return the task title and the agent's instructions.

    Only the flag key, safe variant keys, plain file paths and a hex commit are interpolated. The
    analysis summaries and notes are model output, so they stay out of the prompt.
    """
    title = f"Remove stale feature flag {flag.key}"
    commit = result.commit_sha if _SAFE_COMMIT.fullmatch(result.commit_sha) else "an earlier commit"
    description = "\n".join(
        [
            f'Remove every check of the PostHog feature flag "{flag.key}" from this repository, keep the right code path, and open a draft pull request.',
            "",
            f"Repository: {repository}",
            f'Feature flag key: "{flag.key}"',
            "PostHog marks this flag as stale, so it no longer needs to decide which code runs.",
            "",
            "## Which code to keep",
            f"- {_keep_instruction(keep_outcome)}",
            "",
            "## Where the flag is checked",
            f"An earlier read-only analysis at commit {commit} found checks at these places:",
            *_reference_lines(result),
            "The code can have changed since that commit. Use the list as a starting point, then search the repository again:",
            f'- Search for the exact key "{flag.key}" and follow every constant, enum, or config entry that holds it.',
            "- Inspect local flag helpers and wrapper components that take the key.",
            "- Cover every language and every directory that deploys on its own.",
            "",
            "## Rules",
            "- At each check, keep the body of the branch to keep, then delete the flag check and the other branches.",
            "- If the kept branch does nothing, delete the check entirely. Do not leave an empty block or a no-op component.",
            "- Remove the dead code the change creates: unused imports, helpers, components, constants, and the flag key constant itself when nothing else uses it.",
            "- Update or delete tests that only exercise the removed branches, and fix tests that mock the flag.",
            "- Leave reads of the flag's payload unchanged, because you don't know its value. List them in the pull request description.",
            "- Do not touch unrelated code.",
            "- If the right code path is unclear at a check, leave it unchanged and list it in the pull request description.",
            "- Do not change the flag in PostHog.",
            "- If the repository has no checks of the flag, do not open a pull request. Say so in your final message.",
            "",
            "## Output",
            f'Open a draft pull request titled "{title}".',
            "In the description, say which outcome the code keeps, list the files you changed, and list anything left for a person to review.",
            "End the description with a reminder to archive the flag in PostHog after the change deploys.",
        ]
    )
    return TaskPrompt(title=title, description=description)


def _cleanup_blocks_new_request(run: CodeCleanupRun | None) -> bool:
    # A failed or canceled run, or one that finished without a pull request, can be retried. One that opened
    # a pull request blocks another, so the repository never gets two cleanup pull requests for one flag.
    if run is None:
        return False
    return not run.is_terminal or (run.run_status == "completed" and run.pr_url is not None)


def start_code_cleanup(flag: FeatureFlag, user: User, keep_outcome: str | None = None) -> FeatureFlagCodeAnalysis:
    require_ai_allowed(flag)

    latest = latest_code_analysis(flag)
    if latest is None:
        raise CodeAnalysisError(
            "cleanup_unavailable", "Analyze the flag's code first, then open the cleanup pull request."
        )
    # Resolved before the lock because it can call GitHub. GitHub installations can be shared across
    # projects, so the repository must still belong to this one.
    target = get_code_analysis_target(flag, requested_repository=latest.repository)
    if target.repository is None:
        raise CodeAnalysisError(
            "no_repository",
            f"{latest.repository} is no longer connected to this project. Connect it, or analyze another repository.",
        )

    # The lock makes the checks and the new task one step, so two concurrent requests cannot both open a
    # pull request. The task's workflow starts on commit, so a rollback starts nothing.
    with transaction.atomic():
        lock_flag_code_work(flag)
        analysis_status = get_code_analysis_status(flag, user)
        if analysis_status is None or analysis_status.analysis.id != latest.id:
            raise CodeAnalysisError(
                "cleanup_unavailable", "The flag was analyzed again. Review the new result, then try again."
            )
        if _cleanup_blocks_new_request(get_cleanup_run(flag, user)):
            raise CodeAnalysisError(
                "cleanup_exists", "A cleanup pull request for this flag is already open or in progress."
            )
        availability = get_cleanup_availability(flag, analysis_status)
        if availability.unavailable_reason == CodeCleanupUnavailableReason.ANALYSIS_NOT_READY:
            raise CodeAnalysisError(
                "cleanup_unavailable", "Wait for the analysis to finish, then open the cleanup pull request."
            )
        if availability.unavailable_reason == CodeCleanupUnavailableReason.NOT_STALE:
            raise CodeAnalysisError(
                "cleanup_unavailable", "Only stale flags can be removed from the code. This flag isn't stale."
            )
        if availability.unavailable_reason is not None:
            raise CodeAnalysisError("cleanup_unavailable", "This flag has no code that can be removed automatically.")

        outcome = keep_outcome or availability.suggested_outcome
        if outcome is None:
            raise CodeAnalysisError(
                "outcome_required", "Users get different outcomes from this flag. Choose which code to keep."
            )
        if outcome not in availability.outcome_options:
            raise CodeAnalysisError("invalid_outcome", f"Choose one of: {', '.join(availability.outcome_options)}.")

        assert analysis_status.result is not None
        prompt = build_code_cleanup_prompt(flag, target.repository, outcome, analysis_status.result)
        created = tasks_facade.create_and_run_task(
            team=flag.team,
            title=prompt.title,
            description=prompt.description,
            origin_product=tasks_facade.TaskOriginProduct.FEATURE_FLAGS,
            user_id=user.id,
            repository=target.repository,
            create_pr=True,
            posthog_mcp_scopes="read_only",
            interaction_origin="feature_flags",
            ai_stage="implementation",
        )
        analysis = analysis_status.analysis
        analysis.cleanup_task_id = created.task_id
        analysis.save(update_fields=["cleanup_task_id"])
        return analysis
