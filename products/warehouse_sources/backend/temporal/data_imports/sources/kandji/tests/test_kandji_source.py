import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kandji import KandjiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.source import KandjiSource


class TestKandjiSource:
    def setup_method(self) -> None:
        self.source = KandjiSource()
        self.team_id = 123
        self.config = KandjiSourceConfig(api_token="tok", subdomain="accuhive", region="us")

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # Kandji exposes no server-side updated-since cursor, so no stream is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping either field would let an editor retarget the stored bearer token at a host
        # they control without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["subdomain", "region"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://accuhive.api.kandji.io/api/v1/devices",
            "403 Client Error: Forbidden for url: https://accuhive.api.kandji.io/api/v1/devices",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "503 Server Error for url: https://accuhive.api.kandji.io/api/v1/devices" for key in non_retryable
        )
