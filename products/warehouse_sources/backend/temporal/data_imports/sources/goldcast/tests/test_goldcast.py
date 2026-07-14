from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast import goldcast
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.goldcast import (
    GoldcastRetryableError,
    _extract_rows,
    get_rows,
    goldcast_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import GOLDCAST_ENDPOINTS


class TestExtractRows:
    @parameterized.expand(
        [
            ("bare_list", [{"id": "a"}, {"id": "b"}], [{"id": "a"}, {"id": "b"}]),
            # The organization endpoint returns a single object, not a collection.
            ("single_object", {"id": "org1"}, [{"id": "org1"}]),
            # Defensive: unwrap a results/data envelope if a deployment ever wraps collections.
            ("results_envelope", {"results": [{"id": "a"}]}, [{"id": "a"}]),
            ("data_envelope", {"data": [{"id": "a"}]}, [{"id": "a"}]),
            # Non-dict entries (e.g. stray ids) are dropped so downstream row handling stays safe.
            ("filters_non_dicts", [{"id": "a"}, "junk", 5], [{"id": "a"}]),
            ("empty_list", [], []),
            ("unexpected_scalar", "nope", []),
        ]
    )
    def test_normalizes_response_shapes(self, _name: str, payload: Any, expected: list[dict]) -> None:
        assert _extract_rows(payload) == expected


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        # A 429/5xx must retry rather than fail the whole sync.
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = [{"id": "a"}]

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(goldcast._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = goldcast._fetch(session, "https://customapi.goldcast.io/event/", {}, MagicMock())

        assert result == [{"id": "a"}]
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_network_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = []

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(goldcast._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = goldcast._fetch(session, "https://customapi.goldcast.io/event/", {}, MagicMock())

        assert result == []
        assert session.get.call_count == 2

    def test_client_error_raises_and_is_not_retried(self) -> None:
        # A 401/403 is a credential problem; it must raise immediately, not burn retries.
        resp = MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)

        session = MagicMock()
        session.get.return_value = resp

        with patch.object(goldcast._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.HTTPError):
                goldcast._fetch(session, "https://customapi.goldcast.io/event/", {}, MagicMock())

        assert session.get.call_count == 1

    def test_error_body_is_not_logged_verbatim(self) -> None:
        # Goldcast error bodies can echo customer tenant records, so a full body must never land
        # in our logs — only a tightly capped excerpt is allowed.
        sensitive_body = "SECRET-TENANT-RECORD-" + "x" * 5000
        resp = MagicMock()
        resp.status_code = 400
        resp.ok = False
        resp.text = sensitive_body
        resp.raise_for_status.side_effect = requests.HTTPError("400 Client Error", response=resp)

        session = MagicMock()
        session.get.return_value = resp
        logger = MagicMock()

        with pytest.raises(requests.HTTPError):
            goldcast._fetch(session, "https://customapi.goldcast.io/event/", {}, logger)

        logged = " ".join(str(call.args[0]) for call in logger.error.call_args_list)
        assert sensitive_body not in logged
        assert len(logged) < 500

    def test_retryable_error_reraised_after_exhausting_attempts(self) -> None:
        bad = MagicMock()
        bad.status_code = 500
        session = MagicMock()
        session.get.return_value = bad

        with patch.object(goldcast._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(GoldcastRetryableError):
                goldcast._fetch(session, "https://customapi.goldcast.io/event/", {}, MagicMock())

        assert session.get.call_count == 5


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> None:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(goldcast, "_fetch", fake_fetch)
    monkeypatch.setattr(goldcast, "make_tracked_session", lambda *a, **k: MagicMock())


class TestGetRowsTopLevel:
    def test_yields_all_rows_from_a_collection_endpoint(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, {"https://customapi.goldcast.io/event/": [{"id": "e1"}, {"id": "e2"}]})

        batches = list(get_rows(access_key="tok", endpoint="events", logger=MagicMock()))

        assert batches == [[{"id": "e1"}, {"id": "e2"}]]

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, {"https://customapi.goldcast.io/event/": []})

        assert list(get_rows(access_key="tok", endpoint="events", logger=MagicMock())) == []


class TestGetRowsFanOut:
    def test_stamps_parent_event_id_onto_each_child_row(self, monkeypatch: Any) -> None:
        # The parent event id must be injected so the composite ["event", "id"] key is unique
        # table-wide — webinar rows carry no `event` field of their own.
        _patch_fetch(
            monkeypatch,
            {
                "https://customapi.goldcast.io/event/": [{"id": "e1"}, {"id": "e2"}],
                "https://customapi.goldcast.io/event/webinars/e1/": [{"id": "w1"}],
                "https://customapi.goldcast.io/event/webinars/e2/": [{"id": "w2"}, {"id": "w3"}],
            },
        )

        rows = [row for batch in get_rows(access_key="tok", endpoint="webinars", logger=MagicMock()) for row in batch]

        assert rows == [
            {"id": "w1", "event": "e1"},
            {"id": "w2", "event": "e2"},
            {"id": "w3", "event": "e2"},
        ]

    def test_event_members_query_param_path_and_stamping(self, monkeypatch: Any) -> None:
        _patch_fetch(
            monkeypatch,
            {
                "https://customapi.goldcast.io/event/": [{"id": "e1"}],
                # event_members already carries `event`; stamping re-affirms it to the parent id.
                "https://customapi.goldcast.io/event/event-members/?event=e1": [{"id": "m1", "event": "stale"}],
            },
        )

        rows = [
            row for batch in get_rows(access_key="tok", endpoint="event_members", logger=MagicMock()) for row in batch
        ]

        assert rows == [{"id": "m1", "event": "e1"}]

    def test_child_404_for_one_event_is_skipped_not_fatal(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError("404 Client Error", response=MagicMock(status_code=404))
        _patch_fetch(
            monkeypatch,
            {
                "https://customapi.goldcast.io/event/": [{"id": "e1"}, {"id": "e2"}],
                "https://customapi.goldcast.io/event/webinars/e1/": not_found,
                "https://customapi.goldcast.io/event/webinars/e2/": [{"id": "w2"}],
            },
        )

        rows = [row for batch in get_rows(access_key="tok", endpoint="webinars", logger=MagicMock()) for row in batch]

        assert rows == [{"id": "w2", "event": "e2"}]

    def test_child_non_404_error_propagates(self, monkeypatch: Any) -> None:
        # 5xx/429 are retried inside _fetch and surface as GoldcastRetryableError, so the case that
        # actually reaches the fan-out's `except HTTPError` branch is a non-404 4xx (e.g. a 403).
        forbidden = requests.HTTPError("403 Client Error", response=MagicMock(status_code=403))
        _patch_fetch(
            monkeypatch,
            {
                "https://customapi.goldcast.io/event/": [{"id": "e1"}],
                "https://customapi.goldcast.io/event/webinars/e1/": forbidden,
            },
        )

        with pytest.raises(requests.HTTPError):
            list(get_rows(access_key="tok", endpoint="webinars", logger=MagicMock()))

    def test_event_missing_id_key_fails_loudly(self, monkeypatch: Any) -> None:
        # A malformed parent event (missing the required `id` fan-out key) must raise rather than
        # silently under-sync that event's children with no signal.
        _patch_fetch(
            monkeypatch,
            {"https://customapi.goldcast.io/event/": [{"name": "no id"}]},
        )

        with pytest.raises(KeyError):
            list(get_rows(access_key="tok", endpoint="webinars", logger=MagicMock()))

    @parameterized.expand([("empty_string", ""), ("none", None), ("zero", 0)])
    def test_event_with_falsy_id_fails_loudly(self, _name: str, falsy_id: Any) -> None:
        # A falsy `id` (empty string, None, 0) must raise too — silently skipping it would
        # under-sync that event's children exactly like a missing key would.
        with pytest.MonkeyPatch.context() as monkeypatch:
            _patch_fetch(
                monkeypatch,
                {"https://customapi.goldcast.io/event/": [{"id": falsy_id}]},
            )

            with pytest.raises(ValueError):
                list(get_rows(access_key="tok", endpoint="webinars", logger=MagicMock()))


class TestGoldcastSourceResponse:
    @parameterized.expand(
        [
            ("events", ["id"], "created_at"),
            ("organizations", ["id"], "created_at"),
            # agenda_items has no creation timestamp, so it must not be partitioned.
            ("agenda_items", ["id"], None),
            # Fan-out children carry the parent id in a composite key for table-wide uniqueness.
            ("webinars", ["event", "id"], "created_at"),
            ("event_members", ["event", "id"], "created_at"),
        ]
    )
    def test_partition_and_primary_keys_per_endpoint(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        response = goldcast_source(access_key="tok", endpoint=endpoint, logger=MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_every_endpoint_declares_a_primary_key(self) -> None:
        # A non-unique / missing key seeds duplicate rows that make every later merge multi-match.
        for name, config in GOLDCAST_ENDPOINTS.items():
            assert config.primary_keys, f"{name} has no primary key"


class TestValidateCredentials:
    def test_valid_token_returns_true(self) -> None:
        session = MagicMock()
        session.get.return_value.status_code = 200
        with patch.object(goldcast, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is True

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_non_200_returns_false(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value.status_code = status_code
        with patch.object(goldcast, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is False

    def test_network_error_returns_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(goldcast, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is False


class TestTokenRedaction:
    # The token rides in a non-standard `Token` auth header the name-based scrubbers can't
    # recognise, so every tracked session must register it with `redact_values` or it leaks
    # into captured HTTP samples.
    def test_get_rows_registers_token_for_redaction(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def spy_session(*_a: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(goldcast, "make_tracked_session", spy_session)
        monkeypatch.setattr(goldcast, "_fetch", lambda *_a, **_k: [])

        list(get_rows(access_key="super-secret", endpoint="events", logger=MagicMock()))

        assert captured.get("redact_values") == ("super-secret",)

    def test_validate_credentials_registers_token_for_redaction(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def spy_session(*_a: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            session = MagicMock()
            session.get.return_value.status_code = 200
            return session

        monkeypatch.setattr(goldcast, "make_tracked_session", spy_session)

        validate_credentials("super-secret")

        assert captured.get("redact_values") == ("super-secret",)
