import base64

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import (
    DripResumeConfig,
    _auth_headers,
    _base_params,
    _has_next_page,
    drip_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import DRIP_ENDPOINTS, ENDPOINTS


def _make_response(status_code=200, json_data=None):
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_data if json_data is not None else {}
    return response


class TestAuthHeaders:
    def test_basic_auth_token_as_username_empty_password(self):
        headers = _auth_headers("my_token")
        expected = base64.b64encode(b"my_token:").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestBaseParams:
    @parameterized.expand(
        [
            ("subscribers", {"per_page": 1000}),
            ("campaigns", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("broadcasts", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("workflows", {"per_page": 100}),
            ("forms", {}),
            ("goals", {}),
        ]
    )
    def test_base_params(self, endpoint, expected):
        assert _base_params(endpoint) == expected


class TestHasNextPage:
    @parameterized.expand(
        [
            # meta drives pagination when present
            ("meta_more_pages", {"meta": {"total_pages": 3}}, [1, 2], 100, 1, True),
            ("meta_last_page", {"meta": {"total_pages": 3}}, [1, 2], 100, 3, False),
            ("meta_single_page", {"meta": {"total_pages": 1}}, [1], 100, 1, False),
            # fallback when there's no meta: a full page implies there may be more
            ("no_meta_full_page", {}, list(range(100)), 100, 1, True),
            ("no_meta_partial_page", {}, list(range(40)), 100, 1, False),
            # non-paginated endpoints (per_page=None) always return everything at once
            ("non_paginated", {}, [1, 2, 3], None, 1, False),
        ]
    )
    def test_has_next_page(self, _name, data, items, per_page, page, expected):
        assert _has_next_page(data, items, per_page, page) is expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Drip API token"),
            ("forbidden", 403, False, "Invalid Drip API token"),
            ("not_found", 404, False, "Drip account ID not found. Please check your account ID."),
            ("server_error", 500, False, "Drip API returned an unexpected status (500)"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, _name, status_code, expected_valid, expected_message, mock_session
    ):
        mock_session.return_value.get.return_value = _make_response(status_code=status_code)

        is_valid, message = validate_credentials("token", "9999")

        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_validate_credentials_connection_error(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, message = validate_credentials("token", "9999")

        assert is_valid is False
        assert message == "Could not connect to the Drip API"


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_paginates_until_last_page_via_meta(self, mock_session):
        responses = [
            _make_response(json_data={"subscribers": [{"id": 1}], "meta": {"total_pages": 2}}),
            _make_response(json_data={"subscribers": [{"id": 2}], "meta": {"total_pages": 2}}),
        ]
        mock_session.return_value.get.side_effect = responses

        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        batches = list(get_rows("token", "9999", "subscribers", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_saves_state_after_yielding_each_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _make_response(json_data={"subscribers": [{"id": 1}], "meta": {"total_pages": 2}}),
            _make_response(json_data={"subscribers": [{"id": 2}], "meta": {"total_pages": 2}}),
        ]
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        list(get_rows("token", "9999", "subscribers", mock.MagicMock(), manager))

        # State advances to page 2 once page 1 has been yielded; the final page saves nothing further.
        manager.save_state.assert_called_once_with(DripResumeConfig(next_page=2))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _make_response(
            json_data={"subscribers": [{"id": 5}], "meta": {"total_pages": 3}}
        )
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = DripResumeConfig(next_page=3)

        list(get_rows("token", "9999", "subscribers", mock.MagicMock(), manager))

        # Should start at page 3 (the resume point) and stop, since total_pages == 3.
        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["params"]["page"] == 3
        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip.make_tracked_session")
    def test_single_page_for_non_paginated_endpoint(self, mock_session):
        mock_session.return_value.get.return_value = _make_response(json_data={"forms": [{"id": 1}, {"id": 2}]})
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        batches = list(get_rows("token", "9999", "forms", mock.MagicMock(), manager))

        assert batches == [[{"id": 1}, {"id": 2}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestDripSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = drip_source("token", "9999", endpoint, mock.MagicMock(), mock.MagicMock())

        config = DRIP_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_subscribers_partitions_on_created_at(self):
        response = drip_source("token", "9999", "subscribers", mock.MagicMock(), mock.MagicMock())
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"
