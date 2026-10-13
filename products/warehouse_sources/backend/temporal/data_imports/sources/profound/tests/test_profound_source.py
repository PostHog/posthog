from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.profound import (
    ProfoundSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.source import ProfoundSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.profound.source"


class _Config:
    api_key = "key"


def _driver() -> SourceDriver:
    return SourceDriver(ProfoundSource(), ProfoundSourceConfig(api_key="key"))


class TestProfoundSource:
    @parameterized.expand(
        [
            ("visibility_is_incremental", "Visibility", True),
            ("citations_is_incremental", "Citations", True),
            ("categories_is_not", "Categories", False),
            ("assets_is_not", "Assets", False),
            ("personas_is_not", "Personas", False),
        ]
    )
    def test_only_the_report_tables_are_incremental(self, _name: str, endpoint: str, expected: bool) -> None:
        # The reference lists carry no time filter, so advertising incremental would promise a cheap
        # sync that still reads everything.
        schemas = {s.name: s for s in ProfoundSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert schemas[endpoint].supports_incremental is expected

    @parameterized.expand([("Visibility",), ("Citations",)])
    def test_reports_track_the_date_column(self, endpoint: str) -> None:
        # `date` only appears on a row because the request groups by it.
        schemas = {s.name: s for s in ProfoundSource().get_schemas(None, 1)}  # type: ignore[arg-type]

        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["date"]

    @parameterized.expand([("valid", True, True), ("rejected", False, False)])
    @mock.patch(f"{SOURCE_MODULE}.validate_profound_credentials")
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: bool, mock_validate) -> None:
        mock_validate.return_value = probe_ok

        ok, message = ProfoundSource().validate_credentials(_Config(), 1)  # type: ignore[arg-type]

        assert ok is expected
        assert (message is None) is expected

    def test_version_declaration_defaults_to_v2_with_v1_supported(self) -> None:
        # Profound versions by URL path segment, so both labels resolve to the same requests;
        # the default tracks the newest label without deprecating the old one.
        source = ProfoundSource()

        assert source.supported_versions == ("v1", "v2")
        assert source.default_version == "v2"
        assert source.deprecated_versions == ()

    @parameterized.expand([("unpinned", None), ("pinned_v1", "v1"), ("pinned_v2", "v2")])
    def test_report_path_is_fixed_regardless_of_pin(self, _name: str, pinned: str | None) -> None:
        # The version is never sent on the wire — a v1 pin (existing sources) and the v2 default
        # both POST to the same `/v2/reports/...` route. This guards the byte-for-byte promise.
        result = _driver().run(
            "Visibility",
            route(
                {
                    "/v1/org/categories": [ScriptedResponse(json=[{"id": "c1"}])],
                    "/v2/reports/visibility": [ScriptedResponse(json={"info": {"next_cursor": None}, "data": []})],
                }
            ),
            api_version=pinned,
        )

        assert result.raised is None
        assert result.paths == ["/v1/org/categories", "/v2/reports/visibility"]

    @parameterized.expand([("unpinned", None), ("pinned_v1", "v1"), ("pinned_v2", "v2")])
    def test_reference_path_is_fixed_regardless_of_pin(self, _name: str, pinned: str | None) -> None:
        # The org lists only exist under `/v1/`, and no pin moves them.
        result = _driver().run("Categories", [ScriptedResponse(json=[{"id": "1"}])], api_version=pinned)

        assert result.raised is None
        assert result.paths == ["/v1/org/categories"]
