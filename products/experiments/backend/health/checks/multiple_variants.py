from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.bias_risk import MULTIPLE_VARIANT_KEY
from products.experiments.backend.health.context import HealthContext

# Some users get more than one ID in any experiment, for example one per device, so a low share is expected.
# The share grows as users return and log in, so a lower line fires on a large part of all experiments. The cases
# that users report sit above this line.
MULTIPLE_VARIANTS_SHARE_THRESHOLD = 5.0  # on the 0-100 scale (5.0 = 5%)
# The floor counts users, not exposures: each of these users is a fact, so the finding can fire on a new
# experiment. The floor stops one or two testers who switch between variants from firing it.
MULTIPLE_VARIANTS_MINIMUM_USERS = 5


def multiple_variants_share(ctx: HealthContext) -> ExperimentHealthFinding | None:
    exposures = ctx.exposures
    # Under "First seen" the exposure query gives each user their first variant, so it counts none of these users.
    if exposures is None or exposures.multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None
    multiple = exposures.total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    total = sum(exposures.total_exposures.values())
    if multiple < MULTIPLE_VARIANTS_MINIMUM_USERS:
        return None
    percentage = multiple / total * 100
    if percentage <= MULTIPLE_VARIANTS_SHARE_THRESHOLD:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.MULTIPLE_VARIANTS_SHARE,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="Many users were exposed to multiple variants",
        detail=(
            f"{percentage:.1f}% of users ({multiple}) were exposed to multiple variants, so the results leave them "
            "out. The exposures table lists them as $multiple. This usually means that one person has more than one "
            "ID: an anonymous ID before login and another after, an ID for each device, a new ID after reset(), or a "
            "different ID on your server than in the browser. A change to the flag after launch, such as a new "
            "variant split, also moves users to another variant. "
            "If a variant changes how often users log in, each variant loses a different group of users, "
            "and the results can be biased. Identify users before your code evaluates the flag, call reset() only "
            "at logout, and send the same ID from your server."
        ),
        evidence={"multiple_variant_percentage": percentage, "multiple_variant_count": multiple},
        actions=(),
        diagnostic_ref="A3",
    )
