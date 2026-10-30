from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.bias_risk import MULTIPLE_VARIANT_KEY
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable, not_checked

# Some users get more than one ID in any experiment, for example one per device, so a low share is expected.
# The share grows as users return and log in, so a lower line fires on a large part of all experiments. The cases
# that users report sit above this line.
MULTIPLE_VARIANTS_SHARE_THRESHOLD = 5.0  # on the 0-100 scale (5.0 = 5%)
# The floor counts users or groups, not exposures: each of them is a fact, so the finding can fire on a new
# experiment. The floor stops one or two testers who switch between variants from firing it.
MULTIPLE_VARIANTS_MINIMUM_COUNT = 5


def multiple_variants_share(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # Under "First seen" the exposure query gives each user their first variant, so it counts none of these users.
    if exposures.multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return not_checked("Couldn't check because the First seen handling doesn't count these users")
    multiple = exposures.total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    total = sum(exposures.total_exposures.values())
    if multiple < MULTIPLE_VARIANTS_MINIMUM_COUNT:
        return None
    percentage = multiple / total * 100
    if percentage <= MULTIPLE_VARIANTS_SHARE_THRESHOLD:
        return None
    # The flag gives every member of a group the same variant, so the causes of a person's several IDs do not apply.
    if exposures.counts_groups:
        title = "Many groups were exposed to multiple variants"
        detail = (
            f"{percentage:.1f}% of groups ({multiple}) were exposed to multiple variants, so the results leave them "
            "out. The exposures table lists them as $multiple.\n\n"
            "The flag gives every member of a group the same variant, so this usually means that the flag changed "
            "after launch, for example with a new variant split or a change from matching users to matching groups. "
            "It also happens when a person switches to another group and your code reads the flag before the flags "
            "reload: the event then carries the new group with the variant of the old group.\n\n"
            "Check the flag's history, and after a group switch, read the flag only once the flags reload."
        )
    else:
        title = "Many users were exposed to multiple variants"
        detail = (
            f"{percentage:.1f}% of users ({multiple}) were exposed to multiple variants, so the results leave them "
            "out. The exposures table lists them as $multiple. If a variant changes how often users log in, each "
            "variant loses a different group of users, and the results can be biased.\n\n"
            "This usually means that one person has more than one ID: an anonymous ID before login and another after, "
            "an ID for each device, a new ID after reset(), or a different ID on your server than in the browser. It "
            "also happens when a bootstrapped flag value differs from the value PostHog evaluates, or when the flag "
            "changes after launch, for example with a new variant split.\n\n"
            "Identify users before your code evaluates the flag, call reset() only at logout, and send the same ID "
            "from your server."
        )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence={"multiple_variant_percentage": percentage, "multiple_variant_count": multiple},
        actions=(),
        diagnostic_ref="A3",
    )
