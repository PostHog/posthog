"""Next-product selection for organization product push campaigns.

TAM-scheduled rows always take precedence, in TAM-defined order. Otherwise we
walk BLESSED_PRODUCT_ORDER and pick the first product the org is not excluded
from — there is deliberately no preference between never-pushed products and
retry-eligible ones; blessed position decides. When every blessed product is
excluded we pick at random from FALLBACK_PRODUCT_ORDER.

Usage granularity is per project: ProductIntent rows are project-scoped
(RootTeamMixin pins them to the project's root team), so an org only counts as
"using" a product when a majority of its projects do. A product adopted by a
minority of projects still gets pushed to the rest of the org — the promo card
is hidden in the projects that already use it (see the API's team_id handling).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from random import choice

from django.db.models import Q

from posthog.models.organization import Organization
from posthog.models.product_intent.product_intent import ACTIVATION_CHECK_PRODUCT_KEYS, ProductIntent
from posthog.models.project import Project
from posthog.schema_enums import ProductKey

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.cadence import is_retry_eligible

# The order in which we push products to organizations that don't use them yet.
# Seeded from the cross-sell BASE_PREFERENCE_WEIGHTS ranking (see
# cross_sell_candidate_selector.py); extend as growth adds products to the program.
BLESSED_PRODUCT_ORDER: list[ProductKey] = [
    ProductKey.PRODUCT_ANALYTICS,
    ProductKey.WEB_ANALYTICS,
    ProductKey.SESSION_REPLAY,
    ProductKey.ERROR_TRACKING,
    ProductKey.FEATURE_FLAGS,
    ProductKey.EXPERIMENTS,
]

# Unordered pool for orgs that exhausted the blessed order; picked at random.
# Only broadly-available products belong here — nothing feature-flag-gated or
# unreleased in the catalog, since the promo card would link to a product most
# users can't open. Gated products can still be pushed to a specific org via a
# TAM-scheduled row once the flag is enabled for them.
FALLBACK_PRODUCT_ORDER: list[ProductKey] = [
    ProductKey.CONVERSATIONS,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.LLM_ANALYTICS,
    ProductKey.LLM_CLUSTERS,
    ProductKey.LLM_EVALUATIONS,
    ProductKey.LLM_PROMPTS,
    ProductKey.LOGS,
    ProductKey.WORKFLOWS,
]

# Display resolution for pushable products: ProductKey → catalog path (the id the
# frontend resolves to a name, icon, and href). Explicit because intent→product
# inference is ambiguous — several keys map to multiple catalog items and the
# first match is often wrong (e.g. product_analytics's first intent match is
# 'Dashboards'). Validated against products.json in tests.
PUSH_PRODUCT_PATHS: dict[ProductKey, str] = {
    ProductKey.PRODUCT_ANALYTICS: "Product analytics",
    ProductKey.WEB_ANALYTICS: "Web analytics",
    ProductKey.SESSION_REPLAY: "Session replay",
    ProductKey.ERROR_TRACKING: "Error tracking",
    ProductKey.FEATURE_FLAGS: "Feature flags",
    ProductKey.EXPERIMENTS: "Experiments",
    ProductKey.CONVERSATIONS: "Support",
    # The 'Data warehouse' catalog item is unreleased; SQL editor is the shipped surface.
    ProductKey.DATA_WAREHOUSE: "SQL editor",
    ProductKey.LLM_ANALYTICS: "LLM analytics",
    ProductKey.LLM_CLUSTERS: "Clusters",
    ProductKey.LLM_EVALUATIONS: "Evaluations",
    ProductKey.LLM_PROMPTS: "Prompts",
    ProductKey.LOGS: "Logs",
    ProductKey.WORKFLOWS: "Workflows",
}


@dataclass(frozen=True)
class Selection:
    product_key: str
    # Set when the pick promotes an existing TAM-scheduled row instead of creating one.
    scheduled_campaign: ProductPushCampaign | None = None


def get_org_used_product_keys(organization: Organization) -> set[str]:
    """Product keys used in a majority of the org's projects, per ProductIntent.

    For products with an activation criterion (ACTIVATION_CHECK_PRODUCT_KEYS),
    a project "uses" the product when it has an activated intent; for the rest
    the strongest available signal is that any intent row exists at all. A
    product used by only a minority of projects is still worth pushing to the
    rest of the org.
    """
    total_projects = Project.objects.filter(organization_id=organization.id).count()
    if total_projects == 0:
        return set()

    rows = ProductIntent.objects.filter(team__organization_id=organization.id).values_list(
        "product_type", "activated_at", "team__project_id"
    )
    projects_using: defaultdict[str, set[int]] = defaultdict(set)
    for product_type, activated_at, project_id in rows:
        if product_type not in ACTIVATION_CHECK_PRODUCT_KEYS or activated_at is not None:
            projects_using[product_type].add(project_id)

    return {product for product, projects in projects_using.items() if len(projects) * 2 > total_projects}


def project_uses_product(project_id: int, product_key: str) -> bool:
    """The per-project version of the usage signal in get_org_used_product_keys."""
    intents = ProductIntent.objects.filter(team__project_id=project_id, product_type=product_key)
    if product_key in ACTIVATION_CHECK_PRODUCT_KEYS:
        intents = intents.filter(activated_at__isnull=False)
    return intents.exists()


def select_next_product(organization: Organization, now: datetime) -> Selection | None:
    """Pick the product the org's next campaign should push, or None when exhausted.

    Excluded from the blessed/fallback walk: products the org already uses (in a
    majority of projects), products with an ADOPTED campaign, products currently
    ACTIVE or SCHEDULED, and products whose last push ended (skipped or
    cancelled) within SKIP_RETRY_DAYS.
    """
    due_scheduled = (
        ProductPushCampaign.objects.filter(organization=organization, status=ProductPushCampaign.Status.SCHEDULED)
        .filter(Q(scheduled_for__isnull=True) | Q(scheduled_for__lte=now.date()))
        .order_by("position", "created_at")
        .first()
    )
    if due_scheduled is not None:
        return Selection(product_key=due_scheduled.product_key, scheduled_campaign=due_scheduled)

    excluded = get_org_used_product_keys(organization)

    history = ProductPushCampaign.objects.filter(organization=organization).values_list(
        "product_key", "status", "ended_at"
    )
    for product_key, status, ended_at in history:
        if status in (
            ProductPushCampaign.Status.SCHEDULED,
            ProductPushCampaign.Status.ACTIVE,
            ProductPushCampaign.Status.ADOPTED,
        ):
            excluded.add(product_key)
        elif ended_at is not None and not is_retry_eligible(ended_at, now):
            # Skipped or cancelled recently — still in retry cooldown.
            excluded.add(product_key)

    for product_key in BLESSED_PRODUCT_ORDER:
        if product_key.value not in excluded:
            return Selection(product_key=product_key.value)

    fallback_candidates = [product_key for product_key in FALLBACK_PRODUCT_ORDER if product_key.value not in excluded]
    if fallback_candidates:
        return Selection(product_key=choice(fallback_candidates).value)

    return None
