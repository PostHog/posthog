from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio import (
    AUTH_REVOKED_ERROR,
    PersonioAuthError,
    PersonioResumeConfig,
    _build_initial_url,
    _format_updated_at,
    get_rows,
    personio_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    PERSONIO_ENDPOINTS,
)


def _make_manager(resume_state: PersonioResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "token_type": "Bearer", "expires_in": 86400}
    resp.status_code = 200
    resp.ok = True
    return resp


def _page_response(items: list[dict[str, Any]], next_url: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"_data": items, "_meta": {"links": {}}}
    if next_url:
        body["_meta"]["links"]["next"] = {"href": next_url}
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestFormatUpdatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_updated_at(value) == expected


class TestBuildInitialUrl:
    def test_incremental_persons_uses_strict_gt_filter(self):
        url = _build_initial_url(
            PERSONIO_ENDPOINTS["persons"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )
        query = parse_qs(urlparse(url).query)
        assert query["updated_at.gt"] == ["2024-01-02T00:00:00Z"]
        assert query["limit"] == ["50"]

    def test_incremental_absence_periods_uses_gte_filter(self):
        url = _build_initial_url(
            PERSONIO_ENDPOINTS["absence_periods"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )
        query = parse_qs(urlparse(url).query)
        assert query["updated_at.gte"] == ["2024-01-02T00:00:00Z"]
        assert query["limit"] == ["100"]

    def test_full_refresh_has_no_filter(self):
        url = _build_initial_url(
            PERSONIO_ENDPOINTS["persons"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        query = parse_qs(urlparse(url).query)
        assert "updated_at.gt" not in query
        assert query["limit"] == ["50"]


class TestValidateCredentials:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_valid_when_token_mints(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        assert validate_credentials("id", "secret") is True

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_invalid_when_token_mint_fails(self, mock_session):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        mock_session.return_value.post.return_value = resp
        assert validate_credentials("id", "secret") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("id", "secret") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_paginates_via_meta_next_link(self, mock_session):
        next_url = "https://api.personio.de/v2/persons?cursor=cur_abc&limit=50"
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _page_response([{"id": "1"}], next_url=next_url),
            _page_response([{"id": "2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url
        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_requests_carry_bearer_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager()
        list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer the-token"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _page_response([{"id": "1"}])]

        manager = _make_manager()
        batches = list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}]]
        # One mint at start + one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_second_401_after_remint_raises_auth_error(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        # Both the original and the post-remint GET return 401 (credential revoked mid-sync).
        mock_session.return_value.get.side_effect = [expired, expired]

        manager = _make_manager()
        with pytest.raises(PersonioAuthError) as exc:
            list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        # The message must be matchable by get_non_retryable_errors so the job fails fast.
        assert AUTH_REVOKED_ERROR in str(exc.value)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_stops_pagination_when_next_url_is_foreign_host(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response(
            [{"id": "1"}], next_url="https://evil.example.com/v2/persons?cursor=x"
        )

        manager = _make_manager()
        batches = list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        # The first page is yielded, but the off-host next URL is never followed or saved.
        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_resume_state_with_foreign_host_raises(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        manager = _make_manager(PersonioResumeConfig(next_url="https://evil.example.com/v2/persons"))

        with pytest.raises(ValueError):
            list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        mock_session.return_value.get.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([{"id": "9"}])

        resume_url = "https://api.personio.de/v2/persons?cursor=cur_resume"
        manager = _make_manager(PersonioResumeConfig(next_url=resume_url))

        list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio.make_tracked_session"
    )
    def test_empty_page_stops_even_with_next_link(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response(
            [], next_url="https://api.personio.de/v2/persons?cursor=loop"
        )

        manager = _make_manager()
        batches = list(get_rows("id", "secret", "persons", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestPersonioSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PERSONIO_ENDPOINTS[endpoint]
        response = personio_source("id", "secret", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(PERSONIO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
