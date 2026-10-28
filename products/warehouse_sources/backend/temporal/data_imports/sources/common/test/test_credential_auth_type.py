import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.credential_auth_types import CREDENTIAL_AUTH_TYPES
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_auth_type import (
    CREDENTIAL_AUTH_TYPES_PATH,
    compute_credential_auth_types,
    derive_credential_auth_type,
    render_credential_auth_types,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@pytest.mark.parametrize(
    "source_type,expected",
    [
        # One secret input.
        (ExternalDataSourceType.ABLY, "token"),
        (ExternalDataSourceType.KLAVIYO, "token"),
        # An auth method select with an OAuth option and one typed-in option that holds one secret.
        (ExternalDataSourceType.STRIPE, "token"),
        (ExternalDataSourceType.GITHUB, "token"),
        # Only an OAuth field.
        (ExternalDataSourceType.HUBSPOT, "oauth"),
        (ExternalDataSourceType.GOOGLEADS, "oauth"),
        # Several typed-in fields.
        (ExternalDataSourceType.POSTGRES, "credentials"),
        (ExternalDataSourceType.MYSQL, "credentials"),
        (ExternalDataSourceType.ZENDESK, "credentials"),
    ],
)
def test_derive_credential_auth_type(source_type: ExternalDataSourceType, expected: str) -> None:
    assert derive_credential_auth_type(source_type) == expected


def test_every_credential_kind_has_an_auth_type() -> None:
    assert set(CREDENTIAL_AUTH_TYPES) == set(CREDENTIAL_KINDS.values())
    assert set(CREDENTIAL_AUTH_TYPES.values()) <= {"oauth", "token", "credentials"}


def test_credential_auth_types_file_is_up_to_date() -> None:
    assert dict(CREDENTIAL_AUTH_TYPES) == compute_credential_auth_types()
    assert CREDENTIAL_AUTH_TYPES_PATH.read_text() == render_credential_auth_types(), (
        "The credential auth types are out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
