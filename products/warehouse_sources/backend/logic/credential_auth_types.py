"""The `Integration` kind and auth type of the row that holds a source's typed-in credentials.

The kind comes from the generated `facade/credential_kinds.py`. The auth type says how the typed-in
fields authenticate. Most sources write the default auth type of their kind. A source whose kind has
an OAuth or App default (Stripe, GitHub, Slack) writes a second auth type of that kind, so code that
handles only the default auth type never gets a typed-in row.
"""

from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.integration import IntegrationAuthType, KindAuthTypes, register_kind_auth_types
from posthog.models.integration.auth_types import catalogued_kinds, default_auth_type, kind_auth_types

from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS

_A = IntegrationAuthType

# Auth types that only an OAuth grant or an App installation has. A typed-in row never has them.
INSTALLED_AUTH_TYPES = frozenset({_A.OAUTH, _A.APP})

# The auth type of a source whose typed-in row does not have the default auth type of its kind.
FIXED_AUTH_TYPES: Mapping[str, IntegrationAuthType] = {
    "AppleSearchAds": _A.KEY_PAIR,
    "AzureBlob": _A.ACCOUNT_KEY,
    "ClickUp": _A.API_KEY,
    "Firebase": _A.DATABASE_CREDENTIALS,
    "Github": _A.TOKEN,
    "GoogleCloudStorage": _A.HMAC_KEY,
    "GoogleSheets": _A.CREDENTIALS,
    "Jira": _A.API_TOKEN,
    "Resend": _A.API_KEY,
    "Slack": _A.TOKEN,
    "Stripe": _A.API_KEY,
    "Vercel": _A.API_TOKEN,
}


@frozen
class SelectedAuthType:
    """A source whose auth type depends on the option of a select field."""

    field: str
    by_option: Mapping[str, IntegrationAuthType]
    # The option the source config uses when the stored value has no selection.
    default_option: str


SELECTED_AUTH_TYPES: Mapping[str, SelectedAuthType] = {
    "Databricks": SelectedAuthType(
        field="auth_type",
        by_option={"access_token": _A.ACCESS_TOKEN, "service_principal": _A.SERVICE_PRINCIPAL},
        default_option="access_token",
    ),
    "Twilio": SelectedAuthType(
        field="auth_method",
        by_option={"auth_token": _A.AUTH_TOKEN, "api_key": _A.API_KEY},
        default_option="api_key",
    ),
}

# Kinds that `generate_source_field_classification` adds get this entry. `credentials` is the
# default of unknown kinds too, so the SQL of `with_auth` stays short for these hundreds of kinds.
GENERATED_KIND_AUTH_TYPES = KindAuthTypes(default=_A.CREDENTIALS)


class UnknownCredentialKindError(ValueError):
    """The source type has no credential kind, for example the Custom source."""


def credential_kind(source_type: str) -> str:
    try:
        return CREDENTIAL_KINDS[str(source_type)]
    except KeyError:
        raise UnknownCredentialKindError(f"Source type {source_type!r} has no credential kind") from None


def typed_in_auth_types(source_type: str) -> frozenset[IntegrationAuthType]:
    """Every auth type that a typed-in row of the source type can have."""
    selected = SELECTED_AUTH_TYPES.get(str(source_type))
    if selected is not None:
        return frozenset(selected.by_option.values())
    fixed = FIXED_AUTH_TYPES.get(str(source_type))
    return frozenset({fixed if fixed is not None else default_auth_type(credential_kind(source_type))})


def typed_in_auth_type(source_type: str, fields: Mapping[str, Any]) -> IntegrationAuthType:
    """The auth type of a typed-in row with these connection fields.

    Raises ValueError when the kind does not support the auth type, or when the auth type is one that
    only an OAuth grant or an App installation has. The generator test checks every source type.
    """
    kind = credential_kind(source_type)
    selected = SELECTED_AUTH_TYPES.get(str(source_type))
    if selected is not None:
        value = fields.get(selected.field)
        option = value.get("selection") if isinstance(value, Mapping) else value
        auth_type = selected.by_option.get(str(option or selected.default_option))
        if auth_type is None:
            raise ValueError(f"Source type {source_type!r} has no auth type for option {option!r}")
    else:
        auth_type = FIXED_AUTH_TYPES.get(str(source_type)) or default_auth_type(kind)
    if auth_type in INSTALLED_AUTH_TYPES:
        raise ValueError(f"A typed-in row of kind {kind!r} cannot have auth type {auth_type.value!r}")
    if auth_type not in kind_auth_types(kind).supported:
        raise ValueError(f"Integration kind {kind!r} does not support auth type {auth_type.value!r}")
    return auth_type


def register_credential_kinds() -> None:
    """Add each generated kind that core does not know to the auth type catalogue.

    The app config calls it at startup. Core then lists these kinds as valid stored kinds.
    """
    known = catalogued_kinds()
    for kind in sorted(set(CREDENTIAL_KINDS.values())):
        if kind not in known:
            register_kind_auth_types(kind, GENERATED_KIND_AUTH_TYPES)
