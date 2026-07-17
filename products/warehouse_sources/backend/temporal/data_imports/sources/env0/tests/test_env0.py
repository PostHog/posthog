from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import (
    PAGE_SIZE,
    Env0ResumeConfig,
    _build_date_window_params,
    env0_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS, ENV0_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0"


def _make_manager(resume_state: Env0ResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = payload
    if status_code >= 400:
        error = requests.HTTPError(f"{status_code} Client Error")
        error.response = resp
        resp.raise_for_status.side_effect = error
    return resp


def _requested_urls(mock_session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in mock_session.return_value.get.call_args_list]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestBuildDateWindowParams:
    def test_incremental_deployments_sends_from_and_to_date_together(self):
        watermark = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        params = _build_date_window_params(ENV0_ENDPOINTS["deployments"], True, watermark)

        # env0 rejects fromDate without toDate, so both must always be present together.
        assert params["fromDate"] == "2026-05-31T12:00:00.000Z"  # watermark minus the 24h lookback
        assert params["toDate"].endswith("Z")

    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, last_value",
        [
            ("deployments", True, None),
            ("deployments", False, datetime(2026, 6, 1, tzinfo=UTC)),
            ("environments", True, datetime(2026, 6, 1, tzinfo=UTC)),
        ],
    )
    def test_no_window_without_watermark_or_support(self, endpoint, should_use_incremental_field, last_value):
        assert _build_date_window_params(ENV0_ENDPOINTS[endpoint], should_use_incremental_field, last_value) == {}


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
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key-id", "key-secret") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key-id", "key-secret") is False


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_root_endpoint_fetches_once(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "org-1"}, {"id": "org-2"}])

        manager = _make_manager()
        batches = list(get_rows("key-id", "key-secret", "organizations", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["org-1", "org-2"]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_org_scoped_endpoint_fans_out_over_organizations(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}, {"id": "org-2"}]),
            _response([{"id": "proj-1"}]),
            _response([{"id": "proj-2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key-id", "key-secret", "projects", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["proj-1", "proj-2"]
        urls = _requested_urls(mock_session)
        assert _query(urls[1])["organizationId"] == ["org-1"]
        assert _query(urls[2])["organizationId"] == ["org-2"]
        # Bookmark advances to the next organization so a crash between parents resumes there.
        manager.save_state.assert_called_once_with(Env0ResumeConfig(parent_id="org-2", offset=None))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_offset_pagination_advances_until_short_page(self, mock_session):
        full_page = [{"id": f"env-{i}"} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response(full_page),
            _response([{"id": "env-last"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key-id", "key-secret", "environments", mock.MagicMock(), manager))

        assert sum(len(batch) for batch in batches) == PAGE_SIZE + 1
        urls = _requested_urls(mock_session)
        assert "offset" not in _query(urls[1])
        assert _query(urls[2])["offset"] == [str(PAGE_SIZE)]
        # State saved after yielding the full page, pointing at the next offset.
        manager.save_state.assert_called_once_with(Env0ResumeConfig(parent_id="org-1", offset=str(PAGE_SIZE)))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_teams_pagination_follows_next_page_key(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response({"teams": [{"id": "team-1"}], "nextPageKey": "key-abc"}),
            _response({"teams": [{"id": "team-2"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("key-id", "key-secret", "teams", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["team-1", "team-2"]
        urls = _requested_urls(mock_session)
        assert _query(urls[2])["offset"] == ["key-abc"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_deployments_fan_out_strips_heavy_fields_and_windows_requests(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response([{"id": "env-1"}]),
            _response([{"id": "dep-1", "status": "SUCCESS", "output": "x" * 100, "plan": {"big": True}}]),
        ]

        manager = _make_manager()
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        batches = list(
            get_rows(
                "key-id",
                "key-secret",
                "deployments",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        rows = [row for batch in batches for row in batch]
        assert rows == [{"id": "dep-1", "status": "SUCCESS"}]

        deployments_query = _query(_requested_urls(mock_session)[2])
        assert deployments_query["fromDate"] == ["2026-05-31T00:00:00.000Z"]
        assert "toDate" in deployments_query

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_costs_inject_environment_id_and_skip_404s(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response([{"id": "env-1"}, {"id": "env-2"}]),
            # env-1 has no cost monitoring configured.
            _response({"message": "not found"}, status_code=404),
            _response([{"date": "2026-06-01", "total": 12.5}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key-id", "key-secret", "environment_costs", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert rows == [{"date": "2026-06-01", "total": 12.5, "environment_id": "env-2"}]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_non_404_error_fails_the_sync(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response([{"id": "env-1"}]),
            _response({"message": "forbidden"}, status_code=403),
        ]

        with pytest.raises(requests.HTTPError):
            list(get_rows("key-id", "key-secret", "environment_costs", mock.MagicMock(), _make_manager()))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_already_processed_parents(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}, {"id": "org-2"}]),
            _response([{"id": "proj-2"}]),
        ]

        manager = _make_manager(Env0ResumeConfig(parent_id="org-2", offset=None))
        batches = list(get_rows("key-id", "key-secret", "projects", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["proj-2"]
        urls = _requested_urls(mock_session)
        assert len(urls) == 2
        assert _query(urls[1])["organizationId"] == ["org-2"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resume_offset_applies_only_to_bookmarked_parent(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}, {"id": "org-2"}]),
            _response([{"id": "env-9"}]),
            _response([{"id": "env-10"}]),
        ]

        manager = _make_manager(Env0ResumeConfig(parent_id="org-1", offset="200"))
        list(get_rows("key-id", "key-secret", "environments", mock.MagicMock(), manager))

        urls = _requested_urls(mock_session)
        assert _query(urls[1])["offset"] == ["200"]
        # The next parent starts a fresh page chain.
        assert "offset" not in _query(urls[2])

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_stale_resume_bookmark_starts_over(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "org-1"}]),
            _response([{"id": "proj-1"}]),
        ]

        manager = _make_manager(Env0ResumeConfig(parent_id="org-deleted", offset="100"))
        batches = list(get_rows("key-id", "key-secret", "projects", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["proj-1"]
        assert "offset" not in _query(_requested_urls(mock_session)[1])


class TestEnv0SourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ENV0_ENDPOINTS[endpoint]
        response = env0_source("key-id", "key-secret", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Unverified API ordering: incremental endpoints must persist their watermark only at
        # successful job end, which "desc" guarantees.
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_child_primary_keys_include_parent_id(self):
        # Cost rows have no globally-unique id of their own; without the environment id in the
        # key, rows from different environments on the same date would merge into one.
        assert ENV0_ENDPOINTS["environment_costs"].primary_keys == ["environment_id", "date"]

    @pytest.mark.parametrize("config", list(ENV0_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "createdAt"
