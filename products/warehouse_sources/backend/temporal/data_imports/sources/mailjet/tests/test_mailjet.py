import base64
from datetime import UTC, datetime
from typing import Any

import time_machine
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailjet import (
    MailjetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet import (
    MAILJET_BASE_URL,
    WEBHOOK_PATH,
    MailjetResumeConfig,
    _authenticated_callback_url,
    _to_unix_ts,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    mailjet_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    MAILJET_ENDPOINTS,
    MAILJET_WEBHOOK_EVENTS,
    STATCOUNTERS_EARLIEST_UNIX_TS,
    STATCOUNTERS_ENDPOINT,
    WEBHOOK_TABLE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.source import MailJetSource


def _response(
    rows: list[dict[str, Any]] | None, total: int | None = None, *, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_data:
        body["Data"] = rows or []
    if total is not None:
        body["Total"] = total
    return ScriptedResponse(json=body)


def _make_manager(resume_state: MailjetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    kwargs.setdefault("webhook_source_manager", mock.MagicMock())
    return mailjet_source("key", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _driver() -> SourceDriver:
    return SourceDriver(MailJetSource(), MailjetSourceConfig(api_key="key", secret_key="secret"))


LIMIT = MAILJET_ENDPOINTS["contact"].page_size
OFFSET_PAGINATED_ENDPOINTS = [name for name in MAILJET_ENDPOINTS if name != STATCOUNTERS_ENDPOINT]


class TestToUnixTs:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), 1767225600),
            ("naive_datetime", datetime(2026, 1, 1), 1767225600),
            ("int_passthrough", 1767225600, 1767225600),
            ("none", None, None),
            ("string", "not-a-ts", None),
        ]
    )
    def test_to_unix_ts(self, _name: str, value: object, expected: int | None) -> None:
        assert _to_unix_ts(value) == expected


class TestOffsetPagination:
    def test_multi_page_advances_offset(self) -> None:
        result = _driver().run(
            "contact",
            [
                _response([{"ID": i} for i in range(LIMIT)], total=LIMIT + 2),
                _response([{"ID": i} for i in range(2)], total=LIMIT + 2),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == LIMIT + 2
        assert result.params("Offset") == ["0", str(LIMIT)]
        assert result.params("Limit") == [str(LIMIT), str(LIMIT)]

    @parameterized.expand([(name,) for name in OFFSET_PAGINATED_ENDPOINTS])
    def test_sort_param_sent(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([{"ID": 1}], total=1)])

        assert result.raised is None
        assert result.requests[0].param("Sort") == MAILJET_ENDPOINTS[endpoint].sort

    def test_campaigndraft_does_not_sort_on_created_at(self) -> None:
        # Regression guard for the Sort fallback documented in settings.py.
        assert MAILJET_ENDPOINTS["campaigndraft"].sort == "ID"


class TestResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "contact",
            [_response([{"ID": 1}], total=2000)],
            resume_state=MailjetResumeConfig(offset=1000, endpoint="contact"),
        )

        assert result.raised is None
        assert result.params("Offset")[0] == "1000"


class TestIncremental:
    def test_from_ts_applied_for_statistics_endpoint(self) -> None:
        result = _driver().run(
            "openinformation",
            [_response([{"ID": 1}], total=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("FromTS") == "1767225600"


DAY = 24 * 60 * 60
WINDOW = 90 * DAY


class TestStatcounters:
    @time_machine.travel(datetime.fromtimestamp(STATCOUNTERS_EARLIEST_UNIX_TS + WINDOW + 5 * DAY, tz=UTC), tick=False)
    def test_full_refresh_walks_non_overlapping_windows_up_to_now(self) -> None:
        result = _driver().run(
            STATCOUNTERS_ENDPOINT,
            [
                _response([{"Timeslice": "2018-04-02T00:00:00Z"}, {"Timeslice": "2018-04-01T00:00:00Z"}]),
                _response([]),
            ],
        )

        assert result.raised is None
        now = STATCOUNTERS_EARLIEST_UNIX_TS + WINDOW + 5 * DAY
        assert list(zip(result.params("FromTS"), result.params("ToTS"))) == [
            (str(STATCOUNTERS_EARLIEST_UNIX_TS), str(STATCOUNTERS_EARLIEST_UNIX_TS + WINDOW - 1)),
            (str(STATCOUNTERS_EARLIEST_UNIX_TS + WINDOW), str(now)),
        ]
        request = result.requests[-1]
        assert (
            request.param("CounterSource"),
            request.param("CounterTiming"),
            request.param("CounterResolution"),
        ) == ("APIKey", "Event", "Day")
        # sort_mode="asc" relies on rows arriving oldest first.
        assert [row["Timeslice"] for row in result.rows] == ["2018-04-01T00:00:00Z", "2018-04-02T00:00:00Z"]
        expected_states = [
            MailjetResumeConfig(endpoint=STATCOUNTERS_ENDPOINT, from_ts=STATCOUNTERS_EARLIEST_UNIX_TS + WINDOW),
            MailjetResumeConfig(endpoint=STATCOUNTERS_ENDPOINT, from_ts=STATCOUNTERS_EARLIEST_UNIX_TS + 2 * WINDOW),
        ]
        assert result.saved_states == expected_states
        # The empty window yields nothing, so it has to give the pipeline a chance to hand off.
        assert result.committed_states == expected_states

    @parameterized.expand(
        [
            ("full_refresh", False, None, None, STATCOUNTERS_EARLIEST_UNIX_TS),
            ("watermark_rereads_its_day", True, datetime(2026, 1, 1, 15, 30, tzinfo=UTC), None, 1767225600),
            ("iso_string_watermark", True, "2026-01-01T15:30:00Z", None, 1767225600),
            ("watermark_before_earliest", True, datetime(2010, 1, 1, tzinfo=UTC), None, STATCOUNTERS_EARLIEST_UNIX_TS),
            (
                "resume_wins_over_watermark",
                True,
                datetime(2026, 1, 1, tzinfo=UTC),
                MailjetResumeConfig(endpoint=STATCOUNTERS_ENDPOINT, from_ts=1767312000),
                1767312000,
            ),
            (
                "resume_of_another_endpoint_ignored",
                False,
                None,
                MailjetResumeConfig(endpoint="contact", from_ts=1767312000),
                STATCOUNTERS_EARLIEST_UNIX_TS,
            ),
        ]
    )
    @time_machine.travel("2026-01-03T00:00:00Z", tick=False)
    def test_first_window_start(
        self,
        _name: str,
        incremental: bool,
        last_value: object,
        resume: MailjetResumeConfig | None,
        expected_from_ts: int,
    ) -> None:
        result = _driver().run(
            STATCOUNTERS_ENDPOINT,
            always(_response([])),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
            resume_state=resume,
        )

        assert result.raised is None
        assert result.params("FromTS")[0] == str(expected_from_ts)


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name in MAILJET_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_response([{"ID": 1}], total=1)))
        assert result.raised is None
        response = result.response
        assert response is not None
        config = MAILJET_ENDPOINTS[endpoint]

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestRetryable:
    def test_401_does_not_retry_and_raises(self) -> None:
        result = _driver().run("contact", [ScriptedResponse(status=401, json={"ErrorMessage": "boom"})])

        assert isinstance(result.raised, Exception)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok_200", 200, True),
        ]
    )
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key", "secret") is expected

        assert network.requests_log[0].url == f"{MAILJET_BASE_URL}/contactmetadata?Limit=1"
        token = network.requests_log[0].headers["authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:secret"


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog-fn-1"


def _callback_row(event: str, url: str, row_id: int = 1, status: str = "alive") -> dict[str, Any]:
    return {"ID": row_id, "EventType": event, "Url": url, "Status": status, "Version": 1, "IsBackup": False}


class TestCreateWebhook:
    def test_partial_failure_still_persists_the_credentials(self) -> None:
        # Losing the password would leave the registrations that did land unverifiable forever.
        ok = ScriptedResponse(status=201, json={"Data": []})
        bad = ScriptedResponse(status=400, json={})
        with scripted_network([ok, bad, ok, ok, ok, ok, ok]) as network:
            result = create_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is True
        assert "authorization_header" in result.extra_inputs
        assert len(network.requests_log) == len(MAILJET_WEBHOOK_EVENTS)

    def test_total_failure_reports_an_error(self) -> None:
        with scripted_network(always(ScriptedResponse(status=403, json={}))) as network:
            result = create_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None
        assert result.extra_inputs == {}
        assert len(network.requests_log) == len(MAILJET_WEBHOOK_EVENTS)


class TestSyncWebhookEvents:
    def test_registers_only_the_missing_events_reusing_stored_credentials(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        with scripted_network(
            [
                ScriptedResponse(json={"Data": [_callback_row("open", authed)]}),
                ScriptedResponse(status=201, json={"Data": []}),
            ]
        ) as network:
            result = sync_webhook_events("key", "secret", WEBHOOK_URL, ["open", "click"])

        assert result.success is True
        posted = [request.json() for request in network.requests_log if request.method == "POST"]
        assert [body["EventType"] for body in posted] == ["click"]
        # The password only exists on the stored registration, so it has to be carried over.
        assert posted[0]["Url"] == authed

    def test_no_op_when_every_event_is_registered(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        with scripted_network(
            [
                ScriptedResponse(
                    json={
                        "Data": [
                            _callback_row(event, authed, row_id=i) for i, event in enumerate(MAILJET_WEBHOOK_EVENTS)
                        ]
                    }
                )
            ]
        ) as network:
            assert sync_webhook_events("key", "secret", WEBHOOK_URL, list(MAILJET_WEBHOOK_EVENTS)).success is True

        assert [request.method for request in network.requests_log] == ["GET"]

    def test_ignores_callback_urls_belonging_to_other_destinations(self) -> None:
        with scripted_network(
            [ScriptedResponse(json={"Data": [_callback_row("open", "https://example.com/hook")]})]
        ) as network:
            assert sync_webhook_events("key", "secret", WEBHOOK_URL, ["open"]).success is True

        assert [request.method for request in network.requests_log] == ["GET"]

    def test_api_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            result = sync_webhook_events("key", "secret", WEBHOOK_URL, ["open"])

        assert result.success is False
        assert result.error is not None


class TestExternalWebhookInfo:
    def test_reports_registered_events_without_leaking_the_password(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        with scripted_network(
            [ScriptedResponse(json={"Data": [_callback_row("open", authed, 1), _callback_row("click", authed, 2)]})]
        ):
            info = get_external_webhook_info("key", "secret", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["click", "open"]
        assert info.url == WEBHOOK_URL
        assert "stored-password" not in (info.url or "")

    def test_asks_for_more_than_mailjets_default_page(self) -> None:
        # Mailjet returns 10 callback URLs by default. An account with its own callbacks would
        # push ours off that page and every match would come back empty.
        with scripted_network([ScriptedResponse(json={"Data": []})]) as network:
            get_external_webhook_info("key", "secret", WEBHOOK_URL)

        assert int(network.requests_log[0].param("Limit") or "0") > 10


class TestDeleteWebhook:
    def test_deletes_only_our_callback_urls(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        with scripted_network(
            [
                ScriptedResponse(
                    json={
                        "Data": [
                            _callback_row("open", authed, 1),
                            _callback_row("click", "https://example.com/hook", 2),
                        ]
                    }
                ),
                ScriptedResponse(status=200, json={}),
            ]
        ) as network:
            result = delete_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is True
        deleted = [request.url for request in network.requests_log if request.method == "DELETE"]
        assert deleted == [f"{MAILJET_BASE_URL}{WEBHOOK_PATH}/1"]

    def test_reports_a_refused_delete(self) -> None:
        authed = _authenticated_callback_url(WEBHOOK_URL, "stored-password")
        with scripted_network(
            [
                ScriptedResponse(json={"Data": [_callback_row("open", authed, 1)]}),
                ScriptedResponse(status=403, json={}),
            ]
        ):
            result = delete_webhook("key", "secret", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None


class TestWebhookTableTransformer:
    def test_rows_without_an_event_id_are_kept(self) -> None:
        import pyarrow as pa

        table = pa.Table.from_pylist([{"event_id": None, "event": "open"}, {"event_id": "a", "event": "click"}])

        assert len(_webhook_table_transformer(table).to_pylist()) == 2


class TestWebhookOnlySource:
    def _manager(self, enabled: bool) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
        return manager

    def test_reads_webhook_rows_with_the_dedupe_transformer(self) -> None:
        manager = self._manager(enabled=True)

        response = _source(WEBHOOK_TABLE_NAME, _make_manager(), webhook_source_manager=manager)
        response.items()

        assert response.name == WEBHOOK_TABLE_NAME
        assert response.primary_keys == ["event_id"]
        # Marks the poll as backfill-free, so a reset resumes ingestion rather than wiping rows
        # that no poll could rebuild.
        assert response.webhook_only is True
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=True)
        assert manager.get_items.call_args.kwargs["table_transformer"] is _webhook_table_transformer

    def test_yields_nothing_until_the_webhook_is_registered(self) -> None:
        manager = self._manager(enabled=False)

        response = _source(WEBHOOK_TABLE_NAME, _make_manager(), webhook_source_manager=manager)

        assert list(response.items()) == []
        manager.get_items.assert_not_called()
