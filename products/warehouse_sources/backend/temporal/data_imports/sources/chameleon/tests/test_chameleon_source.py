from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon import ChameleonResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.source import ChameleonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(secret: str = "secret") -> MagicMock:
    config = MagicMock()
    config.account_secret = secret
    return config


class TestChameleonSourceConfig:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CHAMELEON

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_single_secret_field_is_a_required_password(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "account_secret"
        assert field.required is True
        assert field.type.value == "password"
        assert field.secret is True

    def test_docs_url_matches_doc_filename(self) -> None:
        assert self.source.get_source_config.docsUrl == "https://posthog.com/docs/cdp/sources/chameleon"

    def test_stays_unreleased_alpha(self) -> None:
        config = self.source.get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus is not None
        assert config.releaseStatus.value == "alpha"


class TestChameleonSchemas:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_names_filter_narrows_output(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["tours"])
        assert [s.name for s in schemas] == ["tours"]

    def test_responses_describes_fan_out(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        assert "Full refresh" in (schemas["responses"].description or "")


class TestChameleonCredentials:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Invalid Chameleon account secret")),
            ("unreachable", (False, "Could not reach Chameleon to validate the account secret. Please try again.")),
        ]
    )
    def test_validate_credentials_propagates_probe_result(
        self, _name: str, probe_result: tuple[bool, str | None]
    ) -> None:
        with patch.object(source_module, "validate_chameleon_credentials", return_value=probe_result):
            result = self.source.validate_credentials(_config(), team_id=1)
        assert result == probe_result

    def test_403_is_non_retryable(self) -> None:
        observed = "403 Client Error: Forbidden for url: https://api.chameleon.io/v3/edit/segments?limit=500"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.chameleon.io/v3/edit/tours"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.chameleon.io"),
            ("read_timeout", "HTTPSConnectionPool(host='api.chameleon.io', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in self.source.get_non_retryable_errors())


class TestChameleonPipelineWiring:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChameleonResumeConfig

    def test_source_for_pipeline_passes_secret_and_schema_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "profiles"
        manager = MagicMock()
        with patch.object(source_module, "chameleon_source") as chameleon_source_mock:
            self.source.source_for_pipeline(_config("my-secret"), manager, inputs)
        chameleon_source_mock.assert_called_once_with(
            account_secret="my-secret",
            endpoint="profiles",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(ENDPOINTS).issubset(set(descriptions))
