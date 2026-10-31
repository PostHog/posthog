from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import ExposureTotals, HealthContext
from products.experiments.backend.health.delays import ZERO_EXPOSURES_GRACE_HOURS
from products.experiments.backend.health.skips import (
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckSkip,
    not_applicable,
    not_checked,
)

# The count without the filter scans the exposure events, so the check runs only on results that look starved.
FEW_EXPOSURES_LIMIT = 1_000
# A filter that leaves out the project's own team and testers removes a small share of a live experiment's users.
# Keeping this share or less means that the filter matches only some users and leaves out everyone else.
KEPT_SHARE_THRESHOLD = 10.0  # on the 0-100 scale (10.0 = 10%)
# While few users are exposed, the project's own team can be most of them, so a small kept share is expected.
MINIMUM_EXPOSED_WITHOUT_FILTER = 100


def reads_share_kept_by_test_account_filter(ctx: HealthContext) -> bool:
    """Whether the test account filter is on, a project filter keeps what it matches, and the experiment counts some
    exposures, but few. The exposure query counts the exposures without the filter for
    `exposures_removed_by_test_account_filter` only then, because the count scans the exposure events."""
    return ctx.exposures is not None and _skip(ctx, ctx.exposures) is None


def exposures_removed_by_test_account_filter(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if skip := _skip(ctx, exposures):
        return skip
    unit = exposures.unit
    exposed = exposures.exposed_without_test_account_filter
    if exposed is None:
        return not_checked(
            f"Couldn't check because the {unit}s exposed without the test account filter weren't counted"
        )
    counted = exposures.total
    if exposed < MINIMUM_EXPOSED_WITHOUT_FILTER or counted * 100 > exposed * KEPT_SHARE_THRESHOLD:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=f"The test account filter removes most exposed {unit}s",
        detail=(
            "The exposure criteria filter out internal and test users, and the project's test account filters keep "
            f"{counted:,} of the {exposed:,} {unit}s exposed to the experiment ({_kept_share(counted, exposed)}).\n\n"
            "Each test account filter is a condition that an exposure must match to count. A filter that matches only "
            'some users, such as an IP address that equals your office address or a cohort with "user in", keeps '
            "those users and leaves out everyone else. To leave out test accounts, write each filter so that it "
            'excludes them, for example with "doesn\'t equal", "doesn\'t contain" or "user not in".\n\n'
            f"If most of the exposed {unit}s are internal, for example in an internal rollout, the filters work as "
            "intended and you can ignore this warning. Otherwise, change the project's test account filters, or turn "
            'off "Filter out internal and test users" in the exposure criteria.'
        ),
        evidence={"exposed_with_test_account_filter": counted, "exposed_without_test_account_filter": exposed},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )


def _kept_share(counted: int, exposed: int) -> str:
    share = counted / exposed * 100
    # One decimal would print this share as 0.0%, which contradicts the count next to it.
    return f"{share:.1f}%" if share >= 0.1 else "less than 0.1%"


def _skip(ctx: HealthContext, exposures: ExposureTotals) -> CheckSkip | None:
    if exposures.hours_since_launch is None or not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if not exposures.filters_test_accounts:
        return not_applicable("Runs when the exposure criteria filter out internal and test users")
    if not exposures.has_positive_test_account_filter:
        return not_applicable("Runs when a test account filter keeps only the users that it matches")
    if exposures.hours_since_launch < ZERO_EXPOSURES_GRACE_HOURS:
        return not_applicable(f"Runs {ZERO_EXPOSURES_GRACE_HOURS} hours after launch")
    if exposures.total == 0:
        return not_applicable("The zero exposures check reports an experiment without exposures")
    if exposures.total >= FEW_EXPOSURES_LIMIT:
        return not_applicable(f"Runs while fewer than {FEW_EXPOSURES_LIMIT:,} {exposures.unit}s are exposed")
    return None
