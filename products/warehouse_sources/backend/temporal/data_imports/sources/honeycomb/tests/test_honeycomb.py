import json
from collections.abc import Mapping
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb import honeycomb
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.honeycomb import (
    HoneycombResumeConfig,
    HoneycombRetryableError,
    HoneycombSloCountsUnavailableError,
    _base_url,
    get_rows,
    validate_credentials,
)

US = "https://api.honeycomb.io"


class _FakeResumableManager:
    def __init__(self, state: HoneycombResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HoneycombResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HoneycombResumeConfig | None:
        return self._state

    def save_state(self, data: HoneycombResumeConfig) -> None:
        self.saved.append(data)


def _make_response(status_code: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if body is not None:
        response._content = json.dumps(body).encode()
    return response


class _FakeSession:
    """Returns queued responses in order, recording the URLs requested."""

    def __init__(self, responses: list[requests.Response]) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> requests.Response:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _not_found(url: str) -> requests.HTTPError:
    return requests.HTTPError(f"404 Client Error: Not Found for url: {url}", response=_make_response(404))


def _collect(
    endpoint: str,
    lists: Mapping[str, list[dict[str, Any]] | Exception],
    manager: _FakeResumableManager,
    monkeypatch: Any,
    region: str = "us",
) -> list[dict]:
    monkeypatch.setattr(honeycomb, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    def fake_fetch_list(session: Any, url: str, headers: Any, logger: Any) -> list[dict]:
        if url not in lists:
            raise AssertionError(f"unexpected URL requested: {url}")
        result = lists[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(honeycomb, "_fetch_list", fake_fetch_list)

    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        region=region,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(batch)
    return rows


class TestHelpers:
    @parameterized.expand([("us", US), ("eu", "https://api.eu1.honeycomb.io"), ("unknown", US)])
    def test_base_url_per_region(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = _FakeSession([_make_response(status_code) for _ in range(5)])
        # tenacity exposes retry_with on the decorated callable to rebuild it with different
        # retry settings; here we drop the backoff so the test doesn't actually sleep.
        fast_fetch = honeycomb._fetch_page.retry_with(wait=wait_none(), stop=stop_after_attempt(3))  # type: ignore[attr-defined]
        with pytest.raises(HoneycombRetryableError):
            fast_fetch(session, f"{US}/1/datasets", {}, MagicMock())

    def test_client_error_raises_http_error_without_retry(self) -> None:
        session = _FakeSession([_make_response(401, body={"error": "unknown API key"})])
        with pytest.raises(requests.HTTPError):
            honeycomb._fetch_page(session, f"{US}/1/datasets", {}, MagicMock())  # type: ignore[arg-type]
        assert len(session.requested_urls) == 1

    def test_fetch_list_treats_non_array_body_as_empty(self) -> None:
        session = _FakeSession([_make_response(200, body={"unexpected": "shape"})])
        assert honeycomb._fetch_list(session, f"{US}/1/datasets", {}, MagicMock()) == []  # type: ignore[arg-type]


class TestPerDatasetFanOut:
    def test_walks_datasets_and_injects_dataset_slug(self, monkeypatch: Any) -> None:
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "staging"}],
            f"{US}/1/columns/prod": [{"id": "c1"}],
            f"{US}/1/columns/staging": [{"id": "c1"}, {"id": "c2"}],
        }
        rows = _collect("columns", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "c1", "dataset_slug": "prod"},
            {"id": "c1", "dataset_slug": "staging"},
            {"id": "c2", "dataset_slug": "staging"},
        ]

    @parameterized.expand([("markers",), ("derived_columns",)])
    def test_environment_wide_pseudo_dataset_included(self, endpoint: str) -> None:
        # Environment-scoped markers/derived columns only exist under __all__; skipping it would
        # silently drop e.g. every environment-wide deploy marker from the table.
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}],
            f"{US}/1/{endpoint}/prod": [{"id": "r1"}],
            f"{US}/1/{endpoint}/__all__": [{"id": "r2"}],
        }
        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        with pytest.MonkeyPatch.context() as mp:
            rows = _collect(endpoint, lists, _FakeResumableManager(), mp)
        assert rows == [
            {"id": "r1", "dataset_slug": "prod"},
            {"id": "r2", "dataset_slug": "__all__"},
        ]

    def test_resume_refetches_bookmarked_dataset_and_skips_earlier(self, monkeypatch: Any) -> None:
        # The bookmarked dataset's rows may not have been durably flushed before the crash, so it
        # is re-fetched in full (merge dedupes); datasets before it must not be re-fetched (their
        # URLs are absent from `lists`, so a fetch would raise).
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "staging"}, {"slug": "dev"}],
            f"{US}/1/columns/staging": [{"id": "c2"}],
            f"{US}/1/columns/dev": [{"id": "c3"}],
        }
        manager = _FakeResumableManager(HoneycombResumeConfig(dataset_slug="staging"))
        rows = _collect("columns", lists, manager, monkeypatch)
        assert rows == [
            {"id": "c2", "dataset_slug": "staging"},
            {"id": "c3", "dataset_slug": "dev"},
        ]


class TestBurnAlertFanOut:
    def test_walks_datasets_then_slos_and_injects_both_ids(self, monkeypatch: Any) -> None:
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}],
            f"{US}/1/slos/prod": [{"id": "slo1"}, {"id": "slo2"}],
            f"{US}/1/burn_alerts/prod?slo_id=slo1": [{"id": "ba1"}],
            f"{US}/1/burn_alerts/prod?slo_id=slo2": [{"id": "ba2"}],
        }
        rows = _collect("burn_alerts", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "ba1", "dataset_slug": "prod", "slo_id": "slo1"},
            {"id": "ba2", "dataset_slug": "prod", "slo_id": "slo2"},
        ]

    def test_dataset_without_slos_yields_nothing(self, monkeypatch: Any) -> None:
        lists: dict[str, Any] = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "quiet"}],
            f"{US}/1/slos/prod": [{"id": "slo1"}],
            f"{US}/1/burn_alerts/prod?slo_id=slo1": [{"id": "ba1"}],
            f"{US}/1/slos/quiet": [],
        }
        rows = _collect("burn_alerts", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": "ba1", "dataset_slug": "prod", "slo_id": "slo1"}]


class TestBoardViewFanOut:
    def test_walks_boards_injects_board_id_and_skips_deleted_board(self, monkeypatch: Any) -> None:
        lists: dict[str, Any] = {
            f"{US}/1/boards": [{"id": "b1"}, {"id": "gone"}, {"id": "b2"}],
            f"{US}/1/boards/b1/views": [{"id": "v1", "name": "Errors"}],
            f"{US}/1/boards/gone/views": _not_found(f"{US}/1/boards/gone/views"),
            f"{US}/1/boards/b2/views": [{"id": "v1", "name": "Slow"}],
        }
        manager = _FakeResumableManager()
        rows = _collect("board_views", lists, manager, monkeypatch)
        assert rows == [
            {"id": "v1", "name": "Errors", "board_id": "b1"},
            {"id": "v1", "name": "Slow", "board_id": "b2"},
        ]
        assert [state.board_id for state in manager.saved] == ["b1", "b2"]

    def test_resume_refetches_bookmarked_board_and_skips_earlier(self, monkeypatch: Any) -> None:
        lists = {
            f"{US}/1/boards": [{"id": "b1"}, {"id": "b2"}],
            f"{US}/1/boards/b2/views": [{"id": "v2"}],
        }
        manager = _FakeResumableManager(HoneycombResumeConfig(board_id="b2"))
        rows = _collect("board_views", lists, manager, monkeypatch)
        assert rows == [{"id": "v2", "board_id": "b2"}]


class _UrlSession:
    """Serves canned JSON bodies (or a status code) per URL, recording the URLs requested."""

    def __init__(self, responses: Mapping[str, Any]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> requests.Response:
        self.requested_urls.append(url)
        if url not in self._responses:
            raise AssertionError(f"unexpected URL requested: {url}")
        result = self._responses[url]
        if isinstance(result, int):
            return _make_response(result, body={"error": "not found"})
        return _make_response(200, body=result)


# 2026-01-15T12:30:00Z — mid-hour, so the hour alignment of the window start is exercised.
NOW = 1768480200
HOUR = 3600
DAY = 24 * HOUR


def _bucket(start: int, **extra: Any) -> dict[str, Any]:
    return {"start_time": start, "end_time": start + HOUR, "total_count": 10, "error_count": 1, **extra}


def _collect_counts_history(
    responses: Mapping[str, Any], last_value: Any, monkeypatch: Any
) -> tuple[list[list[dict]], _UrlSession]:
    session = _UrlSession(responses)
    monkeypatch.setattr(honeycomb, "make_tracked_session", lambda *args, **kwargs: session)
    with time_machine.travel(NOW, tick=False):
        batches = list(
            get_rows(
                api_key="key",
                region="us",
                endpoint="slo_counts_history",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                db_incremental_field_last_value=last_value,
            )
        )
    return batches, session


def _history_url(dataset_slug: str, slo_id: str, start: int, end: int) -> str:
    return f"{US}/1/slos/{dataset_slug}/{slo_id}/counts/history?start_time={start}&end_time={end}"


class TestSloCountsHistory:
    @parameterized.expand(
        [
            ("no_watermark", None),
            # A watermark from a non-epoch column must not walk back to 1970.
            ("watermark_older_than_lookback", 84513),
        ]
    )
    def test_walks_lookback_in_weekly_windows_across_every_slo(self, _name: str, last_value: Any) -> None:
        aligned_now = NOW - NOW % HOUR
        first_start = aligned_now - 90 * DAY
        window_starts = list(range(first_start, NOW, 7 * DAY))
        responses: dict[str, Any] = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "gone"}],
            f"{US}/1/slos/prod": [{"id": "slo1"}, {"id": "slo2"}],
            f"{US}/1/slos/gone": 404,
        }
        for start in window_starts:
            end = min(start + 7 * DAY, NOW)
            responses[_history_url("prod", "slo1", start, end)] = {"slo_id": "slo1", "buckets": [_bucket(start)]}
            # A deleted SLO 404s; that must drop its rows, not fail the sync.
            responses[_history_url("prod", "slo2", start, end)] = 404

        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        with pytest.MonkeyPatch.context() as mp:
            batches, session = _collect_counts_history(responses, last_value, mp)

        assert len(batches) == len(window_starts)
        assert batches[0] == [{**_bucket(first_start), "dataset_slug": "prod", "slo_id": "slo1"}]
        # Every window is requested, and the last one ends at "now" rather than in the future.
        assert session.requested_urls[-1] == _history_url("prod", "slo2", window_starts[-1], NOW)

    @parameterized.expand(
        [
            ("int_epoch", NOW - 2 * HOUR - 600),
            ("iso_string", "2026-01-15T10:20:00+00:00"),
        ]
    )
    def test_incremental_rereads_watermark_hour_and_batches_all_slos_per_window(
        self, _name: str, last_value: Any
    ) -> None:
        watermark_hour = NOW - NOW % HOUR - 2 * HOUR
        responses: dict[str, Any] = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "api"}],
            f"{US}/1/slos/prod": [{"id": "slo1"}],
            f"{US}/1/slos/api": [{"id": "slo2"}],
            _history_url("prod", "slo1", watermark_hour, NOW): {
                "buckets": [_bucket(watermark_hour), _bucket(watermark_hour + HOUR, is_partial=True)]
            },
            _history_url("api", "slo2", watermark_hour, NOW): {"buckets": [_bucket(watermark_hour)]},
        }
        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        with pytest.MonkeyPatch.context() as mp:
            batches, _ = _collect_counts_history(responses, last_value, mp)

        # One batch per window holding every SLO, so the batch max start_time never regresses
        # and the ascending watermark can be checkpointed after each batch.
        assert batches == [
            [
                {**_bucket(watermark_hour), "dataset_slug": "prod", "slo_id": "slo1"},
                {**_bucket(watermark_hour + HOUR, is_partial=True), "dataset_slug": "prod", "slo_id": "slo1"},
                {**_bucket(watermark_hour), "dataset_slug": "api", "slo_id": "slo2"},
            ]
        ]

    def test_every_slo_404ing_fails_instead_of_syncing_empty(self, monkeypatch: Any) -> None:
        watermark_hour = NOW - NOW % HOUR
        responses: dict[str, Any] = {
            f"{US}/1/datasets": [{"slug": "prod"}],
            f"{US}/1/slos/prod": [{"id": "slo1"}, {"id": "slo2"}],
            _history_url("prod", "slo1", watermark_hour, NOW): 404,
            _history_url("prod", "slo2", watermark_hour, NOW): 404,
        }
        with pytest.raises(HoneycombSloCountsUnavailableError):
            _collect_counts_history(responses, watermark_hour, monkeypatch)


class TestRecipientCredentialScrubbing:
    """Recipient payloads carry live credentials (PagerDuty integration keys, webhook signing
    secrets, webhook / MS Teams capability URLs). Dropping the sanitization would hand those to
    anyone with warehouse query access, so lock in the redaction behavior."""

    def test_recipient_details_are_allow_listed(self, monkeypatch: Any) -> None:
        lists: dict[str, list[dict[str, Any]]] = {
            f"{US}/1/recipients": [
                {"id": "r1", "type": "email", "details": {"email_address": "oncall@example.com"}},
                {
                    "id": "r2",
                    "type": "webhook",
                    "details": {"webhook_name": "hook", "webhook_url": "https://h.example", "webhook_secret": "shh"},
                },
                {
                    "id": "r3",
                    "type": "pagerduty",
                    "details": {"pagerduty_integration_name": "svc", "pagerduty_integration_key": "pd-key"},
                },
                # Unknown detail keys (new recipient types) must fail closed.
                {"id": "r4", "type": "msteams", "details": {"msteams_url": "https://teams.example/abc"}},
            ]
        }
        rows = _collect("recipients", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "r1", "type": "email", "details": {"email_address": "oncall@example.com"}},
            {
                "id": "r2",
                "type": "webhook",
                "details": {"webhook_name": "hook", "webhook_url": "[REDACTED]", "webhook_secret": "[REDACTED]"},
            },
            {
                "id": "r3",
                "type": "pagerduty",
                "details": {"pagerduty_integration_name": "svc", "pagerduty_integration_key": "[REDACTED]"},
            },
            {"id": "r4", "type": "msteams", "details": {"msteams_url": "[REDACTED]"}},
        ]

    def test_embedded_trigger_recipients_redact_credential_targets(self, monkeypatch: Any) -> None:
        # Triggers (and burn alerts) embed abbreviated recipients whose `target` holds the same
        # credentials for non-address types; only email/slack targets are plain addresses.
        lists: dict[str, list[dict[str, Any]]] = {
            f"{US}/1/datasets": [{"slug": "prod"}],
            f"{US}/1/triggers/prod": [
                {
                    "id": "t1",
                    "name": "High latency",
                    "recipients": [
                        {"id": "r1", "type": "email", "target": "oncall@example.com"},
                        {"id": "r2", "type": "pagerduty", "target": "pd-integration-key"},
                    ],
                }
            ],
        }
        rows = _collect("triggers", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {
                "id": "t1",
                "name": "High latency",
                "recipients": [
                    {"id": "r1", "type": "email", "target": "oncall@example.com"},
                    {"id": "r2", "type": "pagerduty", "target": "[REDACTED]"},
                ],
                "dataset_slug": "prod",
            }
        ]

    @parameterized.expand(
        [
            ("recipients", False),
            ("triggers", False),
            ("burn_alerts", False),
            ("boards", True),
            ("columns", True),
        ]
    )
    def test_credential_payload_endpoints_excluded_from_sample_capture(self, endpoint: str, expected: bool) -> None:
        # Raw responses for these endpoints contain unsanitized credentials, so they must not be
        # persisted by HTTP sample capture (the name-based scrubbers can't recognise them).
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        # parameterized.expand can't also receive the `monkeypatch` fixture, so manage our own.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(honeycomb, "make_tracked_session", fake_make_session)
            mp.setattr(honeycomb, "_fetch_list", lambda *args, **kwargs: [])
            list(
                get_rows(
                    api_key="key",
                    region="us",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert captured.get("capture") is expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        session = _FakeSession([_make_response(status_code, body={})])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(honeycomb, "make_tracked_session", lambda *args, **kwargs: session)
            ok, _error = validate_credentials("key", "us")
        assert ok is expected_ok

    def test_request_exception_is_failure(self, monkeypatch: Any) -> None:
        class _BoomSession:
            def get(self, *args: Any, **kwargs: Any) -> requests.Response:
                raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(honeycomb, "make_tracked_session", lambda *args, **kwargs: _BoomSession())
        ok, error = validate_credentials("key", "us")
        assert ok is False
        assert error is not None


class TestApiKeyRedaction:
    """The key rides in the X-Honeycomb-Team header, which the tracked transport's scrubber
    doesn't recognise, so every session must redact the key by value."""

    def test_validate_credentials_redacts_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeSession([_make_response(200, body={})])

        monkeypatch.setattr(honeycomb, "make_tracked_session", fake_make_session)
        validate_credentials("super-secret-key", "us")
        assert captured.get("redact_values") == ("super-secret-key",)

    def test_get_rows_redacts_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(honeycomb, "make_tracked_session", fake_make_session)
        monkeypatch.setattr(honeycomb, "_fetch_list", lambda *args, **kwargs: [])
        list(
            get_rows(
                api_key="super-secret-key",
                region="us",
                endpoint="boards",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert captured.get("redact_values") == ("super-secret-key",)
