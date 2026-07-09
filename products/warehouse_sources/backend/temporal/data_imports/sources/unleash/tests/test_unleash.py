from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.unleash import unleash
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.settings import UNLEASH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.unleash import (
    PAGE_SIZE,
    UnleashHostNotAllowedError,
    UnleashResumeConfig,
    UnleashRetryableError,
    _extract_rows,
    _headers,
    check_endpoint_permissions,
    get_rows,
    normalize_instance_url,
    unleash_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = unleash._fetch.__wrapped__  # type: ignore[attr-defined]

BASE_URL = "https://unleash.example.com"
TOKEN = "user:secret-token"


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    is_redirect: bool = False,
) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.json.return_value = json_data
    response.text = str(json_data)
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
    )
    return response


class _FakeResumableManager:
    def __init__(self, state: UnleashResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[UnleashResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> UnleashResumeConfig | None:
        return self._state

    def save_state(self, data: UnleashResumeConfig) -> None:
        self.saved.append(data)


class TestUnleash:
    # --- URL normalization ---

    @parameterized.expand(
        [
            ("plain", "https://unleash.example.com", "https://unleash.example.com"),
            ("trailing_slash", "https://unleash.example.com/", "https://unleash.example.com"),
            ("api_suffix", "https://unleash.example.com/api", "https://unleash.example.com"),
            ("api_admin_suffix", "https://unleash.example.com/api/admin/", "https://unleash.example.com"),
            ("no_scheme", "unleash.example.com", "https://unleash.example.com"),
            ("whitespace", "  https://unleash.example.com  ", "https://unleash.example.com"),
            (
                # Unleash cloud URLs carry the instance name as a path prefix — it must be preserved.
                "cloud_path_prefix",
                "https://us.app.unleash-hosted.com/my-instance/",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
            (
                "cloud_path_prefix_with_api_suffix",
                "https://us.app.unleash-hosted.com/my-instance/api/admin",
                "https://us.app.unleash-hosted.com/my-instance",
            ),
        ]
    )
    def test_normalize_instance_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_instance_url(raw) == expected

    def test_headers_send_raw_token_without_bearer_prefix(self) -> None:
        # Unleash rejects Bearer-prefixed tokens — the raw token is the whole header value.
        assert _headers(TOKEN)["Authorization"] == TOKEN

    # --- row extraction ---

    @parameterized.expand(
        [
            ("wrapped", "projects", {"version": 1, "projects": [{"id": "a"}]}, [{"id": "a"}]),
            ("bare_array", "context_fields", [{"name": "userId"}], [{"name": "userId"}]),
        ]
    )
    def test_extract_rows(self, _name: str, endpoint: str, payload: Any, expected: list[dict]) -> None:
        assert _extract_rows(payload, UNLEASH_ENDPOINTS[endpoint], "http://url") == expected

    @parameterized.expand(
        [
            ("wrapped_missing_key", "projects", {"version": 1}),
            ("wrapped_got_array", "projects", [{"id": "a"}]),
            ("bare_got_object", "context_fields", {"fields": []}),
        ]
    )
    def test_extract_rows_rejects_unexpected_payloads(self, _name: str, endpoint: str, payload: Any) -> None:
        with pytest.raises(UnleashRetryableError):
            _extract_rows(payload, UNLEASH_ENDPOINTS[endpoint], "http://url")

    # --- fetch ---

    @parameterized.expand([(429,), (500,), (503,)])
    def test_fetch_raises_retryable_on_transient_statuses(self, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(UnleashRetryableError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    @parameterized.expand([(401,), (403,), (404,)])
    def test_fetch_raises_http_error_on_permanent_statuses(self, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    @parameterized.expand([(301,), (302,), (307,)])
    def test_fetch_refuses_redirects(self, status_code: int) -> None:
        # The session never follows redirects — a 3xx would move the sync off the validated
        # host (SSRF), so it must fail rather than be treated as an empty page.
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(UnleashHostNotAllowedError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    # --- get_rows ---

    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[Any, Any],
        endpoint: str,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        """Run get_rows with a fake _fetch keyed by the `offset` param (None = unpaginated)."""
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, params: Optional[dict], logger: Any) -> Any:
            calls.append({"url": url, "params": params})
            return pages[params["offset"] if params else None]

        monkeypatch.setattr(unleash, "_fetch", fake_fetch)
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: MagicMock())
        monkeypatch.setattr(unleash, "_check_host", lambda instance_url, team_id: None)

        rows: list[dict] = []
        for batch in get_rows(
            instance_url=BASE_URL,
            api_token=TOKEN,
            endpoint=endpoint,
            team_id=1,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows, calls

    def test_unpaginated_endpoint_fetches_once_without_resume_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, calls = self._collect(
            manager, monkeypatch, {None: {"version": 1, "projects": [{"id": "a"}, {"id": "b"}]}}, "projects"
        )
        assert rows == [{"id": "a"}, {"id": "b"}]
        assert len(calls) == 1
        assert calls[0]["url"] == f"{BASE_URL}/api/admin/projects"
        assert calls[0]["params"] is None
        # The whole collection arrives in one response, so there is nothing to resume.
        assert manager.saved == []

    def test_unpaginated_endpoint_with_no_rows_yields_no_batches(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()

        def fake_fetch(session: Any, url: str, params: Any, logger: Any) -> Any:
            return {"version": 1, "projects": []}

        monkeypatch.setattr(unleash, "_fetch", fake_fetch)
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: MagicMock())
        monkeypatch.setattr(unleash, "_check_host", lambda instance_url, team_id: None)

        batches = list(
            get_rows(
                instance_url=BASE_URL,
                api_token=TOKEN,
                endpoint="projects",
                team_id=1,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        # An empty collection must not push an empty batch into the pipeline.
        assert batches == []

    def test_paginated_endpoint_walks_offsets_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        full_page = [{"name": f"flag-{i}"} for i in range(PAGE_SIZE)]
        pages = {
            0: {"features": full_page, "total": PAGE_SIZE + 2},
            PAGE_SIZE: {"features": [{"name": "x"}, {"name": "y"}], "total": PAGE_SIZE + 2},
        }
        rows, calls = self._collect(manager, monkeypatch, pages, "features")

        assert len(rows) == PAGE_SIZE + 2
        assert [c["params"]["offset"] for c in calls] == [0, PAGE_SIZE]
        # Stable ascending sort keeps page boundaries fixed while walking offsets.
        assert all(
            c["params"]["sortBy"] == "createdAt"
            and c["params"]["sortOrder"] == "asc"
            and c["params"]["limit"] == PAGE_SIZE
            for c in calls
        )
        # State is saved once — after the first (full) page, pointing at the next offset.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_paginated_endpoint_stops_on_short_page_without_total(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, calls = self._collect(manager, monkeypatch, {0: {"features": [{"name": "only"}]}}, "features")
        assert rows == [{"name": "only"}]
        assert len(calls) == 1
        assert manager.saved == []

    def test_paginated_endpoint_stops_when_total_reached_on_full_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        full_page = [{"name": f"flag-{i}"} for i in range(PAGE_SIZE)]
        rows, calls = self._collect(manager, monkeypatch, {0: {"features": full_page, "total": PAGE_SIZE}}, "features")
        assert len(rows) == PAGE_SIZE
        # total == offset means the collection is exhausted — no extra empty-page request.
        assert len(calls) == 1
        assert manager.saved == []

    def test_paginated_endpoint_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(UnleashResumeConfig(offset=PAGE_SIZE))
        pages = {PAGE_SIZE: {"features": [{"name": "x"}], "total": PAGE_SIZE + 1}}
        rows, calls = self._collect(manager, monkeypatch, pages, "features")
        assert rows == [{"name": "x"}]
        assert [c["params"]["offset"] for c in calls] == [PAGE_SIZE]

    def test_get_rows_blocks_unsafe_hosts(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        with pytest.raises(UnleashHostNotAllowedError):
            list(
                get_rows(
                    instance_url="https://10.0.0.1",
                    api_token=TOKEN,
                    endpoint="projects",
                    team_id=1,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    # --- SourceResponse assembly ---

    @parameterized.expand(
        [
            ("features", ["name"]),
            # A tag has no id — its identity is the (type, value) pair; a single-column key here
            # would seed duplicate rows and multi-match on every merge.
            ("tags", ["type", "value"]),
        ]
    )
    def test_unleash_source_returns_declared_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = unleash_source(
            instance_url=BASE_URL,
            api_token=TOKEN,
            endpoint=endpoint,
            team_id=1,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    # --- credential validation ---

    def _validate(self, monkeypatch: Any, response: MagicMock, schema_name: Optional[str] = None) -> tuple:
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        return validate_credentials(BASE_URL, TOKEN, schema_name=schema_name, team_id=1)

    def test_validate_credentials_success(self, monkeypatch: Any) -> None:
        assert self._validate(monkeypatch, _mock_response(200, {"projects": []})) == (True, None)

    def test_validate_credentials_invalid_token(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(401, {"message": "nope"}))
        assert valid is False
        assert message == "Invalid Unleash API token"

    def test_validate_credentials_accepts_403_at_source_create(self, monkeypatch: Any) -> None:
        # A valid token may lack the permission for the probe endpoint; source creation must
        # still go through, and per-schema syncs surface their own permission errors.
        assert self._validate(monkeypatch, _mock_response(403, {"message": "denied"})) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(403, {"message": "denied"}), schema_name="users")
        assert valid is False
        assert message == "denied"

    def test_validate_credentials_rejects_redirects(self, monkeypatch: Any) -> None:
        # A redirect could bounce the probe to an internal address, defeating the host check.
        valid, _ = self._validate(monkeypatch, _mock_response(200, {}, is_redirect=True))
        assert valid is False

    def test_validate_credentials_rejects_unsafe_host(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        valid, message = validate_credentials("https://10.0.0.1", TOKEN, team_id=1)
        assert valid is False
        assert message == "blocked"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://unleash.example.com"),
            # Parser-differential SSRF guards: urlparse and urllib3 disagree on where the
            # authority ends for backslash/userinfo URLs, so validation could approve one host
            # while requests connects to another.
            ("userinfo", "https://169.254.169.254@unleash.example.com"),
            ("backslash", "https://169.254.169.254\\@unleash.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@unleash.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        valid, message = validate_credentials(raw_url, TOKEN, team_id=1)
        assert valid is False
        assert message == "Invalid Unleash instance URL"

    def test_check_endpoint_permissions_rejects_ambiguous_url_for_all_endpoints(self) -> None:
        result = check_endpoint_permissions(
            "https://169.254.169.254\\@unleash.example.com", TOKEN, ["projects", "users"], team_id=1
        )
        assert result == {"projects": "Invalid Unleash instance URL", "users": "Invalid Unleash instance URL"}

    def test_get_rows_blocks_ambiguous_url(self) -> None:
        with pytest.raises(UnleashHostNotAllowedError):
            list(
                get_rows(
                    instance_url="https://169.254.169.254\\@unleash.example.com",
                    api_token=TOKEN,
                    endpoint="projects",
                    team_id=1,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    def test_validate_credentials_handles_connection_errors(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        valid, message = validate_credentials(BASE_URL, TOKEN, team_id=1)
        assert valid is False
        assert message is not None and "Could not connect to Unleash" in message

    # --- per-endpoint permissions ---

    def test_check_endpoint_permissions_flags_admin_gated_tables(self, monkeypatch: Any) -> None:
        def get(url: str, params: Any = None, **kwargs: Any) -> MagicMock:
            if url.endswith("/api/admin/user-admin"):
                return _mock_response(403, {"message": "You need the ADMIN permission."})
            return _mock_response(200, {"projects": [], "features": [], "total": 0})

        session = MagicMock()
        session.get.side_effect = get
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))

        result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects", "features", "users"], team_id=1)
        assert result["projects"] is None
        assert result["features"] is None
        assert result["users"] is not None and "Admin root role" in result["users"]

    @parameterized.expand(
        [
            # Transient failures are not permission problems — they must not flag the table.
            ("server_error", 500, None),
            ("throttled", 429, None),
            ("invalid_token", 401, "Invalid Unleash API token"),
        ]
    )
    def test_check_endpoint_permissions_status_mapping(
        self, _name: str, status_code: int, expected: Optional[str]
    ) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code, {})
        with (
            patch.object(unleash, "make_tracked_session", lambda **kwargs: session),
            patch.object(unleash, "_is_host_safe", lambda host, team_id: (True, None)),
        ):
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1)
        assert result["projects"] == expected

    def test_check_endpoint_permissions_treats_network_blips_as_reachable(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(unleash, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (True, None))
        assert check_endpoint_permissions(BASE_URL, TOKEN, ["projects"], team_id=1) == {"projects": None}

    def test_check_endpoint_permissions_blocks_unsafe_host_for_all_endpoints(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(unleash, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        result = check_endpoint_permissions("https://10.0.0.1", TOKEN, ["projects", "users"], team_id=1)
        assert result == {"projects": "blocked", "users": "blocked"}
