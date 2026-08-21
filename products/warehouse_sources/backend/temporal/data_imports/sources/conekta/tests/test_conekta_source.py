import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import (
    API_VERSION,
    CONEKTA_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.source import ConektaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.conekta import (
    ConektaSourceConfig,
)

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.conekta.source.api_client"


class TestConektaSource:
    def setup_method(self):
        self.source = ConektaSource()
        self.team_id = 123
        self.config = ConektaSourceConfig(api_key="key_priv")

    def test_declared_version_is_the_one_the_transport_sends(self):
        # A pin the code doesn't actually send makes every deprecation warning and upgrade path wrong.
        assert self.source.default_version == API_VERSION
        assert self.source.supported_versions == (API_VERSION,)

    def test_canonical_descriptions_document_the_partition_key(self):
        for name, config in CONEKTA_ENDPOINTS.items():
            if config.partition_key:
                assert config.partition_key in CANONICAL_DESCRIPTIONS[name]["columns"]

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message_fragment",
        [
            ((True, 200), True, None),
            ((False, 401), False, "private key"),
            ((False, 500), False, "Could not reach"),
            ((False, None), False, "Could not reach"),
        ],
    )
    def test_validate_credentials_status_mapping(self, probe_result, expected_valid, expected_message_fragment):
        with mock.patch(API_CLIENT_PATCH) as api_client:
            api_client.validate_credentials.return_value = probe_result

            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message

    def test_validate_credentials_probes_the_resolved_version(self):
        with mock.patch(API_CLIENT_PATCH) as api_client:
            api_client.validate_credentials.return_value = (True, 200)

            self.source.validate_credentials(self.config, self.team_id, api_version=None)

        assert api_client.validate_credentials.call_args.args == ("key_priv", API_VERSION)
