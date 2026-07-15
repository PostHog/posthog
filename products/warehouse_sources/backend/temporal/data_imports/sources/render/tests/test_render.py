from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.render import render
from products.warehouse_sources.backend.temporal.data_imports.sources.render.render import (
    RenderResumeConfig,
    _build_params,
    _fetch_page,
    _format_incremental_value,
    _unwrap_item,
    get_rows,
    render_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.render.settings import (
    RENDER_ENDPOINTS,
    RenderEndpointConfig,
)


def _response(payload: Any, status: int = 200) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: Error for url: https://api.render.com", response=response
        )
    return response


class FakeSession:
    """Returns queued page payloads in request order and records every requested URL."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> Any:
        self.urls.append(url)
        response = self._responses.pop(0)
        if isinstance(response, MagicMock):
            return response
        return _response(response)


def _manager(resume: RenderResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _rows(
    endpoint: str,
    responses: list[Any],
    manager: MagicMock | None = None,
    owner_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> tuple[list[list[dict]], FakeSession, MagicMock]:
    session = FakeSession(responses)
    manager = manager if manager is not None else _manager()
    with patch.object(render, "make_tracked_session", return_value=session):
        batches = list(
            get_rows(
                api_key="rnd_test",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                owner_id=owner_id,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
                incremental_field=incremental_field,
            )
        )
    return batches, session, manager


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (
                # Watermarks come back from the pipeline in whatever offset the API row carried;
                # sending a non-UTC offset to Render's ISO filters is undocumented territory.
                "non_utc_offset_converted",
                datetime(2026, 3, 4, 4, 58, 14, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-04T02:58:14Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestUnwrapItem:
    @parameterized.expand(
        [
            (
                "wrapped_with_sibling_cursor",
                {"service": {"id": "srv-1"}, "cursor": "c1"},
                "service",
                ({"id": "srv-1"}, "c1"),
            ),
            (
                "unwrapped_env_group_shape",
                {"id": "evg-1", "name": "group"},
                "envGroup",
                ({"id": "evg-1", "name": "group"}, None),
            ),
        ]
    )
    def test_unwrap_item(self, _name: str, item: dict, wrapper_key: str, expected: tuple) -> None:
        assert _unwrap_item(item, wrapper_key) == expected


class TestBuildParams:
    WATERMARK = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)

    @parameterized.expand(
        [
            ("services_updated_at", "services", "updatedAt", {"updatedAfter": "2026-03-04T02:58:14Z"}),
            ("deploys_finished_at", "deploys", "finishedAt", {"finishedAfter": "2026-03-04T02:58:14Z"}),
            ("deploys_default_field", "deploys", None, {"finishedAfter": "2026-03-04T02:58:14Z"}),
            ("events_timestamp_maps_to_start_time", "events", "timestamp", {"startTime": "2026-03-04T02:58:14Z"}),
        ]
    )
    def test_incremental_field_maps_to_server_side_filter(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_params: dict
    ) -> None:
        params = _build_params(
            RENDER_ENDPOINTS[endpoint],
            owner_id=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self.WATERMARK,
            incremental_field=incremental_field,
            logger=MagicMock(),
        )
        for key, value in expected_params.items():
            assert params[key] == value

    def test_no_watermark_means_no_time_filter(self) -> None:
        params = _build_params(
            RENDER_ENDPOINTS["services"],
            owner_id=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updatedAt",
            logger=MagicMock(),
        )
        assert "updatedAfter" not in params

    @parameterized.expand(
        [
            ("owner_filter_on_supporting_endpoint", "services", True),
            ("no_owner_filter_on_fan_out_child", "deploys", False),
        ]
    )
    def test_owner_filter(self, _name: str, endpoint: str, expects_owner: bool) -> None:
        params = _build_params(
            RENDER_ENDPOINTS[endpoint],
            owner_id="tea-123",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            logger=MagicMock(),
        )
        assert ("ownerId" in params) == expects_owner

    def test_incremental_field_without_server_filter_is_skipped(self) -> None:
        config = RenderEndpointConfig(name="x", path="/x", wrapper_key="x", default_incremental_field="updatedAt")
        logger = MagicMock()
        params = _build_params(
            config,
            owner_id=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self.WATERMARK,
            incremental_field="updatedAt",
            logger=logger,
        )
        assert params == {"limit": 100}
        logger.warning.assert_called_once()


class TestPagination:
    def test_follows_last_item_cursor_and_stops_on_empty_page(self) -> None:
        batches, session, manager = _rows(
            "services",
            [
                [
                    {"service": {"id": "srv-1"}, "cursor": "c1"},
                    {"service": {"id": "srv-2"}, "cursor": "c2"},
                ],
                [{"service": {"id": "srv-3"}, "cursor": "c3"}],
                [],
            ],
        )

        assert batches == [[{"id": "srv-1"}, {"id": "srv-2"}], [{"id": "srv-3"}]]
        assert "cursor" not in _query(session.urls[0])
        assert _query(session.urls[1])["cursor"] == ["c2"]
        assert _query(session.urls[2])["cursor"] == ["c3"]
        # State saved after each yielded page so a crash re-yields the last page.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [state.cursor for state in saved] == ["c2", "c3"]

    def test_resume_starts_from_saved_cursor(self) -> None:
        batches, session, _ = _rows(
            "services",
            [[{"service": {"id": "srv-9"}, "cursor": "c9"}], []],
            manager=_manager(RenderResumeConfig(cursor="c-resume")),
        )

        assert _query(session.urls[0])["cursor"] == ["c-resume"]
        assert batches == [[{"id": "srv-9"}]]

    def test_full_page_without_cursor_stops_instead_of_looping(self) -> None:
        # Unwrapped responses (env groups) carry no cursor: a full page must terminate with a
        # truncation warning, not refetch the same page forever.
        page = [{"id": f"evg-{i}"} for i in range(100)]
        batches, session, _ = _rows("env_groups", [page])

        assert len(batches) == 1
        assert len(session.urls) == 1


class TestFanOut:
    SERVICES_PAGE = [
        {"service": {"id": "srv-1", "createdAt": "2024-01-01T00:00:00Z"}},
        {"service": {"id": "srv-2", "createdAt": "2024-02-01T00:00:00Z"}},
    ]

    def test_deploys_fetched_per_service_with_injected_service_id(self) -> None:
        batches, session, manager = _rows(
            "deploys",
            [
                self.SERVICES_PAGE,
                [{"deploy": {"id": "dep-1", "status": "live"}}],
                [{"deploy": {"id": "dep-2", "status": "live"}}],
            ],
        )

        assert urlparse(session.urls[1]).path == "/v1/services/srv-1/deploys"
        assert urlparse(session.urls[2]).path == "/v1/services/srv-2/deploys"
        # Deploy payloads omit the service id; rows must carry it for the composite primary key.
        assert batches == [
            [{"serviceId": "srv-1", "id": "dep-1", "status": "live"}],
            [{"serviceId": "srv-2", "id": "dep-2", "status": "live"}],
        ]
        # The bookmark advances to the next parent so a crash between parents resumes correctly.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert RenderResumeConfig(cursor=None, parent_id="srv-2") in saved

    def test_deleted_parent_404_is_skipped(self) -> None:
        batches, _, _ = _rows(
            "deploys",
            [
                self.SERVICES_PAGE,
                _response({"message": "Not Found"}, status=404),
                [{"deploy": {"id": "dep-2"}}],
            ],
        )

        assert batches == [[{"serviceId": "srv-2", "id": "dep-2"}]]

    def test_resume_skips_parents_before_bookmark_and_seeds_cursor(self) -> None:
        batches, session, _ = _rows(
            "deploys",
            [
                self.SERVICES_PAGE,
                [{"deploy": {"id": "dep-5"}}],
            ],
            manager=_manager(RenderResumeConfig(cursor="c-mid", parent_id="srv-2")),
        )

        deploy_urls = [url for url in session.urls if "/deploys" in url]
        assert len(deploy_urls) == 1
        assert urlparse(deploy_urls[0]).path == "/v1/services/srv-2/deploys"
        assert _query(deploy_urls[0])["cursor"] == ["c-mid"]

    def test_resume_bookmark_for_deleted_parent_restarts_from_first_parent(self) -> None:
        _, session, _ = _rows(
            "deploys",
            [
                self.SERVICES_PAGE,
                [{"deploy": {"id": "dep-1"}}],
                [{"deploy": {"id": "dep-2"}}],
            ],
            manager=_manager(RenderResumeConfig(cursor="c-mid", parent_id="srv-gone")),
        )

        deploy_urls = [url for url in session.urls if "/deploys" in url]
        assert urlparse(deploy_urls[0]).path == "/v1/services/srv-1/deploys"
        assert "cursor" not in _query(deploy_urls[0])

    def test_environments_pass_project_id_as_query_param(self) -> None:
        _, session, _ = _rows(
            "environments",
            [
                [{"project": {"id": "prj-1"}}],
                [{"environment": {"id": "env-1", "projectId": "prj-1"}}],
            ],
        )

        env_url = session.urls[1]
        assert urlparse(env_url).path == "/v1/environments"
        assert _query(env_url)["projectId"] == ["prj-1"]

    def test_events_full_refresh_uses_service_created_at_as_window_start(self) -> None:
        # The events endpoint defaults to the last hour server-side; omitting startTime on a
        # full refresh would silently drop everything older.
        _, session, _ = _rows(
            "events",
            [
                [{"service": {"id": "srv-1", "createdAt": "2024-01-01T00:00:00Z"}}],
                [{"event": {"id": "evt-1", "serviceId": "srv-1"}}],
            ],
        )

        assert _query(session.urls[1])["startTime"] == ["2024-01-01T00:00:00Z"]

    def test_events_incremental_watermark_overrides_window_start(self) -> None:
        _, session, _ = _rows(
            "events",
            [
                [{"service": {"id": "srv-1", "createdAt": "2024-01-01T00:00:00Z"}}],
                [{"event": {"id": "evt-1", "serviceId": "srv-1"}}],
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="timestamp",
        )

        assert _query(session.urls[1])["startTime"] == ["2026-03-04T02:58:14Z"]


class TestSensitiveEndpointHandling:
    def test_env_group_secret_values_are_redacted_from_rows(self) -> None:
        # Env var values and secret-file contents are credentials the key is only meant to use
        # for sync; leaking them into a queryable table exposes database URLs and API tokens.
        batches, _, _ = _rows(
            "env_groups",
            [
                [
                    {
                        "id": "evg-1",
                        "name": "prod",
                        "envVars": [{"key": "DATABASE_URL", "value": "postgres://user:pw@host/db"}],
                        "secretFiles": [{"name": "config.yaml", "contents": "token: super-secret"}],
                    }
                ],
            ],
        )

        row = batches[0][0]
        # Metadata survives so the table stays useful.
        assert row["id"] == "evg-1"
        assert row["name"] == "prod"
        assert row["envVars"][0]["key"] == "DATABASE_URL"
        assert row["secretFiles"][0]["name"] == "config.yaml"
        # The actual secrets do not.
        assert row["envVars"][0]["value"] == render.REDACTED_VALUE
        assert row["secretFiles"][0]["contents"] == render.REDACTED_VALUE

    @parameterized.expand(
        [
            # Sensitive endpoints skip sample capture — capture snapshots the raw response before
            # row-level redaction, so it would otherwise persist secrets to the sample store.
            ("env_groups", [{"id": "evg-1"}], False),
            ("owners", [{"owner": {"id": "own-1"}}], True),
        ]
    )
    def test_sample_capture_disabled_for_sensitive_endpoints(
        self, endpoint: str, page: list[dict], expected_capture: bool
    ) -> None:
        session = FakeSession([page])
        with patch.object(render, "make_tracked_session", return_value=session) as make_session:
            list(
                get_rows(
                    api_key="rnd_test",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )

        make_session.assert_called_once_with(capture=expected_capture)


class TestFetchPage:
    def test_retryable_status_is_retried_until_success(self) -> None:
        session = FakeSession([_response({"message": "rate limited"}, status=429), [{"owner": {"id": "own-1"}}]])
        result = _fetch_page(cast(requests.Session, session), "https://api.render.com/v1/owners", {}, MagicMock())

        assert result == [{"owner": {"id": "own-1"}}]
        assert len(session.urls) == 2

    def test_auth_error_raises_without_retry(self) -> None:
        session = FakeSession([_response({"message": "Unauthorized"}, status=401)])
        with pytest.raises(requests.HTTPError):
            _fetch_page(cast(requests.Session, session), "https://api.render.com/v1/owners", {}, MagicMock())

        assert len(session.urls) == 1


class TestRenderSourceResponse:
    @parameterized.expand(
        [
            ("services", ["id"], ["createdAt"]),
            # Fan-out children key on (parent, id): a non-unique key multi-matches on every
            # delta merge and degrades each sync until the pod OOMs.
            ("deploys", ["serviceId", "id"], ["createdAt"]),
            ("events", ["serviceId", "id"], ["timestamp"]),
            ("owners", ["id"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_primary_keys: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        response = render_source(
            api_key="rnd_test", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )

        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
        # Render documents no list ordering, so the watermark must only persist at job end.
        assert response.sort_mode == "desc"
