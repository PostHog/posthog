from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku import (
    HerokuResumeConfig,
    get_rows,
    heroku_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    DEFAULT_PAGE_SIZE,
    HEROKU_ENDPOINTS,
    MAX_PAGES_PER_LIST,
)

PATCH_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku.make_tracked_session"


def _response(
    status_code: int = 200, json_data: list[dict[str, Any]] | None = None, next_range: str | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = {"Next-Range": next_range} if next_range else {}
    response.json.return_value = json_data if json_data is not None else []
    response.text = ""
    if status_code >= 400:
        error = requests.HTTPError(f"{status_code} Client Error: for url: https://api.heroku.com", response=response)
        response.raise_for_status.side_effect = error
    return response


def _manager(resume: HerokuResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestPagination:
    def test_follows_next_range_header_until_absent(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000"),
            _response(200, [{"id": "b"}]),
        ]
        manager = _manager()

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "apps", MagicMock(), manager))

        assert pages == [[{"id": "a"}], [{"id": "b"}]]
        first_headers = session.get.call_args_list[0].kwargs["headers"]
        second_headers = session.get.call_args_list[1].kwargs["headers"]
        assert first_headers["Range"] == f"id ..; order=asc,max={DEFAULT_PAGE_SIZE}"
        assert second_headers["Range"] == "id ]a..; order=asc,max=1000"
        assert first_headers["Accept"] == "application/vnd.heroku+json; version=3"
        assert first_headers["Authorization"] == "Bearer key"

    def test_saves_state_after_yield_only_when_more_pages_remain(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000"),
            _response(200, [{"id": "b"}]),
        ]
        manager = _manager()

        with patch(PATCH_PATH, return_value=session):
            iterator = get_rows("key", "apps", MagicMock(), manager)
            next(iterator)
            manager.save_state.assert_not_called()
            next(iterator)

        manager.save_state.assert_called_once_with(HerokuResumeConfig(next_range="id ]a..; order=asc,max=1000"))

    def test_resumes_top_level_endpoint_from_saved_cursor(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_response(200, [{"id": "b"}])]
        manager = _manager(HerokuResumeConfig(next_range="id ]a..; order=asc,max=1000"))

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "apps", MagicMock(), manager))

        assert pages == [[{"id": "b"}]]
        assert session.get.call_args_list[0].kwargs["headers"]["Range"] == "id ]a..; order=asc,max=1000"

    def test_page_cap_stops_unbounded_scans_and_warns(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(206, [{"id": "a"}], next_range="id ]a..; order=asc,max=1000")
        logger = MagicMock()

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "apps", logger, _manager()))

        assert len(pages) == MAX_PAGES_PER_LIST
        assert session.get.call_count == MAX_PAGES_PER_LIST
        logger.warning.assert_called_once()


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retries_transient_statuses_then_succeeds(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.side_effect = [_response(status_code), _response(200, [{"id": "a"}])]

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "apps", MagicMock(), _manager()))

        assert pages == [[{"id": "a"}]]
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_credential_errors_raise_without_retry(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code)

        with patch(PATCH_PATH, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "apps", MagicMock(), _manager()))

        assert session.get.call_count == 1


class TestFanOut:
    def test_fans_out_over_every_app(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(200, [{"id": "app-1"}, {"id": "app-2"}]),
            _response(200, [{"id": "rel-1", "app": {"id": "app-1"}}]),
            _response(200, [{"id": "rel-2", "app": {"id": "app-2"}}]),
        ]

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "releases", MagicMock(), _manager()))

        assert pages == [
            [{"id": "rel-1", "app": {"id": "app-1"}}],
            [{"id": "rel-2", "app": {"id": "app-2"}}],
        ]
        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls == [
            "https://api.heroku.com/apps",
            "https://api.heroku.com/apps/app-1/releases",
            "https://api.heroku.com/apps/app-2/releases",
        ]

    def test_app_deleted_mid_sync_is_skipped(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(200, [{"id": "app-1"}, {"id": "app-2"}]),
            _response(404),
            _response(200, [{"id": "rel-2", "app": {"id": "app-2"}}]),
        ]

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "releases", MagicMock(), _manager()))

        assert pages == [[{"id": "rel-2", "app": {"id": "app-2"}}]]

    def test_resumes_from_bookmarked_app_with_saved_cursor(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(200, [{"id": "app-1"}, {"id": "app-2"}, {"id": "app-3"}]),
            _response(200, [{"id": "rel-2"}]),
            _response(200, [{"id": "rel-3"}]),
        ]
        saved_cursor = "id ]rel-1..; order=asc,max=1000"
        manager = _manager(HerokuResumeConfig(next_range=saved_cursor, app_id="app-2"))

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "releases", MagicMock(), manager))

        assert pages == [[{"id": "rel-2"}], [{"id": "rel-3"}]]
        urls = [call.args[0] for call in session.get.call_args_list]
        assert "https://api.heroku.com/apps/app-1/releases" not in urls
        assert session.get.call_args_list[1].kwargs["headers"]["Range"] == saved_cursor
        # The next app starts from a fresh first page, not the resumed cursor.
        assert session.get.call_args_list[2].kwargs["headers"]["Range"] == f"id ..; order=asc,max={DEFAULT_PAGE_SIZE}"
        manager.save_state.assert_called_with(HerokuResumeConfig(next_range=None, app_id="app-3"))

    def test_deleted_bookmark_app_restarts_from_first_app(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(200, [{"id": "app-1"}]),
            _response(200, [{"id": "rel-1"}]),
        ]
        manager = _manager(HerokuResumeConfig(next_range="id ]x..; order=asc,max=1000", app_id="app-gone"))

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", "releases", MagicMock(), manager))

        assert pages == [[{"id": "rel-1"}]]
        assert session.get.call_args_list[1].kwargs["headers"]["Range"] == f"id ..; order=asc,max={DEFAULT_PAGE_SIZE}"


class TestSensitiveFieldRedaction:
    @parameterized.expand(
        [
            (
                "build_capability_urls_nulled",
                "builds",
                {
                    "id": "b-1",
                    "output_stream_url": "https://build-output.heroku.com/streams/secret",
                    "source_blob": {"url": "https://signed.example.com/tarball?sig=secret", "checksum": "SHA256:abc"},
                },
                {"id": "b-1", "output_stream_url": None, "source_blob": {"url": None, "checksum": "SHA256:abc"}},
            ),
            (
                "release_output_stream_nulled",
                "releases",
                {"id": "r-1", "output_stream_url": "https://release-output.heroku.com/streams/secret", "version": 3},
                {"id": "r-1", "output_stream_url": None, "version": 3},
            ),
            (
                "dyno_attach_url_nulled",
                "dynos",
                {"id": "d-1", "attach_url": "rendezvous://rendezvous.runtime.heroku.com:5000/secret", "state": "up"},
                {"id": "d-1", "attach_url": None, "state": "up"},
            ),
            (
                "row_without_sensitive_fields_untouched",
                "builds",
                {"id": "b-2", "status": "succeeded"},
                {"id": "b-2", "status": "succeeded"},
            ),
        ]
    )
    def test_capability_urls_never_reach_the_warehouse(
        self, _name: str, endpoint: str, row: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(200, [{"id": "app-1"}]),
            _response(200, [row]),
        ]

        with patch(PATCH_PATH, return_value=session):
            pages = list(get_rows("key", endpoint, MagicMock(), _manager()))

        assert pages == [[expected]]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    def test_maps_account_probe_status(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code)

        with patch(PATCH_PATH, return_value=session):
            assert validate_credentials("key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")

        with patch(PATCH_PATH, return_value=session):
            assert validate_credentials("key") is False


class TestSourceResponse:
    @parameterized.expand([(name,) for name in HEROKU_ENDPOINTS])
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        response = heroku_source("key", endpoint, MagicMock(), _manager())
        config = HEROKU_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            # updated_at moves on every write, which would rewrite partitions each sync.
            assert config.partition_key != "updated_at"
        else:
            assert response.partition_mode is None
