from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.source import RKICovidSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.source"


def _make_config(history_days: int | None = None) -> Any:
    config = MagicMock()
    config.history_days = history_days
    return config


class TestRKICovidSource:
    def test_source_type(self) -> None:
        assert RKICovidSource().source_type == ExternalDataSourceType.RKICOVID

    def test_source_config_is_released_alpha(self) -> None:
        config = RKICovidSource().get_source_config
        # A finished source must stay visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/rki-covid"

    def test_source_config_history_days_field_is_optional(self) -> None:
        config = RKICovidSource().get_source_config
        assert [f.name for f in config.fields] == ["history_days"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == "number"
        assert field.required is False
        assert field.secret is False

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert RKICovidSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = RKICovidSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # The API has no server-side timestamp cursor, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_exposes_primary_keys(self) -> None:
        schemas = {s.name: s for s in RKICovidSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["germany"].detected_primary_keys is None
        assert schemas["germany_age_groups"].detected_primary_keys == ["age_group"]
        assert schemas["states"].detected_primary_keys == ["abbreviation"]
        assert schemas["districts"].detected_primary_keys == ["ags"]
        assert schemas["germany_history_cases"].detected_primary_keys == ["date"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = RKICovidSource().get_schemas(_make_config(), team_id=1, names=["germany", "states"])
        assert {s.name for s in schemas} == {"germany", "states"}

    @parameterized.expand(
        [
            ("no_days_reachable", None, True, True),
            ("valid_days_reachable", 90, True, True),
            ("unreachable", None, False, False),
        ]
    )
    def test_validate_credentials(self, _name: str, days: int | None, probe_result: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_connection", return_value=probe_result):
            ok, message = RKICovidSource().validate_credentials(_make_config(days), team_id=1)
        assert ok is expected_ok
        assert (message is None) is expected_ok

    def test_validate_credentials_rejects_invalid_days_without_probing(self) -> None:
        with patch(f"{MODULE}.validate_connection") as probe:
            ok, message = RKICovidSource().validate_credentials(_make_config(0), team_id=1)
        assert ok is False
        assert message is not None and "History window" in message
        probe.assert_not_called()

    def test_source_for_pipeline_plumbs_endpoint_and_history_days(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "germany_history_cases"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.rki_covid_source") as source_fn:
            RKICovidSource().source_for_pipeline(_make_config(30), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["endpoint"] == "germany_history_cases"
        assert kwargs["history_days"] == 30

    def test_source_for_pipeline_rejects_invalid_history_days(self) -> None:
        # A previously-saved bad config must fail the run loudly instead of syncing a wrong window.
        inputs = MagicMock()
        inputs.schema_name = "germany_history_cases"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.rki_covid_source") as source_fn:
            with pytest.raises(ValueError, match="History window"):
                RKICovidSource().source_for_pipeline(_make_config(-1), inputs)
        source_fn.assert_not_called()

    def test_non_retryable_errors_cover_endpoint_drift(self) -> None:
        errors = RKICovidSource().get_non_retryable_errors()
        assert "404 Client Error: Not Found for url: https://api.corona-zahlen.org" in errors
        assert "RKI COVID-19 API error [unexpected_response]" in errors

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = RKICovidSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "germany" in descriptions
        assert "districts" in descriptions
