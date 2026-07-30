from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb import (
    LinearbResumeConfig,
    _get_headers,
    _iter_list_rows,
    _iter_measurements_rows,
    _sanitize_metric_key,
    linearb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.settings import (
    ENDPOINTS,
    LINEARB_ENDPOINTS,
    LinearbEndpointConfig,
)


def _response(status_code: int = 200, payload: Any = None, content: bytes = b"x") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.content = content
    response.json.return_value = payload
    return response


def _session_returning(responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.request.side_effect = responses
    return session


def _list_config(page_size: int = 2) -> LinearbEndpointConfig:
    return LinearbEndpointConfig(name="teams", path="/api/v2/teams", page_size_param="page_size", page_size=page_size)


class TestHeaders:
    def test_sets_api_key_header(self) -> None:
        headers = _get_headers("secret-key")
        assert headers["x-api-key"] == "secret-key"
        assert headers["Content-Type"] == "application/json"


class TestSanitizeMetricKey:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("branch.computed.cycle_time:p75", "branch_computed_cycle_time_p75"),
            ("releases.count", "releases_count"),
            ("organization_id", "organization_id"),
            ("pr.merged.without.review.count", "pr_merged_without_review_count"),
        ],
    )
    def test_sanitize(self, raw: str, expected: str) -> None:
        assert _sanitize_metric_key(raw) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (403, False), (401, False), (500, False)],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb.make_tracked_session")
    def test_status_mapping(self, mock_make_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=status_code)
        mock_make_session.return_value = session

        assert validate_credentials("key") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb.make_tracked_session")
    def test_network_error_is_invalid(self, mock_make_session: mock.MagicMock) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        mock_make_session.return_value = session

        assert validate_credentials("key") is False


class TestListPagination:
    def _manager(self) -> mock.MagicMock:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        return manager

    def test_paginates_until_total_reached(self) -> None:
        # total=3 with page_size=2 -> a full page then a final short page.
        responses = [
            _response(payload={"total": 3, "items": [{"id": 1}, {"id": 2}]}),
            _response(payload={"total": 3, "items": [{"id": 3}]}),
        ]
        session = _session_returning(responses)

        pages = list(_iter_list_rows(session, {}, mock.MagicMock(), _list_config(), self._manager()))

        assert [row["id"] for page in pages for row in page] == [1, 2, 3]
        assert session.request.call_count == 2

    def test_stops_when_total_covered_without_extra_request(self) -> None:
        # A single full page whose total says we already have everything must not fetch again.
        responses = [_response(payload={"total": 2, "items": [{"id": 1}, {"id": 2}]})]
        session = _session_returning(responses)

        pages = list(_iter_list_rows(session, {}, mock.MagicMock(), _list_config(), self._manager()))

        assert [row["id"] for page in pages for row in page] == [1, 2]
        assert session.request.call_count == 1

    def test_stops_on_empty_page(self) -> None:
        session = _session_returning([_response(payload={"total": 0, "items": []})])
        pages = list(_iter_list_rows(session, {}, mock.MagicMock(), _list_config(), self._manager()))
        assert pages == []

    def test_single_page_endpoint_without_paging_params_fetches_once(self) -> None:
        # services documents no paging params; even a large page must not loop forever.
        config = LinearbEndpointConfig(name="services", path="/api/v1/services")
        session = _session_returning([_response(payload={"total": 5, "items": [{"id": i} for i in range(5)]})])

        pages = list(_iter_list_rows(session, {}, mock.MagicMock(), config, self._manager()))

        assert len(pages) == 1
        assert session.request.call_count == 1

    def test_saves_offset_after_yielding_page(self) -> None:
        responses = [
            _response(payload={"total": 3, "items": [{"id": 1}, {"id": 2}]}),
            _response(payload={"total": 3, "items": [{"id": 3}]}),
        ]
        manager = self._manager()
        list(_iter_list_rows(_session_returning(responses), {}, mock.MagicMock(), _list_config(), manager))

        # State is saved after the first (non-terminal) page carrying the next offset.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert LinearbResumeConfig(offset=2) in saved

    def test_resumes_from_saved_offset(self) -> None:
        manager = self._manager()
        manager.can_resume.return_value = True
        manager.load_state.return_value = LinearbResumeConfig(offset=2)
        session = _session_returning([_response(payload={"total": 3, "items": [{"id": 3}]})])

        list(_iter_list_rows(session, {}, mock.MagicMock(), _list_config(), manager))

        # The first (only) request must start at the saved offset, not 0.
        assert session.request.call_args.kwargs["params"]["offset"] == 2


class TestMeasurements:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb._measurements_body")
    def test_flattens_windows_into_rows(self, mock_body: mock.MagicMock) -> None:
        mock_body.return_value = {}
        windows = [
            {
                "after": "2024-01-01",
                "before": "2024-01-02",
                "metrics": [{"organization_id": 7, "releases.count": 3, "branch.computed.cycle_time:p75": 100}],
            }
        ]
        session = _session_returning([_response(payload=windows)])

        pages = list(_iter_measurements_rows(session, {}, mock.MagicMock()))

        assert len(pages) == 1
        row = pages[0][0]
        assert row["after"] == "2024-01-01"
        assert row["before"] == "2024-01-02"
        assert row["organization_id"] == 7
        assert row["releases_count"] == 3
        assert row["branch_computed_cycle_time_p75"] == 100

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb._measurements_body")
    def test_no_content_yields_nothing(self, mock_body: mock.MagicMock) -> None:
        mock_body.return_value = {}
        session = _session_returning([_response(status_code=204, content=b"")])

        assert list(_iter_measurements_rows(session, {}, mock.MagicMock())) == []


class TestLinearbSource:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        response = linearb_source(
            api_key="key",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(spec=ResumableSourceManager),
        )
        config = LINEARB_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
