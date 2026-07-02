from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer import (
    KustomerResumeConfig,
    _base_url,
    _clean_org_name,
    get_rows,
    kustomer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import (
    ENDPOINTS,
    KUSTOMER_ENDPOINTS,
)


def _make_manager(resume_state: KustomerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"data": items, "links": {}}
    if next_link:
        body["links"]["next"] = next_link
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestCleanOrgName:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("myorg", "myorg"),
            (" myorg ", "myorg"),
            ("https://myorg.kustomerapp.com", "myorg"),
            ("myorg.api.kustomerapp.com/v1", "myorg"),
            ("my-org", "my-org"),
        ],
    )
    def test_valid_org_names(self, value, expected):
        assert _clean_org_name(value) == expected

    @pytest.mark.parametrize("value", ["", "my org", "org?x=1", "../evil"])
    def test_invalid_org_names_raise(self, value):
        with pytest.raises(ValueError):
            _clean_org_name(value)

    def test_base_url(self):
        assert _base_url("myorg") == "https://myorg.api.kustomerapp.com"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Role-scoped keys without the customers grant still 403; only 401
            # means the key itself is bad.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_validate_credentials_rejects_bad_org_without_request(self, mock_session):
        assert validate_credentials("my org!", "key") is False
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_paginates_via_links_next_and_absolutizes(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], next_link="/v1/customers?page%5Bafter%5D=abc&page%5Bsize%5D=100"),
            _response([{"id": "2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "key", "customers", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        saved_url = manager.save_state.call_args.args[0].next_url
        assert saved_url.startswith("https://myorg.api.kustomerapp.com/v1/customers?")
        assert mock_session.return_value.get.call_args_list[1].args[0] == saved_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_first_request_uses_endpoint_path_and_page_size(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(get_rows("myorg", "key", "conversations", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        parsed = urlparse(url)
        assert parsed.path == "/v1/conversations"
        assert parse_qs(parsed.query)["page[size]"] == ["100"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        resume_url = "https://myorg.api.kustomerapp.com/v1/customers?page%5Bafter%5D=resume"
        manager = _make_manager(KustomerResumeConfig(next_url=resume_url))

        list(get_rows("myorg", "key", "customers", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.com/steal",
            "//attacker.com/steal",
            "http://myorg.api.kustomerapp.com/v1/customers",  # downgraded scheme
            "https://myorg.api.kustomerapp.com.evil.com/v1/customers",  # look-alike host
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_off_host_next_link_is_rejected(self, mock_session, next_link):
        mock_session.return_value.get.return_value = _response([{"id": "1"}], next_link=next_link)

        manager = _make_manager()
        with pytest.raises(ValueError):
            list(get_rows("myorg", "key", "customers", mock.MagicMock(), manager))

        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_off_host_resume_state_is_rejected(self, mock_session):
        manager = _make_manager(KustomerResumeConfig(next_url="https://attacker.com/steal"))

        with pytest.raises(ValueError):
            list(get_rows("myorg", "key", "customers", mock.MagicMock(), manager))

        mock_session.return_value.get.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer.make_tracked_session"
    )
    def test_empty_page_with_next_link_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response([], next_link="/v1/customers?page%5Bafter%5D=loop")

        manager = _make_manager()
        batches = list(get_rows("myorg", "key", "customers", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestKustomerSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = KUSTOMER_ENDPOINTS[endpoint]
        response = kustomer_source("myorg", "key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        # JSON:API rows nest timestamps under attributes — no partitioning.
        assert response.partition_mode is None
        assert response.partition_keys is None
