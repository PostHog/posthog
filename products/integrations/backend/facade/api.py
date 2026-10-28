"""The integrations SDK: the only way to read and write `Integration` rows.

    from products.integrations.backend.facade.api import IntegrationManager

    IntegrationManager.github.oauth.get(team_id, integration_id)  # one kind, one auth type: reads and writes
    IntegrationManager.stripe.any.list(team_id)                   # one kind, every auth type: reads and deletes
    IntegrationManager.any.get(team_id, integration_id)           # every kind: reads and deletes
    IntegrationManager.source("ab-tasty").token.create(...)       # warehouse source rows of a registered kind

A kind class has an attribute only for the auth types that the kind supports, so mypy rejects
`IntegrationManager.github.credentials`. `.any` has no writes, because a new row has exactly one auth
type. See `products/integrations/backend/README.md`.
"""

from collections.abc import Mapping

from posthog.models.integration.model import Integration

from products.integrations.backend.facade import api_accessors
from products.integrations.backend.facade.enums import AuthType
from products.integrations.backend.facade.kinds_generated import GeneratedIntegrationManager
from products.integrations.backend.logic import source_kinds, usages

# The Django model for now. A later change makes it a frozen record, so callers must not call
# `.save()` or `.delete()` on it, and must write through the SDK.
IntegrationRecord = Integration

IntegrationReader = api_accessors.IntegrationReader
AuthAccessor = api_accessors.AuthAccessor
SourceKindAccessor = api_accessors.SourceKindAccessor
UsageProvider = usages.UsageProvider

IntegrationManager = GeneratedIntegrationManager()


def register_source_kinds(kinds: Mapping[str, AuthType]) -> None:
    """Register warehouse source kinds and the default auth type of each. Call it from `AppConfig.ready`."""
    source_kinds.register_source_kinds(kinds)


def register_usage_provider(provider: UsageProvider) -> None:
    """Add a provider for `usages`. A product adds `backend/integration_usages.py` instead."""
    usages.register_usage_provider(provider)
