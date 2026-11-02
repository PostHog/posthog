from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source import AviationstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aviationstack import (
    AviationstackSourceConfig,
)


def _make_config(access_key: str = "key", airport_iata_codes: str | None = "JFK") -> AviationstackSourceConfig:
    return AviationstackSourceConfig(access_key=access_key, airport_iata_codes=airport_iata_codes)


class TestAviationstackSource:
    def test_only_the_access_key_field_is_secret(self) -> None:
        fields = AviationstackSource().get_source_config.fields
        inputs = [field for field in fields if isinstance(field, SourceFieldInputConfig)]
        assert len(inputs) == len(fields)
        assert [field.name for field in inputs if field.secret] == ["access_key"]
        access_key_field = inputs[0]
        # The access key is a secret credential, so it must render as a password input.
        assert access_key_field.type == "password"
        assert access_key_field.secret is True
        assert access_key_field.required is True

    @parameterized.expand([("timetable",), ("flights_future",)])
    def test_validate_credentials_rejects_per_airport_table_without_airports(self, schema_name: str) -> None:
        # The probe must not even run: a valid key still cannot sync these tables with no airport.
        with scripted_network([]) as network:
            ok, message = AviationstackSource().validate_credentials(
                _make_config(airport_iata_codes=None), team_id=1, schema_name=schema_name
            )

        assert ok is False
        assert message is not None and "airport IATA code" in message
        assert network.requests_log == []

    def test_validate_credentials_ignores_airports_for_other_tables(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            ok, _ = AviationstackSource().validate_credentials(
                _make_config(airport_iata_codes=None), team_id=1, schema_name="airlines"
            )

        assert ok is True
        assert len(network.requests_log) == 1

    def test_source_for_pipeline_keyless_for_flight_feeds(self) -> None:
        result = SourceDriver(AviationstackSource(), _make_config()).run(
            "flights", [ScriptedResponse(json={"data": [], "pagination": {"total": 0}})]
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys is None

    @parameterized.expand(
        [
            ("body_invalid_key", "aviationstack API error [invalid_access_key]"),
            ("body_usage_limit", "aviationstack API error [usage_limit_reached]"),
            ("body_function_restricted", "aviationstack API error [function_access_restricted]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = AviationstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
