import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.automox import automox
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
    AutomoxOrganizationError,
    AutomoxResumeConfig,
    AutomoxRetryableError,
    _build_url,
    _incremental_param_value,
    automox_source,
    get_rows,
    resolve_organization,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import (
    AUTOMOX_ENDPOINTS,
    ENDPOINTS,
)

ORGS_BODY = [
    {"id": 123, "uuid": "uuid-123", "name": "Org A"},
    {"id": 456, "uuid": "uuid-456", "name": "Org B"},
]


class _FakeResumableManager:
    def __init__(self, state: AutomoxResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AutomoxResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AutomoxResumeConfig | None:
        return self._state

    def save_state(self, data: AutomoxResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"" if body is None else json.dumps(body).encode()
    return response


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


class TestBuildUrl:
    def test_page_zero_is_kept(self) -> None:
        # page=0 is the first page; it must not be dropped as a falsy value.
        url = _build_url("/servers", {"page": 0, "limit": 500})
        assert url == "https://console.automox.com/api/servers?page=0&limit=500"

    def test_omits_none_values(self) -> None:
        url = _build_url("/servers", {"page": 0, "o": None})
        assert "o=" not in url


class TestFetchJson:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(automox._fetch_json.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(AutomoxRetryableError):
                automox._fetch_json(session, "https://console.automox.com/api/servers", MagicMock())
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            automox._fetch_json(session, "https://console.automox.com/api/servers", MagicMock())


class TestFetchPage:
    def test_unwraps_data_selector(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, {"data": [{"policy_id": 1}], "metadata": {}})
        rows = automox._fetch_page(
            session, AUTOMOX_ENDPOINTS["policy_runs"], "https://console.automox.com/api/x", MagicMock()
        )
        assert rows == [{"policy_id": 1}]

    def test_missing_data_key_returns_empty_list(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, {"metadata": {}})
        rows = automox._fetch_page(
            session, AUTOMOX_ENDPOINTS["policy_runs"], "https://console.automox.com/api/x", MagicMock()
        )
        assert rows == []

    @parameterized.expand(
        [
            ("bare_endpoint_object_body", "devices", {"error": "unexpected"}),
            ("wrapped_endpoint_list_body", "policy_runs", [{"policy_id": 1}]),
        ]
    )
    def test_contract_violations_raise_value_error(self, _name: str, endpoint: str, body: Any) -> None:
        # A malformed 200 is a permanent contract violation, so it must bypass the retry decorator.
        session = MagicMock()
        session.get.return_value = _response_with_status(200, body)
        with pytest.raises(ValueError):
            automox._fetch_page(session, AUTOMOX_ENDPOINTS[endpoint], "https://console.automox.com/api/x", MagicMock())
        assert session.get.call_count == 1


class TestIncrementalParamValue:
    @parameterized.expand(
        [
            # policy_runs subtracts the 24h lookback and formats a full RFC3339 timestamp.
            (
                "policy_runs_datetime",
                "policy_runs",
                datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
                "2026-03-09T12:00:00Z",
            ),
            ("policy_runs_string", "policy_runs", "2026-03-10T12:00:00Z", "2026-03-09T12:00:00Z"),
            # events subtracts a 1-day lookback and formats a date-only value.
            ("events_datetime", "events", datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC), "2026-03-09"),
            ("events_string", "events", "2026-03-10T12:00:00Z", "2026-03-09"),
        ]
    )
    def test_formats_watermark(self, _name: str, endpoint: str, last_value: Any, expected: str) -> None:
        assert _incremental_param_value(AUTOMOX_ENDPOINTS[endpoint], last_value) == expected

    @parameterized.expand([("none", None), ("garbage_string", "not-a-date")])
    def test_unusable_watermark_returns_none(self, _name: str, last_value: Any) -> None:
        assert _incremental_param_value(AUTOMOX_ENDPOINTS["policy_runs"], last_value) is None

    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A future-dated cursor must not produce a filter past now, which would skip new rows forever.
        value = _incremental_param_value(AUTOMOX_ENDPOINTS["policy_runs"], datetime(2099, 1, 1, tzinfo=UTC))
        assert value is not None
        assert datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= datetime.now(UTC)


class TestResolveOrganization:
    @parameterized.expand(
        [
            ("explicit_id", "456", (456, "uuid-456")),
            ("explicit_id_with_whitespace", " 123 ", (123, "uuid-123")),
        ]
    )
    def test_explicit_id_is_matched(self, _name: str, organization_id: str, expected: tuple[int, str]) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, ORGS_BODY)
        assert resolve_organization(session, organization_id, MagicMock()) == expected

    def test_single_org_is_used_when_id_not_set(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, [ORGS_BODY[0]])
        assert resolve_organization(session, None, MagicMock()) == (123, "uuid-123")

    @parameterized.expand(
        [
            ("unknown_id", "999", ORG_NOT_FOUND_ERROR),
            ("multiple_orgs_no_id", None, MULTIPLE_ORGS_ERROR),
        ]
    )
    def test_unresolvable_org_raises(self, _name: str, organization_id: str | None, expected_prefix: str) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, ORGS_BODY)
        with pytest.raises(AutomoxOrganizationError, match=expected_prefix):
            resolve_organization(session, organization_id, MagicMock())


class TestMakeSession:
    def test_disables_sample_capture_and_redacts_key(self) -> None:
        # `/orgs` and `/users` responses carry org `access_key` secrets the name-based sample
        # scrubbers don't recognise, so the session must opt out of HTTP sample capture and mask
        # the bearer token in logged URLs.
        with patch.object(automox, "make_tracked_session") as mock_session:
            automox._make_session("secret-key")
        kwargs = mock_session.call_args.kwargs
        assert kwargs["capture"] is False
        assert kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    def _patch_session(self, response: requests.Response) -> Any:
        session = MagicMock()
        session.get.return_value = response
        return patch.object(automox, "make_tracked_session", return_value=session)

    def test_valid_key_single_org(self) -> None:
        with self._patch_session(_response_with_status(200, [ORGS_BODY[0]])):
            assert validate_credentials("key") == (True, None)

    def test_invalid_key_returns_friendly_error(self) -> None:
        with self._patch_session(_response_with_status(401)):
            ok, error = validate_credentials("bad-key")
        assert ok is False
        assert error is not None
        assert "API key" in error

    def test_multiple_orgs_without_id_returns_org_error(self) -> None:
        with self._patch_session(_response_with_status(200, ORGS_BODY)):
            ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None
        assert MULTIPLE_ORGS_ERROR in error

    def test_unknown_org_id_returns_org_error(self) -> None:
        with self._patch_session(_response_with_status(200, ORGS_BODY)):
            ok, error = validate_credentials("key", "999")
        assert ok is False
        assert error is not None
        assert ORG_NOT_FOUND_ERROR in error


class TestGetRows:
    @staticmethod
    def _collect(
        endpoint: str,
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: list[list[dict]],
        organization_id: str | None = "123",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        orgs_body: list[dict] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """Drive ``get_rows`` with canned page bodies, returning rows and requested URLs."""
        fetched_urls: list[str] = []
        config = AUTOMOX_ENDPOINTS[endpoint]

        def fake_fetch_json(session: Any, url: str, logger: Any) -> Any:
            fetched_urls.append(url)
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            # Org resolution calls /orgs without our endpoint's page-size marker.
            if parsed.path.endswith("/orgs") and query.get("limit") == ["500"] and endpoint != "organizations":
                return orgs_body if orgs_body is not None else ORGS_BODY
            index = int(query["page"][0])
            page = pages[index] if index < len(pages) else []
            return {"data": page, "metadata": {}} if config.data_selector else page

        monkeypatch.setattr(automox, "_fetch_json", fake_fetch_json)
        monkeypatch.setattr(automox, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            organization_id=organization_id,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_paginates_until_short_page_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        page_size = AUTOMOX_ENDPOINTS["devices"].page_size
        full_page = [{"id": i} for i in range(page_size)]
        last_page = [{"id": page_size}]
        manager = _FakeResumableManager()
        rows, urls = self._collect("devices", manager, monkeypatch, [full_page, last_page])

        assert len(rows) == page_size + 1
        # One org-resolution call plus two pages.
        page_urls = [u for u in urls if "/servers" in u]
        assert [_query(u)["page"] for u in page_urls] == [["0"], ["1"]]
        # The `o` org param rides on every page request.
        assert all(_query(u)["o"] == ["123"] for u in page_urls)
        # State points at the next page and is only saved after a full (non-terminal) page.
        assert manager.saved == [AutomoxResumeConfig(page=1, incremental_param_value=None)]

    def test_single_short_page_stops_without_saving_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect("devices", manager, monkeypatch, [[{"id": 1}]])
        assert rows == [{"id": 1}]
        assert manager.saved == []

    def test_resume_seeds_page_and_reuses_stored_incremental_value(self, monkeypatch: Any) -> None:
        # On resume the original run's time filter must be reused verbatim: recomputing it from the
        # advanced watermark would change the filtered result set under the saved page number.
        manager = _FakeResumableManager(AutomoxResumeConfig(page=1, incremental_param_value="2026-01-01T00:00:00Z"))
        _, urls = self._collect(
            "policy_runs",
            manager,
            monkeypatch,
            [[{"execution_token": "a"}], [{"execution_token": "b"}]],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )
        page_urls = [u for u in urls if "policy-runs" in u]
        assert [_query(u)["page"] for u in page_urls] == [["1"]]
        assert all(_query(u)["start_time"] == ["2026-01-01T00:00:00Z"] for u in page_urls)

    def test_policy_runs_sends_org_uuid_sort_and_start_time(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect(
            "policy_runs",
            manager,
            monkeypatch,
            [[{"execution_token": "a"}]],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
        )
        run_urls = [u for u in urls if "policy-runs" in u]
        assert len(run_urls) == 1
        query = _query(run_urls[0])
        assert query["org"] == ["uuid-123"]
        assert query["sort"] == ["run_time:asc"]
        # 24h lookback applied to the watermark.
        assert query["start_time"] == ["2026-03-09T12:00:00Z"]

    def test_first_incremental_sync_omits_time_filter(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect(
            "policy_runs",
            manager,
            monkeypatch,
            [[{"execution_token": "a"}]],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        run_urls = [u for u in urls if "policy-runs" in u]
        assert "start_time" not in _query(run_urls[0])

    def test_events_sends_date_only_filter(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect(
            "events",
            manager,
            monkeypatch,
            [[{"id": 1}]],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
        )
        event_urls = [u for u in urls if "/events" in u]
        assert _query(event_urls[0])["startDate"] == ["2026-03-09"]

    def test_packages_formats_org_id_into_path(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect("packages", manager, monkeypatch, [[{"id": 1, "server_id": 2}]])
        package_urls = [u for u in urls if "/packages" in u]
        assert len(package_urls) == 1
        assert urlparse(package_urls[0]).path == "/api/orgs/123/packages"

    def test_organizations_endpoint_restricts_to_configured_org(self, monkeypatch: Any) -> None:
        # `/orgs` lists every organization the API key can access, but the table must expose only
        # the org this source is configured for — otherwise a teammate could read metadata for
        # organizations the source owner never selected.
        manager = _FakeResumableManager()
        org_rows = [
            {"id": 123, "uuid": "uuid-123", "name": "Org A"},
            {"id": 456, "uuid": "uuid-456", "name": "Org B"},
        ]
        rows, _ = self._collect("organizations", manager, monkeypatch, [org_rows], organization_id="456")
        assert rows == [{"id": 456, "uuid": "uuid-456", "name": "Org B"}]

    def test_credential_fields_are_stripped_from_rows(self, monkeypatch: Any) -> None:
        # Automox embeds an org enrollment `access_key` at the top level and again under nested
        # `orgs[]` entries; neither may reach the warehouse, at any depth.
        manager = _FakeResumableManager()
        user_row = {
            "id": 7,
            "access_key": "org-enrollment-secret",
            "orgs": [{"id": 123, "access_key": "nested-secret", "name": "Org A"}],
        }
        rows, _ = self._collect("users", manager, monkeypatch, [[user_row]])
        assert rows == [{"id": 7, "orgs": [{"id": 123, "name": "Org A"}]}]

    def test_missing_org_uuid_raises_for_policy_runs(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        with pytest.raises(AutomoxOrganizationError, match=ORG_NOT_FOUND_ERROR):
            self._collect(
                "policy_runs",
                manager,
                monkeypatch,
                [[]],
                orgs_body=[{"id": 123, "name": "Org A"}],
            )


class TestAutomoxSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = AUTOMOX_ENDPOINTS[name]
        response = automox_source(
            api_key="key",
            organization_id="123",
            endpoint=name,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_policy_runs_is_ascending_and_events_defers_watermark(self) -> None:
        # policy_runs requests an explicit ascending sort so per-batch watermark checkpoints are
        # safe; events has no documented ordering, so it must stay "desc" (watermark persisted only
        # on completed syncs).
        assert AUTOMOX_ENDPOINTS["policy_runs"].sort_mode == "asc"
        assert AUTOMOX_ENDPOINTS["events"].sort_mode == "desc"

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # Guards against accidentally partitioning on a churning field like last_refresh_time.
        assert {cfg.partition_key for cfg in AUTOMOX_ENDPOINTS.values() if cfg.partition_key} == {
            "create_time",
            "run_time",
        }
