"""The `Integration` kind and auth type of the row that holds a source's typed-in credentials.

The kind comes from the generated `facade/credential_kinds.py`, and the auth type from the generated
`facade/credential_auth_types.py`. A source type has exactly one of each. On a catalogue kind with an
OAuth default, such as `stripe`, the typed-in row has a second auth type (`token`), so code that reads
the OAuth rows of the kind never gets a typed-in row.
"""

from posthog.integrations import AuthAccessor, AuthType, IntegrationManager

from products.warehouse_sources.backend.facade.credential_auth_types import CREDENTIAL_AUTH_TYPES
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS


class UnknownCredentialKindError(ValueError):
    """The source type has no credential kind, for example the Custom source."""


def credential_kind(source_type: str) -> str:
    try:
        return CREDENTIAL_KINDS[str(source_type)]
    except KeyError:
        raise UnknownCredentialKindError(f"Source type {source_type!r} has no credential kind") from None


def typed_in_auth_type(source_type: str) -> AuthType:
    """The auth type of the typed-in row of the source type.

    Raises ValueError for a source that has only OAuth fields, because such a source has no typed-in row.
    """
    auth_type = AuthType(CREDENTIAL_AUTH_TYPES[credential_kind(source_type)])
    if auth_type == AuthType.OAUTH:
        raise ValueError(f"Source type {source_type!r} has no typed-in credentials")
    return auth_type


def credentials_accessor(source_type: str) -> AuthAccessor:
    """The SDK accessor of the typed-in rows of the source type: its kind, its auth type, marked rows only."""
    rows = IntegrationManager.source(credential_kind(source_type))
    return rows.token if typed_in_auth_type(source_type) == AuthType.TOKEN else rows.credentials
