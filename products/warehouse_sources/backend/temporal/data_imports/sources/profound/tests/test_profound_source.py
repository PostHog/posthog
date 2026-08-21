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
