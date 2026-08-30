from typing import Any

from parameterized import parameterized

from posthog.schema import SourceConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    _BaseSource,
    error_message_matches,
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


class _RetargetableSource(_DescriptionsOnlySource):
    @property
    def connection_host_fields(self) -> list[str]:
        return ["okta_domain"]


_BASE_JOB_INPUTS: dict[str, Any] = {
    "host": "https://api.example.com",
    "okta_domain": "acme.example.com",
    "api_key": "not-a-real-key",
    "ssh_tunnel": {"enabled": True, "host": "tunnel.example.com", "port": 22, "passphrase": "not-a-real-passphrase"},
}


@parameterized.expand(
    [
        # A rotated secret or a renamed source must leave the fingerprint alone: invalidating a
        # checkpoint on every token refresh restores the never-finishing full re-walk this keying
        # exists to prevent.
        ("rotated_secret", {"api_key": "also-not-a-real-key"}, False),
        ("renamed_tunnel_passphrase", {"ssh_tunnel": {**_BASE_JOB_INPUTS["ssh_tunnel"], "passphrase": "other"}}, False),
        # Each of these repoints the source, so a cursor captured against the old target — often a
        # whole URL — must not survive to be replayed against the new one.
        ("repointed_host", {"host": "https://api.evil.example.com"}, True),
        ("repointed_source_specific_host", {"okta_domain": "other.example.com"}, True),
        ("repointed_tunnel", {"ssh_tunnel": {**_BASE_JOB_INPUTS["ssh_tunnel"], "host": "other.example.com"}}, True),
    ]
)
def test_connection_target_fingerprint_tracks_only_the_target(_name, overrides, expected_change) -> None:
    source = _RetargetableSource()
    before = source.connection_target_fingerprint(_BASE_JOB_INPUTS)

    after = source.connection_target_fingerprint({**_BASE_JOB_INPUTS, **overrides})

    assert (before != after) is expected_change


def test_connection_target_fingerprint_is_none_for_a_source_without_a_target() -> None:
    # Most sources reach a fixed vendor API. They must stay on the plain key rather than pick up an
    # empty-dict digest that would change the moment an unrelated field is added here.
    assert _DescriptionsOnlySource().connection_target_fingerprint({"api_key": "not-a-real-key"}) is None
    assert _DescriptionsOnlySource().connection_target_fingerprint(None) is None
