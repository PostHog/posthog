import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import (
    BUTTONDOWN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source import ButtondownSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.validate_buttondown_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source.buttondown_source"


class TestButtondownSource:
    def setup_method(self) -> None:
        self.source = ButtondownSource()
        self.team_id = 123
        self.config = ButtondownSourceConfig(api_key="bd-key")

    def test_only_endpoints_with_a_server_side_date_filter_advertise_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Advertising incremental on an endpoint with no server-side filter would page the entire
        # history on every run while claiming to be cheap.
        for name, endpoint in BUTTONDOWN_ENDPOINTS.items():
            expected = endpoint.incremental_start_param is not None
            assert schemas[name].supports_incremental is expected
            assert bool(schemas[name].incremental_fields) is expected

    def test_incremental_fields_track_creation_date(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name, endpoint in BUTTONDOWN_ENDPOINTS.items():
            if endpoint.incremental_start_param is None:
                continue
            assert [field["field"] for field in schemas[name].incremental_fields] == ["creation_date"]

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected",
        [
            ((True, 200), None, (True, None)),
            ((False, 401), None, (False, "Invalid Buttondown API key")),
            # A 403 means a real key that can't read one endpoint, so it must not block setup.
            ((False, 403), None, (True, None)),
            ((False, 403), "emails", (False, "Invalid Buttondown API key")),
            ((False, None), None, (False, "Invalid Buttondown API key")),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name) == expected

        mock_validate.assert_called_once_with("bd-key", "2026-04-01")

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions.keys()) == set(ENDPOINTS)
        for name, endpoint in BUTTONDOWN_ENDPOINTS.items():
            for primary_key in endpoint.primary_keys:
                assert primary_key in descriptions[name]["columns"]
