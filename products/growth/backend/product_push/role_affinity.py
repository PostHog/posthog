"""Role-weighted picking for the product push fallback pool.

Members state a role when they sign up (`User.role_at_organization`). The fallback
pool is a long tail of products that suit some teams and not others, so picking
from it uniformly throws away the one thing we already know about who works at the
organization. Each role names the products its people reach for, and a product's
weight grows with the share of members in those roles: an org full of data people
is far more likely to be shown the SQL editor than PostHog in Slack.

Weighting, not filtering: every candidate keeps a non-zero weight, so a product no
role favors still gets pushed and the org still sees the whole pool over time.
"""

from collections import Counter
from random import choices

from posthog.models.organization import Organization, OrganizationMembership
from posthog.schema_enums import ProductKey

# Products each signup role is expected to want, keyed by the values in
# `posthog.models.user.ROLE_CHOICES`. Roles with no clear product opinion (founder,
# leadership, student, other) are left out on purpose: they neither boost a product
# nor dilute the members who did state a usable role.
# Every product in FALLBACK_PRODUCT_ORDER appears at least once, so no candidate is
# permanently stuck at the base weight.
ROLE_PRODUCT_AFFINITIES: dict[str, frozenset[ProductKey]] = {
    "engineering": frozenset(
        {
            ProductKey.LOGS,
            ProductKey.POSTHOG_GITHUB,
            ProductKey.POSTHOG_DESKTOP,
            ProductKey.LLM_ANALYTICS,
            ProductKey.LLM_PROMPTS,
            ProductKey.LLM_EVALUATIONS,
        }
    ),
    "data": frozenset(
        {
            ProductKey.DATA_WAREHOUSE,
            ProductKey.LLM_CLUSTERS,
            ProductKey.LLM_EVALUATIONS,
        }
    ),
    "product": frozenset(
        {
            ProductKey.CONVERSATIONS,
            ProductKey.WORKFLOWS,
            ProductKey.LLM_CLUSTERS,
        }
    ),
    "marketing": frozenset(
        {
            ProductKey.MARKETING_ANALYTICS,
            ProductKey.WORKFLOWS,
        }
    ),
    "sales": frozenset(
        {
            ProductKey.CONVERSATIONS,
            ProductKey.MARKETING_ANALYTICS,
        }
    ),
}

# Weight of a product no stated role favors. Keeps every candidate reachable.
BASE_WEIGHT = 1.0

# Added on top of BASE_WEIGHT when every member with a stated role favors the product,
# scaled down by the share that actually does. Four means a product the whole org's
# roles point at is picked five times as often as one none of them do.
MAX_ROLE_BOOST = 4.0


def get_role_counts(organization: Organization) -> Counter[str]:
    """How many of the organization's members stated each role at signup."""
    roles = OrganizationMembership.objects.filter(organization=organization).values_list(
        "user__role_at_organization", flat=True
    )
    return Counter(role for role in roles if role)


def weights_for_roles(role_counts: Counter[str], candidates: list[ProductKey]) -> list[float]:
    """Weight per candidate, in the order given.

    Roles with no entry in ROLE_PRODUCT_AFFINITIES leave the count entirely, so the
    shares read as "of the people who told us something we can act on". Keeping them
    in the denominator would flatten the weighting of every org where most members
    picked a role with no product opinion.
    """
    opinionated = Counter({role: count for role, count in role_counts.items() if role in ROLE_PRODUCT_AFFINITIES})
    total = sum(opinionated.values())
    if total == 0:
        return [BASE_WEIGHT] * len(candidates)

    weights = []
    for product_key in candidates:
        favoring = sum(count for role, count in opinionated.items() if product_key in ROLE_PRODUCT_AFFINITIES[role])
        weights.append(BASE_WEIGHT + MAX_ROLE_BOOST * favoring / total)
    return weights


def pick_by_role_affinity(organization: Organization, candidates: list[ProductKey]) -> ProductKey:
    """Pick one candidate at random, favoring what the organization's roles point at."""
    weights = weights_for_roles(get_role_counts(organization), candidates)
    return choices(candidates, weights=weights, k=1)[0]
