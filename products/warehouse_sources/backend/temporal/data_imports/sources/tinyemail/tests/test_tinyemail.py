from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail import (
    INVALID_CREDENTIALS_MESSAGE,
    get_resource,
    tinyemail_source,
    validate_credentials,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestTinyemailTransport:
    @parameterized.expand(
        [
            # The campaigns list path really is singular, rows wrapped in `campaigns.content`,
            # and pages are 0-indexed.
            ("campaigns", "/campaign", "campaigns.content", PageNumberPaginator, 0, 20),
            ("contacts", "/contacts", "contacts", SinglePagePaginator, None, None),
            ("sender_details", "/sender-details", "senderDetailses", SinglePagePaginator, None, None),
        ]
    )
    def test_get_resource_top_level(self, endpoint, path, data_selector, paginator_type, base_page, size) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == path
        assert resource["endpoint"]["data_selector"] == data_selector

        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, paginator_type)
        if base_page is not None:
            assert paginator.page == base_page
        if size is not None:
            assert resource["endpoint"]["params"]["size"] == size
        else:
            assert "size" not in resource["endpoint"]["params"]

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("contact_members")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail.rest_api_resource")
    def test_tinyemail_source_top_level_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        response = tinyemail_source(api_key="key", endpoint="campaigns", team_id=1, job_id="job-1")

        assert response.name == "campaigns"
        assert response.primary_keys == ["id"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_tinyemail_source_contact_members_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("contacts", [{"id": "list_1", "name": "Newsletter"}]),
            _FakeDltResource("contact_members", [{"email": "a@example.com", "_contacts_id": "list_1"}]),
        ]

        response = tinyemail_source(api_key="key", endpoint="contact_members", team_id=1, job_id="job-1")

        rows = list(cast(Any, response.items()))
        assert rows == [{"email": "a@example.com", "contact_id": "list_1"}]
        # An email is only unique within one contact list, so the parent id is part of the key.
        assert response.primary_keys == ["contact_id", "email"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail.build_dependent_resource"
    )
    def test_tinyemail_source_contact_members_wiring(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        tinyemail_source(api_key="key", endpoint="contact_members", team_id=1, job_id="job-1")

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "size"
        assert kwargs["client_config"]["allow_redirects"] is False
        assert kwargs["fanout"].parent_name == "contacts"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "contacts"
        child_paginator = kwargs["child_endpoint_extra"]["paginator"]
        assert isinstance(child_paginator, PageNumberPaginator)
        # Member pages are 1-indexed (unlike campaign pages) — starting at 0 would duplicate page one.
        assert child_paginator.page == 1
        assert kwargs["child_endpoint_extra"]["data_selector"] == "members.content"

    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("invalid_key", 401, False, INVALID_CREDENTIALS_MESSAGE),
            ("forbidden", 403, False, INVALID_CREDENTIALS_MESSAGE),
            ("server_error", 500, False, "tinyEmail API returned an unexpected status code 500"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail.make_tracked_session")
    def test_validate_credentials_status_mapping(self, _name, status, expected_valid, expected_message, mock_session):
        mock_session.return_value.get.return_value = Mock(status_code=status)

        assert validate_credentials(api_key="key") == (expected_valid, expected_message)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail.make_tracked_session")
    def test_validate_credentials_sends_api_key_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_key="secret-key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.tinyemail.com/v1/contacts"
        assert call.kwargs["headers"]["X-API-KEY"] == "secret-key"
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)
        # A followed cross-host redirect would replay the X-API-KEY header off-host.
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail.make_tracked_session")
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")

        is_valid, message = validate_credentials(api_key="key")

        assert is_valid is False
        assert message is not None and "Could not connect to the tinyEmail API" in message
