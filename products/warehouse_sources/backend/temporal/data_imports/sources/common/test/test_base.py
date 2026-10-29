from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.aws_auth import (
    AWS_FLAT_STORED_SELECTS,
    aws_auth_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    _BaseSource,
    error_message_matches,
    nest_flat_select_containers,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.types import ExternalDataSourceType


class _DescriptionsOnlySource(_BaseSource[Config]):
    # Only the descriptions matter here; the hook under test never reaches the rest of the surface.
    @property
    def source_type(self) -> ExternalDataSourceType:
        raise NotImplementedError()

    @property
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError()

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return {"widgets": {"description": "A widget."}}


def test_table_prefix_hook_defaults_to_the_plain_descriptions() -> None:
    # Almost no source overrides this, so a default that dropped or emptied the descriptions
    # would silently strip curated docs from every one of them on the enrichment path.
    source = _DescriptionsOnlySource()

    result = source.get_canonical_descriptions_for_table_prefix("acme_")

    assert result == {"widgets": {"description": "A widget."}}


@parameterized.expand(
    [
        (
            "exact_case_match",
            "401 Client Error: Unauthorized for url: https://www.eventbriteapi.com/v3/users/me/organizations/",
            ["401 Client Error: Unauthorized for url: https://www.eventbriteapi.com"],
            True,
        ),
        (
            "vendor_returns_non_standard_reason_phrase_casing",
            "401 Client Error: UNAUTHORIZED for url: https://www.eventbriteapi.com/v3/users/me/organizations/",
            ["401 Client Error: Unauthorized for url: https://www.eventbriteapi.com"],
            True,
        ),
        (
            "no_pattern_matches",
            "500 Server Error: Internal Server Error for url: https://example.com",
            ["401 Client Error: Unauthorized for url: https://example.com"],
            False,
        ),
        (
            "empty_patterns",
            "any error message",
            [],
            False,
        ),
    ]
)
def test_error_message_matches(_name, error_msg, patterns, expected):
    assert error_message_matches(error_msg, patterns) is expected


@parameterized.expand(
    [
        (
            "flat_keys",
            {"aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "secret"},
            {"selection": "access_keys", "aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "secret"},
        ),
        (
            "role_named_by_a_bare_selection",
            {"aws_auth": "role", "aws_integration_id": 5},
            {"selection": "role", "aws_integration_id": 5},
        ),
    ]
)
def test_nest_flat_select_containers_keeps_the_chosen_branch(_name: str, job_inputs: dict, expected: dict) -> None:
    nested = nest_flat_select_containers(job_inputs, [aws_auth_field()], AWS_FLAT_STORED_SELECTS)

    assert nested == {"aws_auth": expected}
