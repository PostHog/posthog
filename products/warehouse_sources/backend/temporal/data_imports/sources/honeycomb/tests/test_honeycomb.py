import json
from collections.abc import Mapping
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb import honeycomb
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.honeycomb import (
    HoneycombResumeConfig,
    HoneycombRetryableError,
    _base_url,
    _get_headers,
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
    def test_get_headers_sets_team_header(self) -> None:
        assert _get_headers("hcaik_123")["X-Honeycomb-Team"] == "hcaik_123"

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


class TestEnvironmentEndpoints:
    def test_single_fetch_yields_all_rows(self, monkeypatch: Any) -> None:
        lists = {f"{US}/1/boards": [{"id": "b1"}, {"id": "b2"}]}
        rows = _collect("boards", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": "b1"}, {"id": "b2"}]

    def test_eu_region_routes_to_eu_host(self, monkeypatch: Any) -> None:
        lists = {"https://api.eu1.honeycomb.io/1/boards": [{"id": "b1"}]}
        rows = _collect("boards", lists, _FakeResumableManager(), monkeypatch, region="eu")
        assert rows == [{"id": "b1"}]


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

    def test_deleted_dataset_404_is_skipped(self, monkeypatch: Any) -> None:
        # A dataset deleted between enumeration and its fetch must not fail the whole sync.
        lists: dict[str, Any] = {
            f"{US}/1/datasets": [{"slug": "gone"}, {"slug": "prod"}],
            f"{US}/1/columns/gone": _not_found(f"{US}/1/columns/gone"),
            f"{US}/1/columns/prod": [{"id": "c1"}],
        }
        rows = _collect("columns", lists, _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": "c1", "dataset_slug": "prod"}]

    def test_state_saved_after_each_yielded_dataset(self, monkeypatch: Any) -> None:
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}, {"slug": "empty"}, {"slug": "staging"}],
            f"{US}/1/columns/prod": [{"id": "c1"}],
            f"{US}/1/columns/empty": [],
            f"{US}/1/columns/staging": [{"id": "c2"}],
        }
        manager = _FakeResumableManager()
        _collect("columns", lists, manager, monkeypatch)
        # Empty datasets yield nothing so no checkpoint is written for them — a checkpoint must
        # only ever point at a dataset whose rows were actually handed to the pipeline.
        assert [state.dataset_slug for state in manager.saved] == ["prod", "staging"]

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

    def test_resume_from_deleted_dataset_restarts_from_first(self, monkeypatch: Any) -> None:
        lists = {
            f"{US}/1/datasets": [{"slug": "prod"}],
            f"{US}/1/columns/prod": [{"id": "c1"}],
        }
        manager = _FakeResumableManager(HoneycombResumeConfig(dataset_slug="GONE"))
        rows = _collect("columns", lists, manager, monkeypatch)
        assert rows == [{"id": "c1", "dataset_slug": "prod"}]


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

    def test_probes_the_selected_regions_auth_endpoint(self) -> None:
        # A key validated against the wrong region always 401s, so the probe must follow the
        # user's region selection rather than defaulting to US.
        session = _FakeSession([_make_response(200, body={})])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(honeycomb, "make_tracked_session", lambda *args, **kwargs: session)
            validate_credentials("key", "eu")
        assert session.requested_urls == ["https://api.eu1.honeycomb.io/1/auth"]

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
