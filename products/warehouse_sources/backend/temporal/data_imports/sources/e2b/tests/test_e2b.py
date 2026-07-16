from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.e2b import e2b
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import (
    E2BResumeConfig,
    e2b_source,
    get_rows,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: E2BResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[E2BResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> E2BResumeConfig | None:
        return self._state

    def save_state(self, data: E2BResumeConfig) -> None:
        self.saved.append(data)


def _response(items: Any, next_token: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = items
    response.headers = {"X-Next-Token": next_token} if next_token else {}
    return response


def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: list[MagicMock], endpoint: str = "sandboxes"):
    """Drive get_rows with a scripted sequence of pages, recording the nextToken each fetch sent."""
    sent_tokens: list[str | None] = []
    pages_iter = iter(pages)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> MagicMock:
        sent_tokens.append(params.get("nextToken"))
        return next(pages_iter)

    monkeypatch.setattr(e2b, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(api_key="e2b_test", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager):  # type: ignore[arg-type]
        rows.extend(table.to_pylist())
    return rows, sent_tokens


class TestPagination:
    def test_follows_next_token_header_across_pages(self, monkeypatch: Any) -> None:
        # The paginator must chase the X-Next-Token header; stopping after page one silently drops data.
        pages = [_response([{"sandboxID": "a"}, {"sandboxID": "b"}], next_token="t1"), _response([{"sandboxID": "c"}])]
        rows, sent_tokens = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}, {"sandboxID": "c"}]
        # First page requested with no cursor, second page with the header token.
        assert sent_tokens == [None, "t1"]

    def test_terminates_when_token_repeats(self, monkeypatch: Any) -> None:
        # An endpoint that echoes the same cursor instead of dropping it must not loop forever.
        pages = [_response([{"sandboxID": "a"}], next_token="same"), _response([{"sandboxID": "b"}], next_token="same")]
        rows, sent_tokens = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"sandboxID": "a"}, {"sandboxID": "b"}]
        assert sent_tokens == [None, "same"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        # A resumed run must start from the persisted cursor, not re-page from the beginning.
        manager = _FakeResumableManager(E2BResumeConfig(next_token="resume_tok"))
        pages = [_response([{"sandboxID": "x"}])]
        rows, sent_tokens = _collect(manager, monkeypatch, pages)
        assert rows == [{"sandboxID": "x"}]
        assert sent_tokens == ["resume_tok"]

    def test_non_list_response_stops_without_crashing(self, monkeypatch: Any) -> None:
        # A wrapped/error body must be tolerated rather than raising while iterating a dict.
        pages = [_response({"code": 500, "message": "boom"})]
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == []

    def test_builds_a_redacted_redirect_pinned_uncaptured_session(self, monkeypatch: Any) -> None:
        # The sync session carries the same X-API-Key header the scrubber can't see, so it must redact the
        # key and refuse redirects; `capture=False` keeps secret-bearing sandbox metadata out of sample
        # storage, which the row-level `_scrub` can't do (it only runs after capture).
        session = MagicMock()
        monkeypatch.setattr(e2b, "_fetch_page", lambda *a, **k: _response([]))
        with patch.object(e2b, "make_tracked_session", return_value=session) as make_session:
            list(
                get_rows(
                    api_key="e2b_secret",
                    endpoint="sandboxes",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert make_session.call_args.kwargs == {
            "redact_values": ("e2b_secret",),
            "allow_redirects": False,
            "capture": False,
        }

    def test_drops_sensitive_metadata_before_ingesting(self, monkeypatch: Any) -> None:
        # E2B lets users stash secrets in sandbox metadata; writing it to the table would leak them to
        # anyone with table read access, so it must be stripped before batching. Other fields survive.
        pages = [_response([{"sandboxID": "a", "metadata": {"API_KEY": "sk-secret"}, "state": "running"}])]
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"sandboxID": "a", "state": "running"}]

    def test_saves_next_page_cursor_after_yielding_a_batch(self, monkeypatch: Any) -> None:
        # Save-after-yield with the NEXT page's token is what makes resume re-yield (not skip) the last
        # batch on a crash. A full 2000-row page forces the batcher to flush mid-loop.
        manager = _FakeResumableManager()
        pages = [
            _response([{"sandboxID": str(i)} for i in range(2000)], next_token="t1"),
            _response([{"sandboxID": "last"}]),
        ]
        rows, _ = _collect(manager, monkeypatch, pages)
        assert len(rows) == 2001
        assert manager.saved == [E2BResumeConfig(next_token="t1")]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked_encoding", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, transient_error: Exception) -> None:
        good = _response([])
        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(e2b._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = e2b._fetch_page(session, "https://api.e2b.app/v2/sandboxes", {}, {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry_then_succeed(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status, ok=False, text="err")
        good = _response([])
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(e2b._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = e2b._fetch_page(session, "https://api.e2b.app/v2/sandboxes", {}, {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_code_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(e2b, "make_tracked_session", return_value=session) as make_session:
            assert validate_credentials("e2b_test") is expected
        # The key rides in the X-API-Key header, which the generic scrubber's denylist doesn't cover, so
        # the probe must redact it from tracked samples, pin redirects off to stop it replaying elsewhere,
        # and disable capture so the sandbox response body never reaches sample storage.
        assert make_session.call_args.kwargs == {
            "redact_values": ("e2b_test",),
            "allow_redirects": False,
            "capture": False,
        }

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_status_raises_rather_than_reporting_invalid(self, _name: str, status: int) -> None:
        # A rate limit or 5xx says nothing about the key; mapping it to "invalid" sends the user the wrong way.
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(e2b, "make_tracked_session", return_value=session):
            with pytest.raises(e2b.E2BRetryableError):
                validate_credentials("e2b_test")

    def test_network_error_propagates(self) -> None:
        # A connection failure is transient — it must bubble up, not be swallowed into a False "invalid key".
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError()
        with patch.object(e2b, "make_tracked_session", return_value=session):
            with pytest.raises(requests.ConnectionError):
                validate_credentials("e2b_test")


class TestSourceResponsePartitioning:
    @parameterized.expand(
        [
            ("sandboxes", ["sandboxID"], "startedAt"),
            ("templates", ["templateID"], "createdAt"),
            # Snapshots carry no timestamp — a partition key would have to be an unstable field.
            ("snapshots", ["snapshotID"], None),
        ]
    )
    def test_primary_keys_and_partitioning_per_endpoint(
        self, endpoint: str, expected_pks: list[str], expected_partition: str | None
    ) -> None:
        response = e2b_source(
            api_key="e2b_test", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


@pytest.mark.parametrize("endpoint", ["sandboxes", "templates", "snapshots"])
def test_every_endpoint_builds_a_source_response(endpoint: str) -> None:
    response = e2b_source(
        api_key="e2b_test", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
    )
    assert response.name == endpoint
    assert callable(response.items)
