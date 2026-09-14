from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source import AviationstackSource


def _make_manager() -> Any:
    manager = MagicMock()
    manager.can_resume.return_value = False
    return manager


def _make_config(access_key: str = "key", airport_iata_codes: str | None = "JFK") -> Any:
    config = MagicMock()
    config.access_key = access_key
    config.airport_iata_codes = airport_iata_codes
    config.flights_future_days = None
    return config


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

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = AviationstackSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # aviationstack has no server-side updated-at cursor, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = AviationstackSource().get_schemas(_make_config(), team_id=1, names=["airlines", "airports"])
        assert {s.name for s in schemas} == {"airlines", "airports"}

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid aviationstack access key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, expected_message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source.validate_aviationstack_credentials",
            return_value=probe_result,
        ):
            ok, message = AviationstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    @parameterized.expand([("timetable",), ("flights_future",)])
    def test_validate_credentials_rejects_per_airport_table_without_airports(self, schema_name: str) -> None:
        # The probe must not even run: a valid key still cannot sync these tables with no airport.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source.validate_aviationstack_credentials",
            return_value=True,
        ) as probe:
            ok, message = AviationstackSource().validate_credentials(
                _make_config(airport_iata_codes=None), team_id=1, schema_name=schema_name
            )
        assert ok is False
        assert message is not None and "airport IATA code" in message
        probe.assert_not_called()

    def test_validate_credentials_ignores_airports_for_other_tables(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source.validate_aviationstack_credentials",
            return_value=True,
        ):
            ok, _ = AviationstackSource().validate_credentials(
                _make_config(airport_iata_codes=None), team_id=1, schema_name="airlines"
            )
        assert ok is True

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "airlines"
        inputs.logger = MagicMock()
        response = AviationstackSource().source_for_pipeline(_make_config("abc"), _make_manager(), inputs)

        assert response.name == "airlines"
        # Reference tables carry a stable row id.
        assert response.primary_keys == ["id"]

    def test_source_for_pipeline_plumbs_the_airport_list(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "timetable"
        inputs.logger = MagicMock()

        # Without the airport list reaching the transport, the per-airport feeds cannot be planned.
        response = AviationstackSource().source_for_pipeline(_make_config(), _make_manager(), inputs)

        assert response.name == "timetable"
        assert response.primary_keys is None

    def test_source_for_pipeline_keyless_for_flight_feeds(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "flights"
        inputs.logger = MagicMock()
        response = AviationstackSource().source_for_pipeline(_make_config(), _make_manager(), inputs)
        assert response.primary_keys is None

    @parameterized.expand(
        [
            ("http_unauthorized", "401 Client Error: Unauthorized for url: https://api.aviationstack.com"),
            ("body_invalid_key", "aviationstack API error [invalid_access_key]"),
            ("body_usage_limit", "aviationstack API error [usage_limit_reached]"),
            ("body_function_restricted", "aviationstack API error [function_access_restricted]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = AviationstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = AviationstackSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "flights" in descriptions
        assert "airlines" in descriptions
        assert "timetable" in descriptions
        assert "flights_future" in descriptions
