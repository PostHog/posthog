from typing import Any

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe import (
    SecureframeResumeConfig,
    _build_url,
    _extract_rows,
    get_endpoint_permissions,
    get_rows,
    secureframe_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import (
    ENDPOINTS,
    SECUREFRAME_ENDPOINTS,
)

MOCK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe"


def _make_manager(resume_state: SecureframeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: Any, status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = payload
    response.status_code = status_code
    response.ok = status_code < 400
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status_code} Client Error", response=response)
    return response


class TestExtractRows:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            # Array of per-item JSON:API envelopes (the shape the OpenAPI spec declares).
            (
                [{"data": {"id": "a", "type": "control", "attributes": {"name": "x"}}}],
                [{"id": "a", "name": "x"}],
            ),
            # Standard JSON:API document with a top-level data array.
            (
                {"data": [{"id": "b", "type": "control", "attributes": {"id": "b", "name": "y"}}]},
                [{"id": "b", "name": "y"}],
            ),
            # Plain row dicts, with and without a wrapping data key.
            ([{"id": "c", "name": "z"}], [{"id": "c", "name": "z"}]),
            ({"data": [{"id": "d", "name": "w"}]}, [{"id": "d", "name": "w"}]),
            # Attributes win, but a missing id is backfilled from the envelope.
            (
                [{"data": {"id": "e", "attributes": {"name": "v", "id": "other"}}}],
                [{"id": "other", "name": "v"}],
            ),
            # Unexpected payloads yield nothing instead of raising.
            ({"message": "Authorization failed"}, []),
            ([], []),
            (None, []),
            ("not json we expect", []),
            ([None, "junk", 42], []),
        ],
    )
    def test_extract_rows_shapes(self, payload, expected):
        assert _extract_rows(payload) == expected


class TestBuildUrl:
    @pytest.mark.parametrize(
        "region, expected_host",
        [
            ("us", "https://api.secureframe.com"),
            ("uk", "https://api-uk.secureframe.com"),
            ("unknown", "https://api.secureframe.com"),
        ],
    )
    def test_region_maps_to_host(self, region, expected_host):
        assert _build_url(region, "/controls", 2) == f"{expected_host}/controls?page=2&per_page=100"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, True)),
            # A valid key whose role lacks the probed scope is authenticated but not authorized.
            (403, (True, False)),
            (401, (False, False)),
            (500, (False, False)),
        ],
    )
    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key", "secret", "us") == expected

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret", "us") == (False, False)

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_probes_requested_endpoint(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("key", "secret", "us", endpoint="devices")

        assert "/devices?" in mock_session.return_value.get.call_args.args[0]


class TestGetEndpointPermissions:
    @pytest.mark.parametrize("denied_status", [401, 403])
    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_denied_endpoints_carry_a_reason(self, mock_session, denied_status):
        ok = mock.MagicMock(status_code=200)
        denied = mock.MagicMock(status_code=denied_status)
        mock_session.return_value.get.side_effect = [ok, denied]

        permissions = get_endpoint_permissions("key", "secret", "us", ["controls", "tests"])

        assert permissions["controls"] is None
        assert permissions["tests"] is not None
        assert "tests" in permissions["tests"]

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_transient_failures_are_not_denials(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("connection reset")

        assert get_endpoint_permissions("key", "secret", "us", ["controls"]) == {"controls": None}


class TestGetRows:
    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_paginates_until_empty_page(self, mock_session):
        pages = [
            _response({"data": [{"id": "1", "attributes": {"id": "1"}}, {"id": "2", "attributes": {"id": "2"}}]}),
            _response({"data": [{"id": "3", "attributes": {"id": "3"}}]}),
            _response({"data": []}),
        ]
        mock_session.return_value.get.side_effect = pages

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "us", "controls", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert [f"page={n}" in url for n, url in enumerate(urls, start=1)] == [True, True, True]

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_state_saved_after_each_yielded_batch(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"id": "1", "attributes": {"id": "1"}}]}),
            _response({"data": []}),
        ]

        manager = _make_manager()
        rows_iterator = get_rows("key", "secret", "us", "controls", mock.MagicMock(), manager)

        next(rows_iterator)
        # Generator paused at the yield: page 1 is in flight downstream, so no checkpoint yet —
        # a crash here must re-fetch page 1, not skip it.
        manager.save_state.assert_not_called()

        assert list(rows_iterator) == []
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page == 2

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": []})

        manager = _make_manager(SecureframeResumeConfig(page=5))
        list(get_rows("key", "secret", "us", "controls", mock.MagicMock(), manager))

        assert "page=5" in mock_session.return_value.get.call_args.args[0]

    @mock.patch(f"{MOCK_MODULE}.make_tracked_session")
    def test_auth_failure_raises_instead_of_ending_sync(self, mock_session):
        mock_session.return_value.get.return_value = _response({"message": "Authorization failed"}, status_code=401)

        manager = _make_manager()
        with pytest.raises(HTTPError):
            list(get_rows("key", "secret", "us", "controls", mock.MagicMock(), manager))

        manager.save_state.assert_not_called()


class TestSecureframeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SECUREFRAME_ENDPOINTS[endpoint]
        response = secureframe_source("key", "secret", "us", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SECUREFRAME_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
