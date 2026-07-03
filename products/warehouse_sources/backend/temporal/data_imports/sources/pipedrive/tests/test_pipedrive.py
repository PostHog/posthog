from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive import (
    PAGE_SIZE,
    PipedriveResumeConfig,
    _initial_url,
    _next_url,
    base_url,
    get_rows,
    normalize_company_domain,
    pipedrive_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import PIPEDRIVE_ENDPOINTS


class TestNormalizeCompanyDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("mycompany", "mycompany"),
            ("MyCompany", "mycompany"),
            ("mycompany.pipedrive.com", "mycompany"),
            ("https://mycompany.pipedrive.com", "mycompany"),
            ("http://mycompany.pipedrive.com/", "mycompany"),
            ("  mycompany  ", "mycompany"),
            ("my-company-123", "my-company-123"),
        ],
    )
    def test_normalizes_valid_domains(self, raw: str, expected: str) -> None:
        assert normalize_company_domain(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "my company",
            "evil.com",
            "mycompany.pipedrive.com.evil.com",
            "http://169.254.169.254",
            "foo_bar",
        ],
    )
    def test_rejects_invalid_domains(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_company_domain(raw)

    def test_base_url_is_pinned_to_pipedrive(self) -> None:
        assert base_url("mycompany") == "https://mycompany.pipedrive.com"
        assert base_url("https://MyCompany.pipedrive.com") == "https://mycompany.pipedrive.com"


class TestInitialUrl:
    def test_cursor_endpoint_only_sets_limit(self) -> None:
        url = _initial_url("acme", PIPEDRIVE_ENDPOINTS["deals"])
        assert url == f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}"

    def test_offset_endpoint_sets_start_and_limit(self) -> None:
        url = _initial_url("acme", PIPEDRIVE_ENDPOINTS["activities"])
        assert url == f"https://acme.pipedrive.com/api/v1/activities?limit={PAGE_SIZE}&start=0"


class TestNextUrl:
    def test_cursor_returns_next_page_url(self) -> None:
        config = PIPEDRIVE_ENDPOINTS["deals"]
        response = {"data": [{"id": 1}], "additional_data": {"next_cursor": "abc123"}}
        assert _next_url("acme", config, response) == (
            f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}&cursor=abc123"
        )

    @pytest.mark.parametrize(
        "additional_data",
        [
            {},
            {"next_cursor": None},
            {"next_cursor": ""},
        ],
    )
    def test_cursor_terminates_when_no_next_cursor(self, additional_data: dict[str, Any]) -> None:
        config = PIPEDRIVE_ENDPOINTS["deals"]
        assert _next_url("acme", config, {"data": [], "additional_data": additional_data}) is None

    def test_offset_returns_next_page_url(self) -> None:
        config = PIPEDRIVE_ENDPOINTS["activities"]
        response = {
            "data": [{"id": 1}],
            "additional_data": {"pagination": {"more_items_in_collection": True, "next_start": 500}},
        }
        assert _next_url("acme", config, response) == (
            f"https://acme.pipedrive.com/api/v1/activities?limit={PAGE_SIZE}&start=500"
        )

    @pytest.mark.parametrize(
        "additional_data",
        [
            {},
            {"pagination": {"more_items_in_collection": False, "next_start": 500}},
            {"pagination": {"more_items_in_collection": True}},
        ],
    )
    def test_offset_terminates(self, additional_data: dict[str, Any]) -> None:
        config = PIPEDRIVE_ENDPOINTS["activities"]
        assert _next_url("acme", config, {"data": [], "additional_data": additional_data}) is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_returns_status_code(self, mock_session: mock.MagicMock, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("acme", "token") == status_code
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://acme.pipedrive.com/api/v1/users/me"
        # Auth header and token redaction are configured on the session, not the request.
        assert mock_session.call_args.kwargs["headers"]["x-api-token"] == "token"
        assert mock_session.call_args.kwargs["redact_values"] == ("token",)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_returns_none_on_transport_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("acme", "token") is None

    def test_propagates_invalid_domain(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com", "token")


class TestGetRows:
    def _manager(self, resume_state: PipedriveResumeConfig | None = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume_state is not None
        manager.load_state.return_value = resume_state
        return manager

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_paginates_cursor_endpoint_and_saves_state_after_yield(self, mock_session: mock.MagicMock) -> None:
        page1 = mock.MagicMock(status_code=200, ok=True)
        page1.json.return_value = {"data": [{"id": 1}], "additional_data": {"next_cursor": "c2"}}
        page2 = mock.MagicMock(status_code=200, ok=True)
        page2.json.return_value = {"data": [{"id": 2}], "additional_data": {"next_cursor": None}}
        mock_session.return_value.get.side_effect = [page1, page2]

        manager = self._manager()
        batches = list(get_rows("acme", "token", "deals", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        # The session masks the token in logged URLs and captured samples.
        assert mock_session.call_args.kwargs["redact_values"] == ("token",)
        # State is saved once: after the first page is yielded, pointing at page 2.
        manager.save_state.assert_called_once_with(
            PipedriveResumeConfig(next_url=f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}&cursor=c2")
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=200, ok=True)
        page.json.return_value = {"data": [{"id": 9}], "additional_data": {"next_cursor": None}}
        mock_session.return_value.get.return_value = page

        resume_url = f"https://acme.pipedrive.com/api/v2/deals?limit={PAGE_SIZE}&cursor=resume-me"
        manager = self._manager(PipedriveResumeConfig(next_url=resume_url))

        batches = list(get_rows("acme", "token", "deals", mock.MagicMock(), manager))

        assert batches == [[{"id": 9}]]
        assert mock_session.return_value.get.call_args.args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_single_page_endpoint_without_pagination(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=200, ok=True)
        page.json.return_value = {"data": [{"id": 1}, {"id": 2}]}
        mock_session.return_value.get.return_value = page

        manager = self._manager()
        batches = list(get_rows("acme", "token", "users", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}, {"id": 2}]]
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive.make_tracked_session"
    )
    def test_raises_on_non_retryable_error(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=401, ok=False, text="unauthorized")
        page.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = page

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("acme", "token", "deals", mock.MagicMock(), self._manager()))


class TestPipedriveSource:
    @pytest.mark.parametrize(
        "endpoint, expected_primary_keys, expected_partition_keys, expected_mode",
        [
            ("deals", ["id"], ["add_time"], "datetime"),
            ("activities", ["id"], ["add_time"], "datetime"),
            ("users", ["id"], None, None),
            ("deal_fields", ["key"], None, None),
            ("person_fields", ["key"], None, None),
            ("organization_fields", ["key"], None, None),
        ],
    )
    def test_source_response_partitioning(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        response = pipedrive_source("acme", "token", endpoint, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == expected_mode
