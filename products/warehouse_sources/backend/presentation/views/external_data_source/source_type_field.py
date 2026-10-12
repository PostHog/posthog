from typing import Any

from rest_framework import serializers

from products.warehouse_sources.backend.facade.source_management import known_source_key


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
            return known_source_key(value)
        except ValueError:
            self.fail("unknown", value=value)
