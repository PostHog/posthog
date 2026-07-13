from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable import (
    IterableResumeConfig,
    _get_headers,
    _resolve_next_url,
    base_url_for_region,
    get_rows,
    iterable_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import ITERABLE_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable"


def _make_response(status_code: int = 200, body: dict[str, Any] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body or {}
    response.text = ""
    return response


def _make_manager(resume_state: IterableResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestBaseUrlForRegion:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.iterable.com"),
            ("US", "https://api.iterable.com"),
            ("eu", "https://api.eu.iterable.com"),
            ("EU", "https://api.eu.iterable.com"),
            (None, "https://api.iterable.com"),
            ("unknown", "https://api.iterable.com"),
        ],
    )
    def test_base_url_for_region(self, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == expected


class TestHeaders:
    def test_uses_api_key_header(self) -> None:
        headers = _get_headers("secret-key")
        assert headers["Api-Key"] == "secret-key"
        assert headers["Accept"] == "application/json"
        # Iterable uses the `Api-Key` header, not `Authorization`.
        assert "Authorization" not in headers


class TestResolveNextUrl:
    @pytest.mark.parametrize(
        "next_page, expected",
        [
            ("https://api.iterable.com/api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            ("/api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            ("api/campaigns?page=2", "https://api.iterable.com/api/campaigns?page=2"),
            (None, None),
            ("", None),
            (123, None),
            # Off-host absolute URLs must not be followed — the session carries the Api-Key header.
            ("https://evil.com/api/campaigns?page=2", None),
            ("http://api.iterable.com/api/campaigns?page=2", None),
            ("https://api.iterable.com.evil.com/api/campaigns", None),
        ],
    )
    def test_resolve_next_url(self, next_page: Any, expected: str | None) -> None:
        assert _resolve_next_url("https://api.iterable.com", next_page) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_code_mapping(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = _make_response(status_code=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_uses_region_base_url(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _make_response(status_code=200)
        validate_credentials("key", "eu")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.eu.iterable.com/api/channels"


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_single_page_yields_items_without_saving_state(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _make_response(body={"campaigns": [{"id": 1}, {"id": 2}]})
        manager = _make_manager()

        batches = list(get_rows("key", "us", "campaigns", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}, {"id": 2}]]
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_response_yields_nothing(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _make_response(body={"campaigns": []})
        manager = _make_manager()

        batches = list(get_rows("key", "us", "campaigns", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_follows_next_page_url_and_saves_state_after_yield(self, mock_session) -> None:
        first = _make_response(body={"campaigns": [{"id": 1}], "nextPageUrl": "/api/campaigns?page=2"})
        second = _make_response(body={"campaigns": [{"id": 2}]})
        mock_session.return_value.get.side_effect = [first, second]
        manager = _make_manager()

        batches = list(get_rows("key", "us", "campaigns", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        # State is saved once — after the first page yields, pointing at the resolved next URL.
        manager.save_state.assert_called_once_with(
            IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=2")
        )
        # Second request follows the resolved next URL.
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == ["https://api.iterable.com/api/campaigns", "https://api.iterable.com/api/campaigns?page=2"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _make_response(body={"campaigns": [{"id": 9}]})
        manager = _make_manager(
            resume_state=IterableResumeConfig(next_url="https://api.iterable.com/api/campaigns?page=5")
        )

        list(get_rows("key", "us", "campaigns", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert first_url == "https://api.iterable.com/api/campaigns?page=5"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_off_host_resume_state_restarts_from_top(self, mock_session) -> None:
        # A resume URL pointing at another host (corrupted/poisoned state) must not be requested
        # with the Api-Key header — pagination restarts from the endpoint's base URL instead.
        mock_session.return_value.get.return_value = _make_response(body={"campaigns": [{"id": 9}]})
        manager = _make_manager(resume_state=IterableResumeConfig(next_url="https://evil.com/api/campaigns?page=5"))

        list(get_rows("key", "us", "campaigns", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert first_url == "https://api.iterable.com/api/campaigns"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_uses_endpoint_data_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = _make_response(body={"templates": [{"templateId": 7}]})
        manager = _make_manager()

        batches = list(get_rows("key", "us", "templates", mock.MagicMock(), manager))

        assert batches == [[{"templateId": 7}]]


class TestIterableSource:
    @pytest.mark.parametrize(
        "endpoint, expected_pk",
        [
            ("campaigns", "id"),
            ("channels", "id"),
            ("lists", "id"),
            ("message_types", "id"),
            ("templates", "templateId"),
        ],
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_pk: str) -> None:
        response = iterable_source("key", "us", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.primary_keys == [ITERABLE_ENDPOINTS[endpoint].primary_key]
