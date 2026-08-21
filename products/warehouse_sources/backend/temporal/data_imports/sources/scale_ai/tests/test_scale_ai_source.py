from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source import ScaleAISource


class TestScaleAISchemas:
    def test_lists_all_endpoints(self) -> None:
        schemas = ScaleAISource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == {"tasks", "batches", "projects"}

    @parameterized.expand(
        [
            ("tasks", True, ["task_id"], ["updated_at", "created_at"]),
            ("batches", True, ["name"], ["created_at"]),
            ("projects", False, ["name"], []),
        ]
    )
    def test_schema_incremental_and_keys(
        self, name: str, incremental: bool, primary_keys: list[str], incremental_fields: list[str]
    ) -> None:
        schemas = {s.name: s for s in ScaleAISource().get_schemas(MagicMock(), team_id=1)}
        schema = schemas[name]
        assert schema.supports_incremental is incremental
        assert schema.detected_primary_keys == primary_keys
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields

    def test_names_filter(self) -> None:
        schemas = ScaleAISource().get_schemas(MagicMock(), team_id=1, names=["tasks"])
        assert [s.name for s in schemas] == ["tasks"]


class TestScaleAICredentials:
    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Scale AI API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        config = MagicMock(api_key="live_key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.source.validate_scale_ai_credentials",
            return_value=probe_result,
        ):
            assert ScaleAISource().validate_credentials(config, team_id=1) == expected
