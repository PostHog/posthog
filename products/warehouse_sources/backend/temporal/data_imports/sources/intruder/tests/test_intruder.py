from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder import intruder
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder import (
    IntruderResumeConfig,
    get_rows,
    intruder_source,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: IntruderResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[IntruderResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> IntruderResumeConfig | None:
        return self._state

    def save_state(self, data: IntruderResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    endpoint: str,
    pages: dict[str, Any],
) -> list[dict]:
    """Run get_rows against a fake page map (url -> response body or Exception)."""

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(intruder, "_fetch_page", fake_fetch)
    monkeypatch.setattr(intruder, "make_tracked_session", lambda *a, **k: MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        access_token="token",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=cast(ResumableSourceManager[IntruderResumeConfig], manager),
    ):
        rows.extend(batch)
    return rows


class TestStandardPagination:
    def test_follows_next_url_until_exhausted(self, monkeypatch: Any) -> None:
        # A bug that dropped the `next` follow (or read the wrong key) would only return page one.
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/targets/?limit=100": {
                "results": [{"id": 1}, {"id": 2}],
                "next": "https://api.intruder.io/v1/targets/?limit=100&offset=100",
            },
            "https://api.intruder.io/v1/targets/?limit=100&offset=100": {
                "results": [{"id": 3}],
                "next": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "targets", pages)
        assert [r["id"] for r in rows] == [1, 2, 3]

    def test_empty_first_page_terminates(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {"https://api.intruder.io/v1/scans/?limit=100": {"results": [], "next": None}}
        rows = _collect(_FakeResumableManager(), monkeypatch, "scans", pages)
        assert rows == []

    def test_saves_state_after_each_page_but_not_after_last(self, monkeypatch: Any) -> None:
        # State must be saved AFTER yielding a page and only when more pages remain, so a crash
        # re-yields the last page (merge dedupes) rather than skipping it. Saving the final page's
        # (absent) cursor would be wrong.
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/targets/?limit=100": {
                "results": [{"id": 1}],
                "next": "https://api.intruder.io/v1/targets/?limit=100&offset=100",
            },
            "https://api.intruder.io/v1/targets/?limit=100&offset=100": {"results": [{"id": 2}], "next": None},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "targets", pages)
        assert [s.next_url for s in manager.saved] == ["https://api.intruder.io/v1/targets/?limit=100&offset=100"]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        # With saved state the first request must be the saved cursor, not the initial page.
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/targets/?limit=100&offset=100": {"results": [{"id": 2}], "next": None},
        }
        manager = _FakeResumableManager(
            IntruderResumeConfig(next_url="https://api.intruder.io/v1/targets/?limit=100&offset=100")
        )
        rows = _collect(manager, monkeypatch, "targets", pages)
        assert [r["id"] for r in rows] == [2]


class TestOccurrencesFanOut:
    @staticmethod
    def _issue_page(ids: list[int], next_url: str | None) -> dict:
        return {"results": [{"id": i} for i in ids], "next": next_url}

    def test_injects_parent_issue_id_into_every_row(self, monkeypatch: Any) -> None:
        # The occurrences endpoint response has no issue reference; without the injected issue_id the
        # composite primary key [issue_id, id] collapses to id and duplicate rows accumulate.
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/issues/?limit=100": self._issue_page([10, 20], None),
            "https://api.intruder.io/v1/issues/10/occurrences/?limit=100": {
                "results": [{"id": 1}, {"id": 2}],
                "next": None,
            },
            "https://api.intruder.io/v1/issues/20/occurrences/?limit=100": {"results": [{"id": 3}], "next": None},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "occurrences", pages)
        assert rows == [
            {"id": 1, "issue_id": 10},
            {"id": 2, "issue_id": 10},
            {"id": 3, "issue_id": 20},
        ]

    def test_follows_occurrence_pagination_within_an_issue(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/issues/?limit=100": self._issue_page([10], None),
            "https://api.intruder.io/v1/issues/10/occurrences/?limit=100": {
                "results": [{"id": 1}],
                "next": "https://api.intruder.io/v1/issues/10/occurrences/?limit=100&offset=100",
            },
            "https://api.intruder.io/v1/issues/10/occurrences/?limit=100&offset=100": {
                "results": [{"id": 2}],
                "next": None,
            },
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "occurrences", pages)
        assert [r["id"] for r in rows] == [1, 2]

    def test_resumes_from_bookmarked_issue(self, monkeypatch: Any) -> None:
        # Resuming must skip already-processed issue 10 and pick up at issue 20.
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/issues/?limit=100": self._issue_page([10, 20], None),
            "https://api.intruder.io/v1/issues/20/occurrences/?limit=100": {"results": [{"id": 3}], "next": None},
        }
        manager = _FakeResumableManager(IntruderResumeConfig(next_url=None, issue_id=20))
        rows = _collect(manager, monkeypatch, "occurrences", pages)
        assert rows == [{"id": 3, "issue_id": 20}]

    def test_deleted_bookmarked_issue_restarts_from_first(self, monkeypatch: Any) -> None:
        # If the bookmarked issue no longer exists, re-pull from the first issue (merge dedupes).
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/issues/?limit=100": self._issue_page([10, 20], None),
            "https://api.intruder.io/v1/issues/10/occurrences/?limit=100": {"results": [{"id": 1}], "next": None},
            "https://api.intruder.io/v1/issues/20/occurrences/?limit=100": {"results": [{"id": 3}], "next": None},
        }
        manager = _FakeResumableManager(IntruderResumeConfig(next_url=None, issue_id=999))
        rows = _collect(manager, monkeypatch, "occurrences", pages)
        assert [r["id"] for r in rows] == [1, 3]

    def test_advances_bookmark_between_issues(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {
            "https://api.intruder.io/v1/issues/?limit=100": self._issue_page([10, 20], None),
            "https://api.intruder.io/v1/issues/10/occurrences/?limit=100": {"results": [{"id": 1}], "next": None},
            "https://api.intruder.io/v1/issues/20/occurrences/?limit=100": {"results": [{"id": 3}], "next": None},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "occurrences", pages)
        # After finishing issue 10, the bookmark advances to issue 20 (no in-issue cursor).
        assert IntruderResumeConfig(next_url=None, issue_id=20) in manager.saved


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 503),
        ]
    )
    def test_retryable_status_codes_retry(self, _name: str, status: int) -> None:
        # 429/5xx must retry rather than fail the whole sync.
        retryable = MagicMock()
        retryable.status_code = status
        retryable.ok = False
        retryable.is_redirect = False
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.is_redirect = False
        good.json.return_value = {"results": []}

        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(intruder._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = intruder._fetch_page(session, "https://api.intruder.io/v1/targets/", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_network_errors_retry(self, _name: str, transient_error: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.is_redirect = False
        good.json.return_value = {"results": []}

        session = MagicMock()
        session.get.side_effect = [transient_error, good]

        with patch.object(intruder._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = intruder._fetch_page(session, "https://api.intruder.io/v1/targets/", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_401_is_not_retried_and_raises(self) -> None:
        # A 401 is a credential problem: raise immediately (surfaced as non-retryable upstream)
        # instead of burning retries.
        response = requests.Response()
        response.status_code = 401
        response.url = "https://api.intruder.io/v1/targets/"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            intruder._fetch_page(session, "https://api.intruder.io/v1/targets/", {}, MagicMock())

        assert session.get.call_count == 1


class TestUrlSafety:
    @parameterized.expand(
        [
            ("http_downgrade", "http://api.intruder.io/v1/targets/"),
            ("attacker_host", "https://evil.com/v1/targets/"),
            ("attacker_subdomain", "https://api.intruder.io.evil.com/v1/targets/"),
            ("userinfo_trick", "https://api.intruder.io@evil.com/v1/targets/"),
            ("wrong_path_prefix", "https://api.intruder.io/v2/targets/"),
            ("root_path", "https://api.intruder.io/"),
        ]
    )
    def test_validate_url_rejects_off_origin(self, _name: str, url: str) -> None:
        # A poisoned resume cursor or a malicious API-returned `next` must never be followed with the
        # bearer token — the allowlist is the SSRF guard.
        with pytest.raises(ValueError):
            intruder._validate_url(url)

    @parameterized.expand(
        [
            ("collection", "https://api.intruder.io/v1/targets/"),
            ("with_paging", "https://api.intruder.io/v1/issues/10/occurrences/?limit=100&offset=100"),
        ]
    )
    def test_validate_url_allows_intruder_origin(self, _name: str, url: str) -> None:
        assert intruder._validate_url(url) == url

    def test_fetch_page_validates_before_requesting(self) -> None:
        # Validation must run before the network call, so a bad URL never reaches the wire (and the
        # session — carrying the token — is never contacted).
        session = MagicMock()
        with pytest.raises(ValueError):
            intruder._fetch_page(session, "https://evil.com/v1/targets/", {}, MagicMock())
        session.get.assert_not_called()

    def test_fetch_page_refuses_redirects(self) -> None:
        # Redirects could retarget the authenticated request off-origin; they must be refused, not
        # followed. `allow_redirects=False` returns the 3xx, which we reject.
        redirect = requests.Response()
        redirect.status_code = 302
        redirect.headers["Location"] = "https://evil.com"

        session = MagicMock()
        session.get.return_value = redirect

        with pytest.raises(requests.HTTPError):
            intruder._fetch_page(session, "https://api.intruder.io/v1/targets/", {}, MagicMock())


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        with patch.object(intruder, "make_tracked_session") as make_session:
            make_session.return_value.get.return_value = response
            assert validate_credentials("token") is expected

    def test_network_error_is_not_valid(self) -> None:
        with patch.object(intruder, "make_tracked_session") as make_session:
            make_session.return_value.get.side_effect = requests.ConnectionError("boom")
            assert validate_credentials("token") is False


class TestSessionHardening:
    def test_validate_credentials_redacts_token(self, monkeypatch: Any) -> None:
        # Dropping redact_values would leak the bearer token into logged URLs / captured samples.
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            session = MagicMock()
            session.get.return_value = response
            return session

        monkeypatch.setattr(intruder, "make_tracked_session", fake_session)
        validate_credentials("secret-token")
        assert captured.get("redact_values") == ("secret-token",)

    def test_get_rows_redacts_token_and_disables_adapter_retries(self, monkeypatch: Any) -> None:
        # tenacity in `_fetch_page` is the single retry authority; the adapter must not stack its own.
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(intruder, "make_tracked_session", fake_session)
        monkeypatch.setattr(intruder, "_fetch_page", lambda *a, **k: {"results": [], "next": None})

        list(
            get_rows(
                access_token="secret-token",
                endpoint="targets",
                logger=MagicMock(),
                resumable_source_manager=cast(ResumableSourceManager[IntruderResumeConfig], _FakeResumableManager()),
            )
        )
        assert captured.get("redact_values") == ("secret-token",)
        assert captured.get("retry") is not None and captured["retry"].total == 0


class TestSourceResponse:
    @parameterized.expand(
        [
            ("targets", ["id"], None),
            ("scans", ["id"], ["created_at"]),
            ("scan_schedules", ["id"], None),
            ("issues", ["id"], None),
            ("occurrences", ["issue_id", "id"], ["first_seen_at"]),
            ("fixed_occurrences", ["id"], ["first_seen_at"]),
            ("tags", ["name"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        response = intruder_source(
            access_token="token", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
