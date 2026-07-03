from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud import k6_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud import (
    K6CloudResumeConfig,
    _absolute_url,
    _build_initial_params,
    _format_rfc3339,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import K6_CLOUD_ENDPOINTS


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("microseconds", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_test_runs_incremental_adds_created_after_and_no_orderby(self) -> None:
        # The top-level test_runs endpoint rejects $orderby, so it must never be sent there.
        params = _build_initial_params(
            K6_CLOUD_ENDPOINTS["test_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["created_after"] == "2026-03-04T02:58:14.000Z"
        assert params["$top"] == "1000"
        assert "$orderby" not in params

    def test_test_runs_full_refresh_has_no_time_filter(self) -> None:
        params = _build_initial_params(
            K6_CLOUD_ENDPOINTS["test_runs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert "created_after" not in params

    def test_projects_sends_orderby_but_no_time_filter(self) -> None:
        # Projects has no server-side time filter, so passing a last value must not add one.
        params = _build_initial_params(
            K6_CLOUD_ENDPOINTS["projects"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["$orderby"] == "created"
        assert "created_after" not in params

    def test_load_zones_is_not_paginated(self) -> None:
        params = _build_initial_params(
            K6_CLOUD_ENDPOINTS["load_zones"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert "$top" not in params


class TestAbsoluteUrl:
    @parameterized.expand(
        [
            (
                "absolute_https",
                "https://api.k6.io/cloud/v6/test_runs",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
            (
                "relative_path",
                "https://api.k6.io/cloud/v6/test_runs",
                "/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
        ]
    )
    def test_absolute_url(self, _name: str, current: str, next_link: str, expected: str) -> None:
        assert _absolute_url(current, next_link) == expected

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/steal"),
            ("relative_to_other_host", "//evil.example.com/steal"),
            ("http_scheme", "http://api.k6.io/cloud/v6/test_runs"),
        ]
    )
    def test_rejects_non_k6_next_link(self, _name: str, next_link: str) -> None:
        # A tampered `@nextLink` must never redirect the credential-bearing request off the k6 origin.
        with pytest.raises(ValueError):
            _absolute_url("https://api.k6.io/cloud/v6/test_runs", next_link)


class _FakeResumableManager:
    def __init__(self, state: K6CloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[K6CloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> K6CloudResumeConfig | None:
        return self._state

    def save_state(self, data: K6CloudResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str) -> list[dict]:
        def fake_fetch(session: Any, url: str, params: Any, headers: Any, logger: Any) -> dict:
            return pages[url]

        monkeypatch.setattr(k6_cloud, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for batch in get_rows(
            api_token="tok",
            stack_id="1",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_follows_next_link_pagination(self, monkeypatch: Any) -> None:
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        pages = {
            "https://api.k6.io/cloud/v6/test_runs": {
                "value": [{"id": 1}, {"id": 2}],
                "@nextLink": next_url,
            },
            next_url: {"value": [{"id": 3}], "@nextLink": None},
        }
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages, "test_runs")
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_saves_state_after_each_page_except_last(self, monkeypatch: Any) -> None:
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        pages = {
            "https://api.k6.io/cloud/v6/test_runs": {"value": [{"id": 1}], "@nextLink": next_url},
            next_url: {"value": [{"id": 2}], "@nextLink": None},
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages, "test_runs")
        # State is saved once (after the first page); the final page has no next link to persist.
        assert [s.next_url for s in manager.saved] == [next_url]

    def test_resumes_from_saved_next_link(self, monkeypatch: Any) -> None:
        resume_url = "https://api.k6.io/cloud/v6/test_runs?$skip=2000&$top=1000"
        pages = {resume_url: {"value": [{"id": 9}], "@nextLink": None}}
        manager = _FakeResumableManager(K6CloudResumeConfig(next_url=resume_url))
        rows = self._collect(manager, monkeypatch, pages, "test_runs")
        assert rows == [{"id": 9}]

    def test_rejects_poisoned_resume_url(self, monkeypatch: Any) -> None:
        # Resume state is loaded from Redis; a poisoned next link must not leak credentials off-origin.
        manager = _FakeResumableManager(K6CloudResumeConfig(next_url="https://evil.example.com/steal"))
        with pytest.raises(ValueError):
            self._collect(manager, monkeypatch, {}, "test_runs")

    def test_missing_value_key_raises(self, monkeypatch: Any) -> None:
        # A 200 whose body lacks `value` is an unexpected format — fail loud rather than empty the table.
        pages = {"https://api.k6.io/cloud/v6/load_zones": {"@nextLink": None}}
        manager = _FakeResumableManager()
        with pytest.raises(KeyError):
            self._collect(manager, monkeypatch, pages, "load_zones")

    def test_non_paginated_endpoint_reads_single_page(self, monkeypatch: Any) -> None:
        # load_zones returns everything in one response with no @nextLink and never saves state.
        pages = {
            "https://api.k6.io/cloud/v6/load_zones": {"value": [{"id": 1}, {"id": 2}]},
        }
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages, "load_zones")
        assert rows == [{"id": 1}, {"id": 2}]
        assert manager.saved == []


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        bad = MagicMock()
        bad.status_code = status
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"value": []}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(k6_cloud._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = k6_cloud._fetch_page(session, "https://api.k6.io/cloud/v6/test_runs", None, {}, MagicMock())

        assert result == {"value": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401/403 is not retryable — raise_for_status must surface it on the first attempt.
        error_response = requests.Response()
        error_response.status_code = 401
        bad = MagicMock()
        bad.status_code = 401
        bad.ok = False
        bad.text = "unauthorized"
        bad.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=error_response)

        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            k6_cloud._fetch_page(session, "https://api.k6.io/cloud/v6/test_runs", None, {}, MagicMock())
        assert session.get.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, (True, False)),
            ("bad_token", 401, None, (False, False)),
            ("forbidden", 403, None, (False, True)),
            ("forbidden_schema", 403, "test_runs", (False, True)),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, schema_name: str | None, expected: tuple[bool, bool]
    ) -> None:
        response = MagicMock()
        response.status_code = status
        # `validate_credentials` opens the session as a context manager, so the `with` target
        # must be the same mock we configure `.get` on.
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response

        with patch.object(k6_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("tok", "1", schema_name) == expected

    def test_network_error_is_invalid_not_forbidden(self) -> None:
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(k6_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("tok", "1") == (False, False)

    def test_schemaless_probe_hits_auth_endpoint(self) -> None:
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with patch.object(k6_cloud, "make_tracked_session", return_value=session):
            validate_credentials("tok", "1")
        assert session.get.call_args[0][0].endswith("/cloud/v6/auth")
