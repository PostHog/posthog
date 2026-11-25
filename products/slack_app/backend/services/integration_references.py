"""Store and read a reference to an integration row on a slack_app model, in the form the integrations SDK sets.

See "Store a reference outside a serializer" in ``posthog/integrations/README.md``.
"""

from posthog.integrations.references import IntegrationReference


def store_integration_id(integration_id: int | None) -> str | None:
    return str(IntegrationReference.from_legacy_id(integration_id)) if integration_id is not None else None


def read_integration_id(stored: str | None) -> int | None:
    """The int id that the SDK accessors take. A reference that cannot resolve yet, such as a UUID, is None."""
    if not stored:
        return None
    try:
        return IntegrationReference.parse(stored).legacy_id
    except ValueError:
        return None
