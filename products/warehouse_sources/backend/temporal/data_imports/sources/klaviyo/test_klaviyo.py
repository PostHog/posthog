import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klaviyo import (
    KlaviyoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo import klaviyo
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.constants import (
    KLAVIYO_API_VERSION_2024_10_15,
    KLAVIYO_API_VERSION_2026_07_15,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.klaviyo import (
    KlaviyoResumeConfig,
    _build_filter,
    _build_initial_params,
    _clamp_future_value_to_now,
    _format_incremental_value,
    get_rows,
    klaviyo_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.settings import (
    KLAVIYO_ENDPOINTS,
    KlaviyoEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.source import KlaviyoSource


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_with_microseconds",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor-value", "some-cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result


class TestBuildFilter:
    @parameterized.expand(
        [
            (
                "incremental_only",
                KLAVIYO_ENDPOINTS["events"],
                "datetime",
                "2026-03-04T02:58:14.000Z",
                "greater-than(datetime,2026-03-04T02:58:14.000Z)",
            ),
            (
                "base_filter_only",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                None,
                None,
                "equals(messages.channel,'email')",
            ),
            (
                "combined_base_and_incremental",
                KLAVIYO_ENDPOINTS["email_campaigns"],
                "updated_at",
                "2026-03-04T02:58:14.000Z",
                "and(equals(messages.channel,'email'),greater-than(updated_at,2026-03-04T02:58:14.000Z))",
            ),
            ("no_filter", KLAVIYO_ENDPOINTS["metrics"], None, None, None),
        ]
    )
    def test_build_filter(
        self, _name: str, config: KlaviyoEndpointConfig, field: str | None, value: str | None, expected: str | None
    ) -> None:
        assert _build_filter(config, field, value) == expected


class TestBuildInitialParams:
    def test_events_incremental_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert "+00:00" not in params["filter"]
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"

    def test_lookback_window_uses_z_suffix(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="datetime",
        )
        assert "filter" in params
        assert "+00:00" not in params["filter"]
        assert params["filter"].endswith("Z)")

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped_to_now(self) -> None:
        # A future-dated cursor would otherwise build greater-than(datetime,<future>),
        # which Klaviyo rejects with a 400 and wedges every subsequent sync.
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-06-15T12:00:00.000Z)"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_cursor_is_not_modified(self) -> None:
        config = KLAVIYO_ENDPOINTS["events"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="datetime",
        )
        assert params["filter"] == "greater-than(datetime,2026-03-04T02:58:14.000Z)"

    def test_list_profiles_incremental_applies_lookback_and_extra_params(self) -> None:
        # Dropping the 24h lookback silently loses joins that landed in already-fetched lists mid-run.
        config = KLAVIYO_ENDPOINTS["list_profiles"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="joined_group_at",
        )
        assert params["filter"] == "greater-than(joined_group_at,2026-03-03T02:58:14.000Z)"
        assert params["sort"] == "-joined_group_at"
        assert params["fields[profile]"] == "joined_group_at"

    def test_list_profiles_first_sync_has_no_filter(self) -> None:
        # Mishandling a missing watermark (e.g. greater-than(joined_group_at,None)) 400s every first sync.
        config = KLAVIYO_ENDPOINTS["list_profiles"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="joined_group_at",
        )
        assert "filter" not in params

    @freeze_time("2026-06-15T12:00:00Z")
    def test_lookback_applies_after_future_clamp(self) -> None:
        # Clamping after the lookback would erase the overlap window for a future-dated cursor.
        config = KLAVIYO_ENDPOINTS["list_profiles"]
        params = _build_initial_params(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
            incremental_field="joined_group_at",
        )
        assert params["filter"] == "greater-than(joined_group_at,2026-06-14T12:00:00.000Z)"


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_naive_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_date_is_unchanged(self) -> None:
        assert _clamp_future_value_to_now(date(2026, 3, 4)) == date(2026, 3, 4)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor-value") == "some-cursor-value"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            # 401/403 surfaced as a requests HTTPError when `fetch_page` calls `raise_for_status()`.
            # The per-request path/query/timestamp varies, but the status text and base host are stable.
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://a.klaviyo.com/api/events?filter=greater-than(datetime,2026-06-15T13:03:18.000Z)",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://a.klaviyo.com/api/metrics",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            # Transient/infra errors and server-side failures must stay retryable.
            ("read_timeout", "HTTPSConnectionPool(host='a.klaviyo.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://a.klaviyo.com/api/events",
            ),
            ("connection_reset", "Connection reset by peer"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = KlaviyoSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            # A plan-gated 403 (e.g. webhooks without Advanced KDP) carries Klaviyo's body detail on
            # the message and must map to the plan message, not the scope one the user can't act on.
            (
                "plan_gated",
                "HTTPError: 403 Client Error: Forbidden for url: https://a.klaviyo.com/api/webhooks (You must have Advanced KDP enabled to use this endpoint.)",
                "Advanced KDP add-on",
            ),
            # A scope-denied 403 keeps pointing at the key's read scopes.
            (
                "scope_missing",
                "HTTPError: 403 Client Error: Forbidden for url: https://a.klaviyo.com/api/metrics",
                "missing the read permissions",
            ),
        ]
    )
    def test_first_matching_entry_supplies_the_user_facing_message(
        self, _name: str, observed_error: str, expected_snippet: str
    ) -> None:
        # Mirrors update_external_data_job_model: the first matching entry becomes the user-facing
        # error, so reordering the dict (or broadening a pattern) regresses the shown message.
        matches = [
            friendly
            for pattern, friendly in KlaviyoSource().get_non_retryable_errors().items()
            if error_message_matches(observed_error, [pattern])
        ]
        assert matches and matches[0] is not None
        assert expected_snippet in matches[0]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        # A transient network failure on the first attempt must retry rather than fail the whole sync.
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(klaviyo._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = klaviyo._fetch_page(session, "https://a.klaviyo.com/api/events", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_transient_error_reraised_after_exhausting_attempts(self) -> None:
        # After the 5-attempt cap the last transient error must surface (reraise=True), not be swallowed.
        session = MagicMock()
        session.get.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength")

        with patch.object(klaviyo._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.exceptions.ChunkedEncodingError):
                klaviyo._fetch_page(session, "https://a.klaviyo.com/api/events", {}, MagicMock())

        assert session.get.call_count == 5


def _response_with_status(status_code: int, body: bytes | None = None, url: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if body is not None:
        response._content = body
    if url is not None:
        response.url = url
    return response


class TestFetchPageErrorDetail:
    _url = "https://a.klaviyo.com/api/webhooks"

    def _session_returning(self, response: requests.Response) -> MagicMock:
        session = MagicMock()
        session.get.return_value = response
        return session

    def test_klaviyo_detail_rides_on_the_http_error(self) -> None:
        # A 403's status and URL alone can't distinguish a key missing a read scope from an endpoint
        # the account's Klaviyo plan doesn't include; without the body detail on the message, the
        # non-retryable mapping blames scopes the user may have already granted.
        body = json.dumps(
            {
                "errors": [
                    {
                        "code": "permission_denied",
                        "title": "You do not have permission to perform this action.",
                        "detail": "You must have Advanced KDP enabled to use this endpoint.",
                    }
                ]
            }
        ).encode()

        with pytest.raises(requests.HTTPError) as exc_info:
            klaviyo._fetch_page(
                self._session_returning(_response_with_status(403, body=body, url=self._url)),
                self._url,
                {},
                MagicMock(),
            )

        assert "You must have Advanced KDP enabled to use this endpoint." in str(exc_info.value)
        assert "403 Client Error" in str(exc_info.value)
        assert self._url in str(exc_info.value)
        # Fan-out handlers branch on `exc.response.status_code`, so the response must stay attached.
        assert exc_info.value.response is not None
        assert exc_info.value.response.status_code == 403

    def test_non_json_error_body_still_raises_the_plain_error(self) -> None:
        # A gateway HTML error page must not crash detail extraction and mask the real HTTPError.
        with pytest.raises(requests.HTTPError) as exc_info:
            klaviyo._fetch_page(
                self._session_returning(_response_with_status(403, body=b"<html>denied</html>", url=self._url)),
                self._url,
                {},
                MagicMock(),
            )

        assert "403 Client Error" in str(exc_info.value)
        assert self._url in str(exc_info.value)


class _FakeResumableManager:
    def __init__(self, state: KlaviyoResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[KlaviyoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> KlaviyoResumeConfig | None:
        return self._state

    def save_state(self, data: KlaviyoResumeConfig) -> None:
        self.saved.append(data)


def _list_url(list_id: str, filter_value: str | None = None) -> str:
    filter_part = f"&filter={filter_value}" if filter_value else ""
    return (
        f"https://a.klaviyo.com/api/lists/{list_id}/profiles"
        f"?page[size]=100{filter_part}&sort=-joined_group_at&fields[profile]=joined_group_at"
    )


class TestListProfilesFanOut:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **incremental: Any
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for table in get_rows(
            api_key="pk_test",
            endpoint="list_profiles",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(table.to_pylist())
        return rows

    def test_config_is_opt_in_fan_out_with_composite_pk(self) -> None:
        config = KLAVIYO_ENDPOINTS["list_profiles"]
        assert config.fan_out is not None
        assert config.fan_out.membership_rows is True
        assert config.should_sync_default is False
        assert config.primary_keys == ["list_id", "profile_id"]

    def test_schema_supports_incremental_merge_but_not_append(self) -> None:
        # Append mode would materialize the intentional 24h lookback re-pulls as duplicate rows.
        schemas = {s.name: s for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        list_profiles = schemas["list_profiles"]
        assert list_profiles.supports_incremental is True
        assert list_profiles.supports_append is False
        assert list_profiles.should_sync_default is False
        assert [f["field"] for f in list_profiles.incremental_fields] == ["joined_group_at"]

    def test_lists_request_stays_within_klaviyo_page_size_cap(self, monkeypatch: Any) -> None:
        # Klaviyo's Get Lists endpoint caps page[size] at 10; a larger value 400s the whole fan-out.
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched_urls.append(url)
            return {"data": [], "links": {"next": None}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        fan_out = KLAVIYO_ENDPOINTS["list_profiles"].fan_out
        assert fan_out is not None
        list(klaviyo._iter_fan_out_parents(MagicMock(), {}, MagicMock(), fan_out))

        assert fetched_urls == ["https://a.klaviyo.com/api/lists?page[size]=10"]

    def test_fans_out_over_every_list_into_membership_rows(self, monkeypatch: Any) -> None:
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}, {"id": "L2"}],
                "links": {"next": None},
            },
            _list_url("L1"): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2025-11-08T00:00:00+00:00"}},
                    # An item without attributes must yield a null joined_group_at, not crash the sync.
                    {"type": "profile", "id": "P2"},
                ],
                "links": {"next": None},
            },
            _list_url("L2"): {
                "data": [
                    {"type": "profile", "id": "P3", "attributes": {"joined_group_at": "2025-12-01T09:30:00+00:00"}}
                ],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1", "joined_group_at": "2025-11-08T00:00:00+00:00"},
            {"list_id": "L1", "profile_id": "P2", "joined_group_at": None},
            {"list_id": "L2", "profile_id": "P3", "joined_group_at": "2025-12-01T09:30:00+00:00"},
        ]

    def test_incremental_run_filters_with_lookback_on_every_list(self, monkeypatch: Any) -> None:
        # Fixtures are keyed by exact URL, so this fails loudly (KeyError) if the fan-out stops
        # forwarding the incremental inputs and silently reverts to a full refresh.
        expected_filter = "greater-than(joined_group_at,2026-03-03T02:58:14.000Z)"
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}, {"id": "L2"}],
                "links": {"next": None},
            },
            _list_url("L1", filter_value=expected_filter): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2026-03-04T01:00:00+00:00"}}
                ],
                "links": {"next": None},
            },
            _list_url("L2", filter_value=expected_filter): {
                "data": [],
                "links": {"next": None},
            },
        }
        rows = self._collect(
            _FakeResumableManager(),
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="joined_group_at",
        )
        assert rows == [{"list_id": "L1", "profile_id": "P1", "joined_group_at": "2026-03-04T01:00:00+00:00"}]

    def test_follows_membership_pagination(self, monkeypatch: Any) -> None:
        next_url = "https://a.klaviyo.com/api/lists/L1/profiles?page[cursor]=abc"
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            _list_url("L1"): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2025-11-08T00:00:00+00:00"}}
                ],
                "links": {"next": next_url},
            },
            next_url: {
                "data": [
                    {"type": "profile", "id": "P2", "attributes": {"joined_group_at": "2025-11-07T00:00:00+00:00"}}
                ],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1", "joined_group_at": "2025-11-08T00:00:00+00:00"},
            {"list_id": "L1", "profile_id": "P2", "joined_group_at": "2025-11-07T00:00:00+00:00"},
        ]

    def test_resume_from_deleted_list_restarts_from_first(self, monkeypatch: Any) -> None:
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            _list_url("L1"): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2025-11-08T00:00:00+00:00"}}
                ],
                "links": {"next": None},
            },
        }
        manager = _FakeResumableManager(KlaviyoResumeConfig(next_url=None, list_id="DELETED"))
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"list_id": "L1", "profile_id": "P1", "joined_group_at": "2025-11-08T00:00:00+00:00"}]

    def test_list_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}, {"id": "GONE"}, {"id": "L2"}],
                "links": {"next": None},
            },
            _list_url("L1"): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2025-11-08T00:00:00+00:00"}}
                ],
                "links": {"next": None},
            },
            _list_url("GONE"): not_found,
            _list_url("L2"): {
                "data": [
                    {"type": "profile", "id": "P2", "attributes": {"joined_group_at": "2025-12-01T09:30:00+00:00"}}
                ],
                "links": {"next": None},
            },
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [
            {"list_id": "L1", "profile_id": "P1", "joined_group_at": "2025-11-08T00:00:00+00:00"},
            {"list_id": "L2", "profile_id": "P2", "joined_group_at": "2025-12-01T09:30:00+00:00"},
        ]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            "https://a.klaviyo.com/api/lists?page[size]=10": {
                "data": [{"id": "L1"}],
                "links": {"next": None},
            },
            _list_url("L1"): server_error,
        }
        with pytest.raises(requests.HTTPError):
            self._collect(_FakeResumableManager(), monkeypatch, pages)


def _collect_rows(endpoint: str, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="pk_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestGeneralizedFanOut:
    def test_segment_membership_uses_the_segment_parent_and_id_column(self, monkeypatch: Any) -> None:
        # The fan-out was originally hardcoded to /lists and a list_id column; a regression there
        # would silently emit list_id rows (or 400 on the wrong parent page size) for segments.
        pages = {
            "https://a.klaviyo.com/api/segments?page[size]=10": {
                "data": [{"id": "S1"}],
                "links": {"next": None},
            },
            (
                "https://a.klaviyo.com/api/segments/S1/profiles"
                "?page[size]=100&sort=-joined_group_at&fields[profile]=joined_group_at"
            ): {
                "data": [
                    {"type": "profile", "id": "P1", "attributes": {"joined_group_at": "2026-01-08T00:00:00+00:00"}}
                ],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("segment_profiles", monkeypatch, pages)
        assert rows == [{"segment_id": "S1", "profile_id": "P1", "joined_group_at": "2026-01-08T00:00:00+00:00"}]

    def test_flow_actions_yield_the_flattened_resource_tagged_with_its_flow(self, monkeypatch: Any) -> None:
        # Non-membership fan-out rows must keep the resource's own fields and gain the parent id;
        # dropping flow_id makes the table impossible to join back to flows.
        pages = {
            "https://a.klaviyo.com/api/flows?page[size]=50": {
                "data": [{"id": "F1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flows/F1/flow-actions?page[size]=50&sort=-updated": {
                "data": [
                    {
                        "type": "flow-action",
                        "id": "A1",
                        "attributes": {
                            "created": "2026-01-01T00:00:00+00:00",
                            "updated": "2026-02-01T00:00:00+00:00",
                        },
                    }
                ],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("flow_actions", monkeypatch, pages)
        assert rows == [
            {
                "type": "flow-action",
                "id": "A1",
                "created": "2026-01-01T00:00:00+00:00",
                "updated": "2026-02-01T00:00:00+00:00",
                "flow_id": "F1",
            }
        ]

    def test_coupon_codes_fan_out_over_coupons_instead_of_the_unfiltered_collection(self, monkeypatch: Any) -> None:
        # Klaviyo's flat /coupon-codes list requires a coupon.id or profile.id filter and 400s
        # without one; fanning out per coupon avoids ever calling that unfiltered endpoint.
        pages = {
            "https://a.klaviyo.com/api/coupons?page[size]=100": {
                "data": [{"id": "C1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/coupons/C1/coupon-codes?page[size]=100": {
                "data": [
                    {
                        "type": "coupon-code",
                        "id": "C1-CODE1",
                        "attributes": {"unique_code": "CODE1", "status": "UNASSIGNED"},
                    }
                ],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("coupon_codes", monkeypatch, pages)
        assert rows == [
            {
                "type": "coupon-code",
                "id": "C1-CODE1",
                "unique_code": "CODE1",
                "status": "UNASSIGNED",
                "coupon_id": "C1",
            }
        ]

    def test_custom_object_records_fan_out_over_object_types_without_a_parent_page_size(self, monkeypatch: Any) -> None:
        # /object-types rejects page[size], so the parent must be enumerated by cursor links alone
        # (no ?page[size] on its URL); each record carries its object_type_id and flattens
        # record_properties onto the row. Fixtures key by exact URL, so a stray page[size] KeyErrors.
        pages = {
            "https://a.klaviyo.com/api/object-types": {
                "data": [{"id": "OT1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/object-types/OT1/object-records?page[size]=100": {
                "data": [
                    {
                        "type": "object-record",
                        "id": "OT1:::rec-1",
                        "attributes": {"record_properties": {"name": "Fluffy"}},
                    }
                ],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("custom_object_records", monkeypatch, pages)
        # The batcher serializes the nested record_properties object to a JSON string in the arrow
        # table, which is how it lands in the warehouse column.
        assert rows == [
            {
                "type": "object-record",
                "id": "OT1:::rec-1",
                "record_properties": '{"name":"Fluffy"}',
                "object_type_id": "OT1",
            }
        ]

    def test_flow_messages_walk_flows_then_actions_and_carry_both_ancestors(self, monkeypatch: Any) -> None:
        # Two-level fan-out: the intermediate path must be formatted with the grandparent id, and
        # each row must carry both ancestors or the flow -> action -> message chain can't be rebuilt.
        pages = {
            "https://a.klaviyo.com/api/flows?page[size]=50": {
                "data": [{"id": "F1"}, {"id": "F2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flows/F1/flow-actions?page[size]=50": {
                "data": [{"id": "A1"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flows/F2/flow-actions?page[size]=50": {
                "data": [{"id": "A2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flow-actions/A1/flow-messages?page[size]=50&sort=-updated": {
                "data": [{"type": "flow-message", "id": "M1", "attributes": {"channel": "email"}}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flow-actions/A2/flow-messages?page[size]=50&sort=-updated": {
                "data": [{"type": "flow-message", "id": "M2", "attributes": {"channel": "sms"}}],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("flow_messages", monkeypatch, pages)
        assert rows == [
            {"type": "flow-message", "id": "M1", "channel": "email", "flow_action_id": "A1", "flow_id": "F1"},
            {"type": "flow-message", "id": "M2", "channel": "sms", "flow_action_id": "A2", "flow_id": "F2"},
        ]

    def test_deleted_flow_is_skipped_while_enumerating_two_level_parents(self, monkeypatch: Any) -> None:
        # A flow deleted between enumeration and the action fetch must not fail the whole sync.
        pages = {
            "https://a.klaviyo.com/api/flows?page[size]=50": {
                "data": [{"id": "GONE"}, {"id": "F2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flows/GONE/flow-actions?page[size]=50": requests.HTTPError(
                response=_response_with_status(404)
            ),
            "https://a.klaviyo.com/api/flows/F2/flow-actions?page[size]=50": {
                "data": [{"id": "A2"}],
                "links": {"next": None},
            },
            "https://a.klaviyo.com/api/flow-actions/A2/flow-messages?page[size]=50&sort=-updated": {
                "data": [{"type": "flow-message", "id": "M2", "attributes": {"channel": "sms"}}],
                "links": {"next": None},
            },
        }
        rows = _collect_rows("flow_messages", monkeypatch, pages)
        assert rows == [{"type": "flow-message", "id": "M2", "channel": "sms", "flow_action_id": "A2", "flow_id": "F2"}]

    @parameterized.expand(
        [
            ("list_profiles", ["list_id", "profile_id"]),
            ("segment_profiles", ["segment_id", "profile_id"]),
        ]
    )
    def test_membership_tables_key_on_parent_and_profile(self, endpoint: str, expected_keys: list[str]) -> None:
        # A membership key that isn't unique table-wide seeds duplicates that every later merge
        # multi-matches, which is how these fan-outs OOM.
        assert KLAVIYO_ENDPOINTS[endpoint].primary_keys == expected_keys


class TestProfilesSubscriptionsRoundTrip:
    def test_suppression_and_consent_land_in_the_synced_row(self, monkeypatch: Any) -> None:
        # Suppression and consent status only exist inside the nested subscriptions object; if
        # flattening or batching drops or reshapes it, a team exporting unsubscribes before a
        # sending-platform migration silently loses exactly the profiles that must not be messaged.
        suppressed_subscriptions = {
            "email": {
                "marketing": {
                    "can_receive_email_marketing": False,
                    "consent": "UNSUBSCRIBED",
                    "suppression": [{"reason": "USER_SUPPRESSED", "timestamp": "2026-01-02T00:00:00+00:00"}],
                    "list_suppressions": [
                        {"list_id": "L1", "reason": "UNSUBSCRIBE", "timestamp": "2026-01-03T00:00:00+00:00"}
                    ],
                }
            }
        }
        consented_subscriptions = {
            "email": {"marketing": {"can_receive_email_marketing": True, "consent": "SUBSCRIBED"}},
            "sms": {
                "marketing": {
                    "can_receive_sms_marketing": True,
                    "consent": "SUBSCRIBED",
                    "consent_timestamp": "2026-02-01T00:00:00+00:00",
                }
            },
            "mobile_push": {"marketing": {"can_receive_push_marketing": False, "consent": "UNSUBSCRIBED"}},
        }
        pages = {
            "https://a.klaviyo.com/api/profiles?additional-fields[profile]=subscriptions": {
                "data": [
                    {
                        "type": "profile",
                        "id": "P_SUPPRESSED",
                        "attributes": {"email": "suppressed@example.com", "subscriptions": suppressed_subscriptions},
                    },
                    {
                        "type": "profile",
                        "id": "P_CONSENTED",
                        "attributes": {"email": "consented@example.com", "subscriptions": consented_subscriptions},
                    },
                ],
                "links": {"next": None},
            },
        }

        rows = {row["id"]: row for row in _collect_rows("profiles", monkeypatch, pages)}

        assert rows["P_SUPPRESSED"]["email"] == "suppressed@example.com"
        assert json.loads(rows["P_SUPPRESSED"]["subscriptions"]) == suppressed_subscriptions
        assert json.loads(rows["P_CONSENTED"]["subscriptions"]) == consented_subscriptions


class TestValuesReports:
    @staticmethod
    def _pages(report_path: str, results: list[dict], next_url: str | None = None) -> dict[str, Any]:
        return {
            "https://a.klaviyo.com/api/metrics": {
                "data": [
                    {"id": "M_OTHER", "attributes": {"name": "Viewed Product"}},
                    {"id": "M_ORDER", "attributes": {"name": "Placed Order"}},
                ],
                "links": {"next": None},
            },
            f"https://a.klaviyo.com/api{report_path}": {
                "data": {"type": "campaign-values-report", "attributes": {"results": results}},
                "links": {"next": next_url},
            },
        }

    def test_groupings_and_statistics_flatten_into_one_row(self, monkeypatch: Any) -> None:
        # The report nests groupings and statistics under separate objects; keeping that nesting
        # would make the table unqueryable and break the declared primary key.
        pages = self._pages(
            "/campaign-values-reports",
            [
                {
                    "groupings": {"campaign_id": "C1", "campaign_message_id": "CM1", "send_channel": "email"},
                    "statistics": {"opens": 123, "open_rate": 0.8253},
                }
            ],
        )
        rows = _collect_rows("campaign_values_reports", monkeypatch, pages)
        assert rows == [
            {
                "campaign_id": "C1",
                "campaign_message_id": "CM1",
                "send_channel": "email",
                "opens": 123,
                "open_rate": 0.8253,
                "timeframe_key": "last_365_days",
                "conversion_metric_id": "M_ORDER",
            }
        ]

    def test_report_body_carries_the_required_query(self, monkeypatch: Any) -> None:
        # Klaviyo 400s a values report that is missing statistics, timeframe, or conversion metric.
        captured: dict[str, Any] = {}

        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            if json_body is not None:
                captured["body"] = json_body
                captured["content_type"] = headers.get("Content-Type")
                return {"data": {"attributes": {"results": []}}, "links": {}}
            return {"data": [{"id": "M_ORDER", "attributes": {"name": "Placed Order"}}], "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        list(
            get_rows(
                api_key="pk_test",
                endpoint="flow_values_reports",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )

        attributes = captured["body"]["data"]["attributes"]
        assert captured["body"]["data"]["type"] == "flow-values-report"
        assert captured["content_type"] == "application/vnd.api+json"
        assert attributes["timeframe"] == {"key": "last_365_days"}
        assert attributes["conversion_metric_id"] == "M_ORDER"
        assert attributes["group_by"] == ["flow_id", "flow_message_id", "send_channel"]
        assert "opens" in attributes["statistics"]

    def test_configured_conversion_metric_skips_the_lookup(self, monkeypatch: Any) -> None:
        # A user-set metric must win, and must not cost an extra /metrics walk on every sync.
        fetched_urls: list[str] = []

        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            fetched_urls.append(url)
            return {"data": {"attributes": {"results": []}}, "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        list(
            get_rows(
                api_key="pk_test",
                endpoint="campaign_values_reports",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                conversion_metric_id="CHOSEN",
            )
        )

        assert fetched_urls == ["https://a.klaviyo.com/api/campaign-values-reports"]

    def test_falls_back_to_the_first_metric_when_placed_order_is_absent(self, monkeypatch: Any) -> None:
        # Accounts without ecommerce have no Placed Order metric; the report still needs one.
        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            if json_body is not None:
                return {
                    "data": {
                        "attributes": {"results": [{"groupings": {"campaign_id": "C1"}, "statistics": {"opens": 1}}]}
                    },
                    "links": {},
                }
            return {"data": [{"id": "M_FIRST", "attributes": {"name": "Viewed Product"}}], "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        rows = [
            row
            for table in get_rows(
                api_key="pk_test",
                endpoint="campaign_values_reports",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
            for row in table.to_pylist()
        ]

        assert rows[0]["conversion_metric_id"] == "M_FIRST"

    def test_ineligible_conversion_metric_skips_the_report_instead_of_failing_the_sync(self, monkeypatch: Any) -> None:
        # Klaviyo rejects some metrics (e.g. system metrics) as conversion metrics for values
        # reports; the same metric would be re-resolved on every retry, so this can never self-heal
        # and must not fail the whole sync.
        response = _response_with_status(400)
        response._content = (
            b'{"errors":[{"status":400,"code":"invalid","title":"Invalid input.",'
            b'"detail":"Passed in conversion metric does not support querying for values data",'
            b'"source":{"pointer":"/data/attributes/conversion_metric_id"}}]}'
        )

        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            if json_body is not None:
                raise requests.HTTPError(response=response)
            return {"data": [{"id": "M_FIRST", "attributes": {"name": "Viewed Product"}}], "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        assert (
            list(
                get_rows(
                    api_key="pk_test",
                    endpoint="campaign_values_reports",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
            == []
        )

    def test_unrelated_http_error_still_propagates(self, monkeypatch: Any) -> None:
        # Only the specific ineligible-conversion-metric 400 should be swallowed; any other HTTP
        # failure (e.g. a transient 500) must still fail the sync loudly rather than go silent.
        response = _response_with_status(500)
        response._content = b'{"errors":[{"status":500,"title":"Internal Server Error"}]}'

        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            if json_body is not None:
                raise requests.HTTPError(response=response)
            return {"data": [{"id": "M_FIRST", "attributes": {"name": "Viewed Product"}}], "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        with pytest.raises(requests.HTTPError):
            list(
                get_rows(
                    api_key="pk_test",
                    endpoint="campaign_values_reports",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    def test_account_with_no_metrics_yields_nothing_instead_of_posting_an_invalid_report(
        self, monkeypatch: Any
    ) -> None:
        def fake_fetch(
            session: Any, url: str, headers: dict[str, str], logger: Any, json_body: dict | None = None
        ) -> dict:
            assert json_body is None, "must not post a report without a conversion metric"
            return {"data": [], "links": {}}

        monkeypatch.setattr(klaviyo, "_fetch_page", fake_fetch)
        assert (
            list(
                get_rows(
                    api_key="pk_test",
                    endpoint="campaign_values_reports",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
            == []
        )


class TestEndpointRequestParams:
    @parameterized.expand(
        [
            # Klaviyo caps page[size] per endpoint and 400s anything larger, which fails the table.
            ("segments", 10),
            ("templates", 10),
            ("web_feeds", 20),
            ("tag_groups", 25),
            ("tags", 50),
            ("flow_actions", 50),
            ("flow_messages", 50),
            ("forms", 100),
            ("reviews", 100),
            ("images", 100),
            ("catalog_items", 100),
            ("catalog_variants", 100),
            ("catalog_categories", 100),
            ("coupons", 100),
            ("coupon_codes", 100),
            ("push_tokens", 100),
            ("data_sources", 100),
            ("segment_profiles", 100),
        ]
    )
    def test_page_size_stays_within_the_endpoint_cap(self, endpoint: str, expected: int) -> None:
        params = _build_initial_params(
            KLAVIYO_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["page[size]"] == expected

    @parameterized.expand([("custom_metrics",), ("object_types",), ("webhooks",), ("accounts",)])
    def test_unsized_endpoints_send_no_page_size(self, endpoint: str) -> None:
        # These endpoints document no page[size] param; sending one is rejected.
        params = _build_initial_params(
            KLAVIYO_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert "page[size]" not in params

    def test_reviews_use_the_inclusive_operator_klaviyo_documents(self) -> None:
        # Klaviyo only accepts greater-or-equal on the review `created` filter; greater-than 400s.
        params = _build_initial_params(
            KLAVIYO_ENDPOINTS["reviews"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created",
        )
        assert params["filter"] == "greater-or-equal(created,2026-03-04T02:58:14.000Z)"

    def test_profiles_request_the_omitted_subscriptions_object(self) -> None:
        # Klaviyo excludes subscriptions (consent detail) unless additional-fields asks for it;
        # dropping this param silently loses the column for every synced profile.
        params = _build_initial_params(
            KLAVIYO_ENDPOINTS["profiles"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated",
        )
        assert params["additional-fields[profile]"] == "subscriptions"
        assert params["filter"] == "greater-than(updated,2026-03-04T02:58:14.000Z)"

    @parameterized.expand([("list_profiles",), ("segment_profiles",)])
    def test_membership_fan_outs_keep_their_restrictive_fieldset(self, endpoint: str) -> None:
        # The fan-outs only need joined_group_at; expanding them with additional-fields would
        # balloon every per-parent request.
        params = _build_initial_params(
            KLAVIYO_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["fields[profile]"] == "joined_group_at"
        assert "additional-fields[profile]" not in params


class TestNewSchemas:
    @parameterized.expand(
        [
            ("segments", True),
            ("segment_profiles", False),
            ("flow_actions", True),
            ("flow_messages", False),
            ("campaign_values_reports", True),
            ("templates", True),
        ]
    )
    def test_expensive_fan_outs_are_opt_in(self, endpoint: str, expected_default: bool) -> None:
        # A default-on fan-out silently multiplies API cost for accounts that opted into auto-sync.
        schemas = {s.name: s for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default

    @parameterized.expand([("segment_profiles",), ("flow_actions",), ("flow_messages",)])
    def test_lookback_endpoints_are_merge_only(self, endpoint: str) -> None:
        # Append mode would materialize the intentional lookback re-pulls as duplicate rows.
        schemas = {s.name: s for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_append is False

    def test_every_endpoint_is_exposed_as_a_schema(self) -> None:
        schemas = {s.name for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas == set(KLAVIYO_ENDPOINTS)

    def test_plan_gated_webhooks_is_opt_in(self) -> None:
        # Klaviyo only offers the webhooks API with its paid Advanced KDP add-on, so a default-on
        # table would fail the first sync for every other account.
        schemas = {s.name: s for s in KlaviyoSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas["webhooks"].should_sync_default is False


class TestSourceResponseSortMode:
    @parameterized.expand(
        [
            ("list_profiles", "desc"),
            ("segment_profiles", "desc"),
            ("flow_actions", "desc"),
            ("flow_messages", "desc"),
            ("events", "asc"),
            ("segments", "asc"),
        ]
    )
    def test_source_response_sort_mode(self, endpoint: str, expected: str) -> None:
        # "desc" defers watermark persistence to successful job end; reverting the fan-out to "asc"
        # per-batch persistence lets a crashed run advance the watermark past lists it never fetched.
        response = klaviyo_source(
            api_key="pk_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected


class TestApiVersionThreadsToRevisionHeader:
    @parameterized.expand([("2024-10-15",), ("2026-07-15",)])
    def test_pinned_version_reaches_revision_header(self, api_version: str) -> None:
        # The resolved pin must reach Klaviyo's `revision` header, or a source pinned to a supported
        # revision would silently sync against whatever version the request layer hardcodes.
        captured: dict[str, str] = {}

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            captured.update(headers)
            return {"data": [], "links": {"next": None}}

        with patch.object(klaviyo, "_fetch_page", fake_fetch):
            list(
                get_rows(
                    api_key="pk_test",
                    endpoint="events",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    api_version=api_version,
                )
            )

        assert captured["revision"] == api_version


class TestVersionDeprecation:
    def test_2024_revision_deprecated_with_sunset_and_current_is_not(self) -> None:
        # The generic in-product warning keys off this metadata; the registry invariant test checks
        # the set relationships but not the specific sunset date this PR pins.
        source = KlaviyoSource()
        deprecation = source.get_version_deprecation("2024-10-15")
        assert deprecation is not None
        assert deprecation.sunset_at == date(2026, 10, 15)
        assert source.get_version_deprecation("2026-07-15") is None


class TestValidateCredentialsResolvedPin:
    @parameterized.expand(
        [
            (KLAVIYO_API_VERSION_2024_10_15, KLAVIYO_API_VERSION_2024_10_15),
            (KLAVIYO_API_VERSION_2026_07_15, KLAVIYO_API_VERSION_2026_07_15),
            # No pin (pre-creation) resolves to the default the new row is stamped with.
            (None, KLAVIYO_API_VERSION_2026_07_15),
        ]
    )
    def test_class_probe_threads_resolved_pin(self, pin: str | None, expected: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.klaviyo.source.validate_klaviyo_credentials",
            return_value=True,
        ) as mock_validate:
            KlaviyoSource().validate_credentials(KlaviyoSourceConfig(api_key="pk_test"), 1, api_version=pin)

        assert mock_validate.call_args.args[-1] == expected

    @parameterized.expand([(KLAVIYO_API_VERSION_2024_10_15,), (KLAVIYO_API_VERSION_2026_07_15,)])
    def test_probe_sends_pin_as_revision_header(self, api_version: str) -> None:
        # A 2024-10-15-pinned source must validate on the same `revision` header it syncs with.
        with patch.object(klaviyo, "make_tracked_session") as session_factory:
            response = MagicMock(status_code=200)
            session_factory.return_value.get.return_value = response
            assert klaviyo.validate_credentials("pk_test", api_version) is True

        headers = session_factory.return_value.get.call_args.kwargs["headers"]
        assert headers["revision"] == api_version
