from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source import MistralAISource


class TestGetSchemas:
    @parameterized.expand(
        [
            ("fine_tuning_jobs", True),
            ("batch_jobs", True),
            ("files", False),
            ("models", False),
            ("agents", False),
            ("conversations", False),
            ("libraries", False),
        ]
    )
    def test_incremental_only_where_server_filter_exists(self, endpoint: str, supports_incremental: bool) -> None:
        # Only fine-tuning and batch jobs expose a server-side created_after filter; the rest must ship
        # full refresh, never advertise incremental they can't honor.
        schemas = {s.name: s for s in MistralAISource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if supports_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    @parameterized.expand([("agents", False), ("conversations", False), ("libraries", False), ("files", True)])
    def test_beta_endpoints_off_by_default(self, endpoint: str, should_sync_default: bool) -> None:
        schemas = {s.name: s for s in MistralAISource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].should_sync_default is should_sync_default

    def test_names_filter(self) -> None:
        schemas = MistralAISource().get_schemas(MagicMock(), team_id=1, names=["files", "models"])
        assert {s.name for s in schemas} == {"files", "models"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Mistral AI API key"))])
    def test_maps_probe_result(self, _name: str, probe: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.source.validate_mistral_ai_credentials",
            return_value=probe,
        ):
            result = MistralAISource().validate_credentials(MagicMock(api_key="sk-x"), team_id=1)
        assert result == expected
