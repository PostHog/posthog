import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta import ConektaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import (
    API_VERSION,
    CONEKTA_ENDPOINTS,
    ENDPOINTS,
    MERGE_ONLY_ENDPOINTS,
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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Conekta"
        assert config.label == "Conekta"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source must ship visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/conekta"

    def test_declared_version_is_the_one_the_transport_sends(self):
        # A pin the code doesn't actually send makes every deprecation warning and upgrade path wrong.
        assert self.source.default_version == API_VERSION
        assert self.source.supported_versions == (API_VERSION,)

    @pytest.mark.parametrize(
        "observed_error, matches",
        [
            ("401 Client Error: Unauthorized for url: https://api.conekta.io/orders?limit=250", True),
            ("403 Client Error: Forbidden for url: https://api.conekta.io/payout_orders", True),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers", False),
            ("500 Server Error for url: https://api.conekta.io/orders", False),
        ],
    )
    def test_non_retryable_errors_match_only_conekta_auth_failures(self, observed_error, matches):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors()) is matches

    def test_only_orders_is_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # `/orders` is the only endpoint documenting server-side `created_at.gte` / `updated_at.gte`
        # filters; claiming incremental anywhere else would page the whole endpoint every run.
        assert {schema.name for schema in schemas if schema.supports_incremental} == {"orders"}

    def test_incremental_schemas_are_merge_only(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name in MERGE_ONLY_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            # `.gte` is inclusive, so the watermark row comes back every run; append would duplicate it.
            assert schemas[name].supports_append is False

    def test_canonical_descriptions_cover_every_schema(self):
        # A renamed endpoint would silently orphan its curated descriptions and fall back to the LLM.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

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

    def test_get_resumable_source_manager_is_bound_to_the_resume_dataclass(self):
        inputs = mock.MagicMock()
        inputs.job_id = "job"
        inputs.schema_id = "schema"

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        # A manager bound to the wrong dataclass fails to deserialize its own Redis state on resume.
        assert manager._data_class is ConektaResumeConfig

    def test_source_for_pipeline_passes_the_users_incremental_selection_through(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = self.team_id
        inputs.job_id = "job"
        inputs.incremental_field = "created_at"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1676328434
        inputs.api_version = None
        manager = mock.MagicMock()

        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = api_client.conekta_source.call_args.kwargs
        assert kwargs["endpoint"] == "orders"
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == 1676328434
        assert kwargs["api_version"] == API_VERSION

    def test_source_for_pipeline_withholds_the_watermark_on_a_full_refresh(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "charges"
        inputs.team_id = self.team_id
        inputs.job_id = "job"
        inputs.incremental_field = None
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1676328434
        inputs.api_version = None

        with mock.patch(API_CLIENT_PATCH) as api_client:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert api_client.conekta_source.call_args.kwargs["db_incremental_field_last_value"] is None
