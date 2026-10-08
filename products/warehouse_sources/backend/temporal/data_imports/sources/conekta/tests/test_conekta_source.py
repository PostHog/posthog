import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta import ConektaResumeConfig
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
