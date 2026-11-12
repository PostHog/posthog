from typing import Any

from rest_framework import serializers

from products.warehouse_sources.backend.facade.source_config import SourceKey
from products.warehouse_sources.backend.facade.source_management import SourceRegistry, known_source_key
from products.warehouse_sources.backend.presentation.views.external_data_source.source_type_resolver import (
    resolve_source_type,
)


def resolve_known_source_key(value: str) -> SourceKey:
    """Resolve a submitted name to its registry key, ignoring case, spaces, hyphens and underscores.

    Raises ValueError when the name matches no registered source.
    """
    try:
        return known_source_key(value)
    except ValueError:
        canonical = resolve_source_type(value, (str(key) for key in SourceRegistry.get_registered_types()))
        if canonical is None:
            raise
        return known_source_key(canonical)


class SourceTypeField(serializers.CharField):
    """A warehouse source key, such as 'Stripe' or 'Postgres', checked against the source registry.

    The API schema publishes it as a plain string, not an enum. A plugin source names itself with a key
    that has no `ExternalDataSourceType` member, and adding a vendor must not change the generated
    API clients.
    """

    default_error_messages = {
        "unknown": "'{value}' is not a known source type. The wizard endpoint lists the available source types.",
    }

    def to_internal_value(self, data: Any) -> str:
        value = super().to_internal_value(data)
        try:
            return resolve_known_source_key(value)
        except ValueError:
            self.fail("unknown", value=value)
