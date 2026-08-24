import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import urlparse

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.source import ProfoundSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.profound.source"
PROFOUND_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound"
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _capture_paths(mock_session: mock.MagicMock, body: Any) -> list[str]:
    """Wire a mock REST session that returns `body` and records each request's URL path."""
    session = mock_session.return_value
    session.headers = {}
    paths: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        paths.append(urlparse(request.url).path)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    page = Response()
    page.status_code = 200
    page._content = json.dumps(body).encode()
    session.send.return_value = page
    return paths


class _Config:
    api_key = "key"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Visibility",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


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

    @mock.patch(f"{SOURCE_MODULE}.profound_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_source) -> None:
        # A stale watermark would shorten the report window a user asked to re-import in full.
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-06-01")

        ProfoundSource().source_for_pipeline(_Config(), mock.MagicMock(), inputs)  # type: ignore[arg-type]

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_version_declaration_defaults_to_v2_with_v1_supported(self) -> None:
        # Profound versions by URL path segment, so both labels resolve to the same requests;
        # the default tracks the newest label without deprecating the old one.
        source = ProfoundSource()

        assert source.supported_versions == ("v1", "v2")
        assert source.default_version == "v2"
        assert source.deprecated_versions == ()

    @parameterized.expand([("unpinned", None), ("pinned_v1", "v1"), ("pinned_v2", "v2")])
    @mock.patch(f"{PROFOUND_MODULE}.fetch_category_ids", return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_path_is_fixed_regardless_of_pin(
        self, _name: str, pinned: str | None, MockSession, _mock_categories
    ) -> None:
        # The version is never sent on the wire — a v1 pin (existing sources) and the v2 default
        # both POST to the same `/v2/reports/...` route. This guards the byte-for-byte promise.
        paths = _capture_paths(MockSession, {"info": {"next_cursor": None}, "data": []})
        inputs = _inputs(schema_name="Visibility", api_version=pinned)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = ProfoundSource().source_for_pipeline(_Config(), manager, inputs)  # type: ignore[arg-type]
        list(cast(Iterable[Any], response.items()))

        assert paths and paths[0] == "/v2/reports/visibility"

    @parameterized.expand([("unpinned", None), ("pinned_v1", "v1"), ("pinned_v2", "v2")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_path_is_fixed_regardless_of_pin(self, _name: str, pinned: str | None, MockSession) -> None:
        # The org lists only exist under `/v1/`, and no pin moves them.
        paths = _capture_paths(MockSession, [{"id": "1"}])
        inputs = _inputs(schema_name="Categories", api_version=pinned)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        response = ProfoundSource().source_for_pipeline(_Config(), manager, inputs)  # type: ignore[arg-type]
        list(cast(Iterable[Any], response.items()))

        assert paths and paths[0] == "/v1/org/categories"

    def test_source_is_visible_and_labelled_alpha(self) -> None:
        # unreleasedSource=True hides the connector from users entirely; this source is finished.
        config = ProfoundSource().get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.category is not None
        assert config.iconPath == "/static/services/profound.png"
