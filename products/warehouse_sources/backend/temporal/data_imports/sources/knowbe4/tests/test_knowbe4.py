from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4 import (
    build_base_url,
    get_resource,
    knowbe4_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.settings import KNOWBE4_ENDPOINTS


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestKnowBe4Transport:
    @parameterized.expand(
        [
            ("us", "us", "https://us.api.knowbe4.com"),
            ("eu", "eu", "https://eu.api.knowbe4.com"),
            ("ca", "ca", "https://ca.api.knowbe4.com"),
            ("uk", "uk", "https://uk.api.knowbe4.com"),
            ("de", "de", "https://de.api.knowbe4.com"),
            ("case_insensitive", "US", "https://us.api.knowbe4.com"),
            ("whitespace_trimmed", "  us  ", "https://us.api.knowbe4.com"),
        ]
    )
    def test_build_base_url(self, _name, region, expected) -> None:
        assert build_base_url(region) == expected

    def test_build_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            build_base_url("apac")

    @parameterized.expand(
        [
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "users", False),
            ("ok", 200, None, True),
            ("unexpected", 500, None, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, _name, status_code, schema_name, expected_ok, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status_code)

        is_valid, _message = validate_credentials(api_key="tok", region="us", schema_name=schema_name)

        assert is_valid is expected_ok

    def test_validate_credentials_rejects_bad_region_before_request(self) -> None:
        is_valid, message = validate_credentials(api_key="tok", region="apac")
        assert is_valid is False
        assert message is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4.make_tracked_session")
    def test_validate_credentials_probes_account_with_bearer(self, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_key="tok", region="us")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://us.api.knowbe4.com/v1/account"
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4.make_tracked_session")
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        is_valid, message = validate_credentials(api_key="tok", region="us")
        assert is_valid is False
        assert message is not None and "boom" in message

    def test_get_resource_users_bare_array_page_paginated(self) -> None:
        resource = cast(dict[str, Any], get_resource(KNOWBE4_ENDPOINTS["users"]))
        assert resource["name"] == "users"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/v1/users"
        assert resource["endpoint"]["data_selector"] == "$"
        assert resource["endpoint"]["params"]["per_page"] == 500
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.page == 1
        assert paginator.page_param == "page"

    def test_get_resource_training_campaigns_carries_exclude_percentages(self) -> None:
        # Without exclude_percentages=true, KnowBe4 caps the response at 10 campaigns.
        resource = cast(dict[str, Any], get_resource(KNOWBE4_ENDPOINTS["training_campaigns"]))
        assert resource["endpoint"]["params"]["exclude_percentages"] == "true"

    def test_get_resource_training_enrollments_requests_enrichment_flags(self) -> None:
        resource = cast(dict[str, Any], get_resource(KNOWBE4_ENDPOINTS["training_enrollments"]))
        params = resource["endpoint"]["params"]
        assert params["include_campaign_id"] == "true"
        assert params["include_store_purchase_id"] == "true"
        assert params["include_employee_number"] == "true"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4.rest_api_resource")
    def test_knowbe4_source_users_top_level(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = knowbe4_source(api_key="tok", region="us", endpoint="users", team_id=1, job_id="job-1")

        assert response.name == "users"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_knowbe4_source_group_members_fanout_injects_and_renames_parent_id(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("groups", [{"id": "grp_1"}]),
            _FakeDltResource("group_members", [{"id": "user_1", "email": "a@b.com", "_groups_id": "grp_1"}]),
        ]

        response = knowbe4_source(api_key="tok", region="us", endpoint="group_members", team_id=1, job_id="job-1")

        rows = list(cast(Any, response.items()))
        # The parent group id is injected and renamed to `group_id` to avoid colliding with the
        # member's own `id` field.
        assert rows == [{"id": "user_1", "email": "a@b.com", "group_id": "grp_1"}]
        # A user can belong to multiple groups, so the parent group id is required in the key.
        assert response.primary_keys == ["group_id", "id"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_knowbe4_source_phishing_recipients_fanout_keeps_own_pst_id(self, mock_rest_api_resources) -> None:
        # Each recipient row already carries its own `pst_id` from the API, so no parent field
        # injection is configured for this fan-out.
        mock_rest_api_resources.return_value = [
            _FakeDltResource("phishing_security_tests", [{"pst_id": 1}]),
            _FakeDltResource("phishing_security_test_recipients", [{"recipient_id": 55, "pst_id": 1, "os": "MacOSX"}]),
        ]

        response = knowbe4_source(
            api_key="tok", region="us", endpoint="phishing_security_test_recipients", team_id=1, job_id="job-1"
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"recipient_id": 55, "pst_id": 1, "os": "MacOSX"}]
        # `recipient_id` is only documented unique within a single test, so the parent pst_id
        # anchors the composite key.
        assert response.primary_keys == ["pst_id", "recipient_id"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4.build_dependent_resource")
    def test_knowbe4_source_fanout_uses_per_page_and_page_paginator(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        knowbe4_source(api_key="tok", region="us", endpoint="group_members", team_id=1, job_id="job-1")

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "per_page"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "$"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "$"
