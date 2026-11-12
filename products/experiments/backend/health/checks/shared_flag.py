"""
Other experiments on the experiment's feature flag. Pure function, no I/O.

The API lets several experiments use one flag. The experiment actions that write the flag change it for every
experiment on it: a pause disables it, and a freeze, a shipped variant or a change of the split rewrites it. A draft
writes its split, rollout and holdout to the flag on every save.

Each experiment reads exposures only between its own start and end, so an ended experiment shares no exposures with a
running one. A new experiment on the flag of an ended one keeps each user's variant, as a reset and a new launch do.
So the check doesn't count ended experiments. On the page of an ended experiment, the flag-state check decides what to
say about the flag, so this check doesn't run there.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import CheckOutcome, CheckSkip, CheckValues, flag_to_check

RUNNING_FLAG_SHARED_WITH_RUNNING = "running_flag_shared_with_running"
RUNNING_FLAG_SHARED_WITH_DRAFT = "running_flag_shared_with_draft"
DRAFT_FLAG_SHARED_WITH_RUNNING = "draft_flag_shared_with_running"


def flag_shared_values(ctx: HealthContext) -> CheckValues:
    if isinstance(flag_to_check(ctx, before_launch=True), CheckSkip):
        return {}
    running, drafts = _other_experiments(ctx)
    return {
        ExperimentHealthValueKey.OTHER_RUNNING_EXPERIMENT_COUNT: running,
        ExperimentHealthValueKey.OTHER_DRAFT_EXPERIMENT_COUNT: drafts,
    }


def flag_shared(ctx: HealthContext) -> CheckOutcome:
    flag = flag_to_check(ctx, before_launch=True)
    if isinstance(flag, CheckSkip):
        return flag
    running, drafts = _other_experiments(ctx)
    if not ctx.is_launched:
        return _draft_shares_with_running(running) if running else None
    if running:
        return _running_shares_with_running(running)
    if drafts:
        return _running_shares_with_draft(drafts)
    return None


def _other_experiments(ctx: HealthContext) -> tuple[int, int]:
    """How many running and how many draft experiments use the flag besides this one."""
    # An archived experiment is ended, or a draft that nobody is going to launch.
    others = [other for other in ctx.other_experiments_on_flag if not other.archived]
    return sum(1 for other in others if other.is_running), sum(1 for other in others if other.is_draft)


def _running_shares_with_running(others: int) -> ExperimentHealthFinding:
    both, either, the_others = (
        ("both", "either one", "the other") if others == 1 else ("all of them", "any of them", "the others")
    )
    return _finding(
        subcode=RUNNING_FLAG_SHARED_WITH_RUNNING,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=(
            "Another running experiment uses this feature flag"
            if others == 1
            else f"{others} other running experiments use this feature flag"
        ),
        detail=(
            f"The experiments read exposures of the same flag, so a user exposed while they run can count in {both}. "
            f"Pausing {either} disables the flag for {both}. Freezing exposure, shipping a variant or changing the "
            f"split from {either} changes the flag for {both} too. If you need only one experiment, end {the_others}. "
            "Ending an experiment doesn't change the flag. To test them separately, end one and run it again on a new "
            "feature flag."
        ),
        evidence={"other_running_experiments": others},
    )


def _draft_shares_with_running(running: int) -> ExperimentHealthFinding:
    the_running = "the running experiment" if running == 1 else "the running experiments"
    return _finding(
        subcode=DRAFT_FLAG_SHARED_WITH_RUNNING,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=(
            "A running experiment already uses this feature flag"
            if running == 1
            else f"{running} running experiments already use this feature flag"
        ),
        detail=(
            f"Saving a change to this draft's split, rollout or holdout changes the flag for {the_running} too. "
            "After launch, both read exposures of the same flag, and pausing this experiment or shipping a variant "
            f"from it changes the flag for {the_running}. To test this experiment separately, duplicate it with a new "
            "feature flag key and delete this draft."
        ),
        evidence={"other_running_experiments": running},
    )


def _running_shares_with_draft(drafts: int) -> ExperimentHealthFinding:
    # Info, because nothing changes the flag until someone edits or launches the draft.
    the_draft = "the draft" if drafts == 1 else "a draft"
    return _finding(
        subcode=RUNNING_FLAG_SHARED_WITH_DRAFT,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=(
            "A draft experiment uses this feature flag"
            if drafts == 1
            else f"{drafts} draft experiments use this feature flag"
        ),
        detail=(
            f"Saving a change to {the_draft}'s split, rollout or holdout changes the flag for this experiment too. "
            f"After {the_draft} launches, both read exposures of the same flag, and pausing either one disables the "
            f"flag for both. To keep {the_draft} separate, duplicate it with a new feature flag key before launch."
        ),
        evidence={"other_draft_experiments": drafts},
    )


def _finding(
    *,
    subcode: str,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    detail: str,
    evidence: dict[str, str | int | float | None],
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.FLAG_SHARED,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=(),
        diagnostic_ref="E15",
    )
