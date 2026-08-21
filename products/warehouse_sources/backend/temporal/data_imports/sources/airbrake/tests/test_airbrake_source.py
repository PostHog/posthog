from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source import AirbrakeSource


class TestAirbrakeSource:
    def test_get_schemas_returns_static_catalog(self) -> None:
        schemas = {s.name: s for s in AirbrakeSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"projects", "groups", "deploys", "notices"}

        # groups is the only endpoint with a server-side time filter (start_time on createdAt).
        assert schemas["groups"].supports_incremental is True
        assert [f["field"] for f in schemas["groups"].incremental_fields] == ["createdAt"]
        for full_refresh_only in ("projects", "deploys", "notices"):
            assert schemas[full_refresh_only].supports_incremental is False, full_refresh_only
            assert schemas[full_refresh_only].incremental_fields == []

        # notices is the API-expensive two-level fan-out and must stay opt-in.
        assert schemas["notices"].should_sync_default is False
        assert schemas["projects"].should_sync_default is True

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = AirbrakeSource().get_schemas(MagicMock(), team_id=1, names=["groups"])
        assert [s.name for s in schemas] == ["groups"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Airbrake user API key"))])
    def test_validate_credentials(self, _name: str, transport_result: bool, expected: tuple) -> None:
        config = MagicMock()
        config.api_key = "user-key"
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source.validate_airbrake_credentials",
            return_value=transport_result,
        ) as validate:
            assert AirbrakeSource().validate_credentials(config, team_id=1) == expected
        validate.assert_called_once_with("user-key")
