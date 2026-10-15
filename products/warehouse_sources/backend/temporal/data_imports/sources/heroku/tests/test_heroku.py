import datetime as dt
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heroku import HerokuSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku import (
    HEROKU_API_ACCEPT,
    HerokuResumeConfig,
    _month_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    DEFAULT_PAGE_SIZE,
    HEROKU_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source import HerokuSource

INITIAL_RANGE = f"id ..; order=asc,max={DEFAULT_PAGE_SIZE}"


def _driver() -> SourceDriver:
    return SourceDriver(HerokuSource(), HerokuSourceConfig(api_key="key"))


def _response(
    status_code: int = 200, json_data: list[dict[str, Any]] | None = None, next_range: str | None = None
) -> ScriptedResponse:
    return ScriptedResponse(
        status=status_code,
        json=json_data if json_data is not None else [],
        headers={"Next-Range": next_range} if next_range else {},
    )


class TestPagination:
    def test_follows_next_range_header_until_absent(self) -> None:
        next_range = "id ]a..; order=asc,max=1000"
        result = _driver().run(
            "apps",
            [_response(206, [{"id": "a"}], next_range=next_range), _response(200, [{"id": "b"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert [request.headers["range"] for request in result.requests] == [INITIAL_RANGE, next_range]
        assert all(request.headers["accept"] == HEROKU_API_ACCEPT for request in result.requests)

    def test_resumes_top_level_from_saved_cursor(self) -> None:
        cursor = "id ]a..; order=asc,max=1000"
        result = _driver().run(
            "apps", [_response(200, [{"id": "b"}])], resume_state=HerokuResumeConfig(next_range=cursor)
        )

        assert result.raised is None
        assert result.rows == [{"id": "b"}]
        assert result.requests[0].headers["range"] == cursor


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retries_transient_statuses_then_succeeds(self, _name: str, status_code: int) -> None:
        result = _driver().run("apps", [_response(status_code), _response(200, [{"id": "a"}])])

        assert result.raised is None
        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_credential_errors_raise_without_retry(self, _name: str, status_code: int) -> None:
        result = _driver().run("apps", [_response(status_code)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestFanOut:
    def test_resumes_from_bookmarked_app_with_saved_cursor(self) -> None:
        saved_cursor = "id ]rel-1..; order=asc,max=1000"
        result = _driver().run(
            "releases",
            [
                _response(200, [{"id": "app-1"}, {"id": "app-2"}, {"id": "app-3"}]),
                _response(200, [{"id": "rel-2"}]),
                _response(200, [{"id": "rel-3"}]),
            ],
            resume_state=HerokuResumeConfig(
                fanout_state={
                    "completed": ["/apps/app-1/releases"],
                    "current": "/apps/app-2/releases",
                    "child_state": {"next_range": saved_cursor},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "rel-2"}, {"id": "rel-3"}]
        # The already-completed app is never re-fetched.
        assert "https://api.heroku.com/apps/app-1/releases" not in result.urls
        # The resumed app starts from the saved cursor; the next app starts from a fresh first page.
        assert result.requests[1].headers["range"] == saved_cursor
        assert result.requests[2].headers["range"] == INITIAL_RANGE


class TestTeamMonthlyUsage:
    @parameterized.expand(
        [
            ("mid_year", dt.date(2026, 10, 2), {"start": "2025-11", "end": "2026-10"}),
            ("january", dt.date(2026, 1, 31), {"start": "2025-02", "end": "2026-01"}),
            ("december", dt.date(2026, 12, 1), {"start": "2026-01", "end": "2026-12"}),
        ]
    )
    def test_month_window_spans_twelve_months_including_current(
        self, _name: str, today: dt.date, expected: dict[str, str]
    ) -> None:
        assert _month_window(today) == expected


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
                "addon_attachment_log_input_url_nulled",
                "addon_attachments",
                {"id": "att-1", "log_input_url": "https://token:t.secret@1.us.logplex.io/logs", "name": "DATABASE"},
                {"id": "att-1", "log_input_url": None, "name": "DATABASE"},
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
        parent_pages = [_response(200, [{"id": "app-1"}])] if HEROKU_ENDPOINTS[endpoint].fan_out_parent else []
        result = _driver().run(endpoint, [*parent_pages, _response(200, [row])])

        assert result.raised is None
        assert result.rows == [expected]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    def test_maps_account_probe_status(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/account"


class TestSourceResponse:
    @parameterized.expand([(name,) for name in HEROKU_ENDPOINTS])
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response()])
        response = result.response
        config = HEROKU_ENDPOINTS[endpoint]

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            # updated_at moves on every write, which would rewrite partitions each sync.
            assert config.partition_key != "updated_at"
        else:
            assert response.partition_mode is None
