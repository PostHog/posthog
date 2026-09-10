import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.source import GainsightCsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightcs import (
    GainsightCsSourceConfig,
)

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.source."
    "validate_gainsight_cs_credentials"
)


def _config(custom_objects: str | None = None) -> GainsightCsSourceConfig:
    return GainsightCsSourceConfig(
        domain="acme.gainsightcloud.com",
        access_key="key",
        custom_objects=custom_objects,
    )


class TestGainsightCsSourceSchemas:
    def test_offers_validated_custom_objects_alongside_the_standard_catalog(self) -> None:
        names = [schema.name for schema in GainsightCsSource().get_schemas(_config("health__gc, bad name"), team_id=1)]

        assert "company" in names
        assert "health__gc" in names
        assert "bad name" not in names


class TestGainsightCsSourceCredentials:
    def test_probes_the_object_behind_the_schema_being_checked(self) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=(True, None)) as validate:
            GainsightCsSource().validate_credentials(_config("health__gc"), team_id=1, schema_name="health__gc")

        assert validate.call_args.args[2] == "health__gc"

    def test_probes_company_when_no_schema_is_named(self) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=(True, None)) as validate:
            GainsightCsSource().validate_credentials(_config(), team_id=1)

        assert validate.call_args.args[2] == "company"

    def test_reports_an_unknown_schema_without_calling_gainsight(self) -> None:
        with mock.patch(VALIDATE_PATCH) as validate:
            ok, error = GainsightCsSource().validate_credentials(_config(), team_id=1, schema_name="not_an_object")

        assert ok is False
        assert error is not None and "Unknown Gainsight object" in error
        validate.assert_not_called()


class TestGainsightCsSourcePipeline:
    def test_refuses_a_schema_that_is_neither_standard_nor_declared_custom(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "dropped_by_validation"

        with pytest.raises(ValueError, match="Unknown Gainsight object"):
            GainsightCsSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)
