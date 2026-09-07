"""Adoption checks for the non-catalog surfaces the product push card advertises.

Desktop, Slack, GitHub, and Self-driving aren't catalog products, so their "does the org
already use this" signal isn't a ProductIntent row — it's live org state read by org id: a
Slack or GitHub integration, accepted desktop beta terms, or an acted-on Self-driving report.
Each surface is org-wide, so a connection anywhere in the org counts.

Selection reads these to keep advertising a surface until the org adopts it; the campaign
service reads them to close an active campaign as adopted once it does.
"""

import uuid
from collections.abc import Callable
from functools import partial

from posthog.models.integration import Integration
from posthog.schema_enums import ProductKey

OrganizationId = str | uuid.UUID


def organization_has_integration(organization_id: OrganizationId, kind: str) -> bool:
    return Integration.objects.filter(team__organization_id=organization_id, kind=kind).exists()


def organization_accepted_desktop_beta_terms(organization_id: OrganizationId) -> bool:
    # Deferred: the tasks facade pulls in a heavy dependency tree kept off the web startup path.
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    org_uuid = organization_id if isinstance(organization_id, uuid.UUID) else uuid.UUID(organization_id)
    return tasks_facade.get_desktop_beta_terms_acceptance(org_uuid).is_desktop_beta_terms_accepted


def organization_acted_on_signal(organization_id: OrganizationId) -> bool:
    # Deferred: the signals facade pulls in the Temporal stack kept off the web startup path.
    from products.signals.backend.facade import api as signals_facade  # noqa: PLC0415

    return signals_facade.organization_acted_on_report(organization_id)


SURFACE_ADOPTION_CHECKS: dict[str, Callable[..., bool]] = {
    ProductKey.POSTHOG_SLACK.value: partial(organization_has_integration, kind=Integration.IntegrationKind.SLACK),
    ProductKey.POSTHOG_GITHUB.value: partial(organization_has_integration, kind=Integration.IntegrationKind.GITHUB),
    ProductKey.POSTHOG_DESKTOP.value: organization_accepted_desktop_beta_terms,
    ProductKey.SELF_DRIVING.value: organization_acted_on_signal,
}
