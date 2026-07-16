import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.datahub import datahub
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.datahub import (
    PAGE_SIZE,
    DatahubHostNotAllowedError,
    DatahubResponseTooLargeError,
    DatahubResumeConfig,
    DatahubRetryableError,
    _extract_entities,
    _headers,
    check_endpoint_permissions,
    datahub_source,
    get_rows,
    normalize_instance_url,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_unwrapped = datahub._fetch.__wrapped__  # type: ignore[attr-defined]

BASE_URL = "https://datahub.example.com"
TOKEN = "eyJhbGciOi-secret-token"


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    is_redirect: bool = False,
    raw_body: bytes | None = None,
) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.url = BASE_URL
    # The source streams responses and reads the body via raw.read under a size cap, never
    # response.json(); feed the encoded body through raw.read (which ignores its byte-count arg).
    body = raw_body if raw_body is not None else (b"" if json_data is None else json.dumps(json_data).encode())
    # `raw` is set in Response.__init__, so spec=Response doesn't expose it — attach it ourselves.
    response.raw = MagicMock()
    response.raw.read.return_value = body
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} Client Error", response=response) if status_code >= 400 else None
    )
    return response


class _FakeResumableManager:
    def __init__(self, state: DatahubResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DatahubResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DatahubResumeConfig | None:
        return self._state

    def save_state(self, data: DatahubResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


class TestDatahub:
    # --- URL normalization ---

    @parameterized.expand(
        [
            ("plain", "https://datahub.example.com", "https://datahub.example.com"),
            ("trailing_slash", "https://datahub.example.com/", "https://datahub.example.com"),
            ("openapi_suffix", "https://datahub.example.com/openapi", "https://datahub.example.com"),
            ("no_scheme", "datahub.example.com", "https://datahub.example.com"),
            ("whitespace", "  https://datahub.example.com  ", "https://datahub.example.com"),
            (
                # DataHub Cloud serves the metadata service under a /gms path prefix — it must be preserved.
                "gms_path_prefix",
                "https://tenant.acryl.io/gms/",
                "https://tenant.acryl.io/gms",
            ),
            (
                "gms_path_prefix_with_openapi_suffix",
                "https://tenant.acryl.io/gms/openapi",
                "https://tenant.acryl.io/gms",
            ),
        ]
    )
    def test_normalize_instance_url(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_instance_url(raw) == expected

    def test_headers_send_bearer_token(self) -> None:
        assert _headers(TOKEN)["Authorization"] == f"Bearer {TOKEN}"

    # --- scroll envelope extraction ---

    @parameterized.expand(
        [
            ("page_with_cursor", {"scrollId": "abc", "entities": [{"urn": "u1"}]}, [{"urn": "u1"}], "abc"),
            ("final_page", {"entities": [{"urn": "u2"}]}, [{"urn": "u2"}], None),
            # An empty final page may omit `entities` entirely — that's a valid empty result.
            ("empty_without_key", {}, [], None),
            # An empty-string scrollId must not be followed as a cursor.
            ("empty_cursor", {"scrollId": "", "entities": []}, [], None),
        ]
    )
    def test_extract_entities(
        self, _name: str, payload: Any, expected_rows: list[dict], expected_cursor: str | None
    ) -> None:
        assert _extract_entities(payload, "http://url") == (expected_rows, expected_cursor)

    @parameterized.expand(
        [
            ("bare_list", [{"urn": "u1"}]),
            ("entities_not_a_list", {"entities": {"urn": "u1"}}),
        ]
    )
    def test_extract_entities_rejects_unexpected_payloads(self, _name: str, payload: Any) -> None:
        with pytest.raises(DatahubRetryableError):
            _extract_entities(payload, "http://url")

    # --- fetch ---

    @parameterized.expand([(429,), (500,), (503,)])
    def test_fetch_raises_retryable_on_transient_statuses(self, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(DatahubRetryableError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    @parameterized.expand([(400,), (401,), (403,), (404,)])
    def test_fetch_raises_http_error_on_permanent_statuses(self, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(requests.HTTPError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    def test_fetch_streams_and_parses_capped_json(self) -> None:
        # stream=True keeps a hostile unbounded body from being buffered at request time; the
        # body is then read under a cap and JSON-parsed. Dropping either regresses the SSRF/OOM
        # guard, so pin both here.
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"entities": [{"urn": "u1"}]})
        result = _fetch_unwrapped(session, "http://url", None, MagicMock())
        assert result == {"entities": [{"urn": "u1"}]}
        assert session.get.call_args.kwargs["stream"] is True

    def test_read_capped_bytes_rejects_oversized_body(self) -> None:
        # A body larger than the cap must raise rather than buffer the whole thing.
        response = _mock_response(200, raw_body=b"x" * 11)
        with pytest.raises(DatahubResponseTooLargeError):
            datahub._read_capped_bytes(response, max_bytes=10)

    @parameterized.expand([(301,), (302,), (307,)])
    def test_fetch_refuses_redirects(self, status_code: int) -> None:
        # The session never follows redirects — a 3xx would move the sync off the validated
        # host (SSRF), so it must fail rather than be treated as an empty page.
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(DatahubHostNotAllowedError):
            _fetch_unwrapped(session, "http://url", None, MagicMock())

    # --- get_rows ---

    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[Any, Any],
        endpoint: str = "datasets",
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        """Run get_rows with a fake _fetch keyed by the `scrollId` param (None = first page)."""
        calls: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, params: Optional[dict], logger: Any) -> Any:
            calls.append({"url": url, "params": params})
            page = pages[params.get("scrollId") if params else None]
            if isinstance(page, Exception):
                raise page
            return page

        monkeypatch.setattr(datahub, "_fetch", fake_fetch)
        monkeypatch.setattr(datahub, "make_tracked_session", lambda **kwargs: MagicMock())
        monkeypatch.setattr(datahub, "_check_host", lambda instance_url, team_id: None)

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

    def test_scroll_walks_pages_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            None: {"scrollId": "cursor-1", "entities": [{"urn": "u1"}, {"urn": "u2"}]},
            "cursor-1": {"entities": [{"urn": "u3"}]},
        }
        rows, calls = self._collect(manager, monkeypatch, pages)

        assert [r["urn"] for r in rows] == ["u1", "u2", "u3"]
        assert calls[0]["url"] == f"{BASE_URL}/openapi/v3/entity/dataset"
        # Stable ascending urn sort keeps page boundaries fixed while scrolling.
        assert all(
            c["params"]["query"] == "*"
            and c["params"]["count"] == PAGE_SIZE
            and c["params"]["sortCriteria"] == "urn"
            and c["params"]["sortOrder"] == "ASCENDING"
            for c in calls
        )
        assert [c["params"].get("scrollId") for c in calls] == [None, "cursor-1"]
        # State is saved once — after the first page yielded, pointing at the next cursor.
        assert [s.scroll_id for s in manager.saved] == ["cursor-1"]

    def test_scroll_stops_on_empty_page_even_with_cursor(self, monkeypatch: Any) -> None:
        # Guard against a server that echoes a cursor forever: an empty page terminates the sweep.
        manager = _FakeResumableManager()
        rows, calls = self._collect(manager, monkeypatch, {None: {"scrollId": "next", "entities": []}})
        assert rows == []
        assert len(calls) == 1
        assert manager.saved == []

    def test_scroll_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(DatahubResumeConfig(scroll_id="cursor-9"))
        pages = {"cursor-9": {"entities": [{"urn": "u9"}]}}
        rows, calls = self._collect(manager, monkeypatch, pages)
        assert [r["urn"] for r in rows] == ["u9"]
        assert [c["params"].get("scrollId") for c in calls] == ["cursor-9"]

    # pytest.mark.parametrize (not parameterized.expand) because the test also needs the
    # monkeypatch fixture, which parameterized's wrapper doesn't forward.
    @pytest.mark.parametrize("status_code", [400, 404, 410])
    def test_stale_resumed_cursor_restarts_from_scratch(self, status_code: int, monkeypatch: Any) -> None:
        # Scroll contexts are server-side and expire; a rejected saved cursor must restart the
        # sweep (merge dedupes re-pulled rows) instead of wedging the sync.
        manager = _FakeResumableManager(DatahubResumeConfig(scroll_id="stale"))
        error = requests.HTTPError("rejected", response=_mock_response(status_code))
        pages = {
            "stale": error,
            None: {"entities": [{"urn": "u1"}]},
        }
        rows, calls = self._collect(manager, monkeypatch, pages)
        assert [r["urn"] for r in rows] == ["u1"]
        assert [c["params"].get("scrollId") for c in calls] == ["stale", None]
        assert manager.cleared is True

    def test_stale_cursor_mid_sweep_is_not_swallowed(self, monkeypatch: Any) -> None:
        # Only a cursor loaded from resume state gets the restart treatment — a 4xx on a cursor
        # the server just handed us is a real error and must fail the sync.
        manager = _FakeResumableManager()
        error = requests.HTTPError("rejected", response=_mock_response(400))
        pages = {
            None: {"scrollId": "cursor-1", "entities": [{"urn": "u1"}]},
            "cursor-1": error,
        }
        with pytest.raises(requests.HTTPError):
            self._collect(manager, monkeypatch, pages)

    def test_get_rows_blocks_unsafe_hosts(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        with pytest.raises(DatahubHostNotAllowedError):
            list(
                get_rows(
                    instance_url="https://10.0.0.1",
                    api_token=TOKEN,
                    endpoint="datasets",
                    team_id=1,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    def test_get_rows_blocks_ambiguous_url(self) -> None:
        with pytest.raises(DatahubHostNotAllowedError):
            list(
                get_rows(
                    instance_url="https://169.254.169.254\\@datahub.example.com",
                    api_token=TOKEN,
                    endpoint="datasets",
                    team_id=1,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    # --- SourceResponse assembly ---

    @parameterized.expand([("datasets",), ("users",), ("tags",)])
    def test_datahub_source_uses_urn_primary_key(self, endpoint: str) -> None:
        response = datahub_source(
            instance_url=BASE_URL,
            api_token=TOKEN,
            endpoint=endpoint,
            team_id=1,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == ["urn"]

    # --- credential validation ---

    def _validate(self, monkeypatch: Any, response: MagicMock, schema_name: Optional[str] = None) -> tuple:
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(datahub, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (True, None))
        return validate_credentials(BASE_URL, TOKEN, schema_name=schema_name, team_id=1)

    def test_validate_credentials_success(self, monkeypatch: Any) -> None:
        assert self._validate(monkeypatch, _mock_response(200, {"entities": []})) == (True, None)

    def test_validate_credentials_invalid_token(self, monkeypatch: Any) -> None:
        # DataHub 401s carry an empty body, so the message must stand on its own.
        valid, message = self._validate(monkeypatch, _mock_response(401, None))
        assert valid is False
        assert message is not None and "Invalid DataHub access token" in message

    def test_validate_credentials_accepts_403_at_source_create(self, monkeypatch: Any) -> None:
        # A valid token may lack the view privilege for the probe entity; source creation must
        # still go through, and per-schema syncs surface their own permission errors.
        assert self._validate(monkeypatch, _mock_response(403, {"message": "denied"})) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self, monkeypatch: Any) -> None:
        valid, message = self._validate(monkeypatch, _mock_response(403, {"message": "denied"}), schema_name="users")
        assert valid is False
        assert message == "denied"

    def test_validate_credentials_scoped_probe_targets_schema_entity(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(200, {"entities": []})
        monkeypatch.setattr(datahub, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (True, None))
        validate_credentials(BASE_URL, TOKEN, schema_name="users", team_id=1)
        assert session.get.call_args.args[0] == f"{BASE_URL}/openapi/v3/entity/corpuser"

    def test_validate_credentials_rejects_redirects(self, monkeypatch: Any) -> None:
        # A redirect could bounce the probe to an internal address, defeating the host check.
        valid, _ = self._validate(monkeypatch, _mock_response(200, {}, is_redirect=True))
        assert valid is False

    def test_validate_credentials_rejects_unsafe_host(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        valid, message = validate_credentials("https://10.0.0.1", TOKEN, team_id=1)
        assert valid is False
        assert message == "blocked"

    @parameterized.expand(
        [
            ("blank", "   "),
            ("bad_scheme", "ftp://datahub.example.com"),
            # Parser-differential SSRF guards: urlparse and urllib3 disagree on where the
            # authority ends for backslash/userinfo URLs, so validation could approve one host
            # while requests connects to another.
            ("userinfo", "https://169.254.169.254@datahub.example.com"),
            ("backslash", "https://169.254.169.254\\@datahub.example.com"),
            ("encoded_backslash", "https://169.254.169.254%5C@datahub.example.com"),
        ]
    )
    def test_validate_credentials_rejects_malformed_or_ambiguous_urls(self, _name: str, raw_url: str) -> None:
        valid, message = validate_credentials(raw_url, TOKEN, team_id=1)
        assert valid is False
        assert message == "Invalid DataHub instance URL"

    @parameterized.expand(
        [
            # The token rides in the Authorization header, so plaintext http is rejected on cloud
            # (public egress) but allowed off cloud (self-hosted controls its own network path).
            ("http_on_cloud", True, "http://datahub.example.com", None),
            ("http_off_cloud", False, "http://datahub.example.com", "datahub.example.com"),
            ("https_on_cloud", True, "https://datahub.example.com", "datahub.example.com"),
        ]
    )
    def test_validated_hostname_requires_https_only_on_cloud(
        self, _name: str, cloud: bool, url: str, expected: Optional[str]
    ) -> None:
        with patch.object(datahub, "is_cloud", return_value=cloud):
            assert datahub._validated_hostname(url) == expected

    def test_validate_credentials_handles_connection_errors(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(datahub, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (True, None))
        valid, message = validate_credentials(BASE_URL, TOKEN, team_id=1)
        assert valid is False
        assert message is not None and "Could not connect to DataHub" in message

    # --- per-endpoint permissions ---

    @parameterized.expand(
        [
            # Transient failures are not permission problems — they must not flag the table.
            ("server_error", 500, None),
            ("throttled", 429, None),
            ("invalid_token", 401, "Invalid DataHub access token"),
            ("denied_with_message", 403, "no view privilege"),
        ]
    )
    def test_check_endpoint_permissions_status_mapping(
        self, _name: str, status_code: int, expected: Optional[str]
    ) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code, {"message": "no view privilege"})
        with (
            patch.object(datahub, "make_tracked_session", lambda **kwargs: session),
            patch.object(datahub, "_is_host_safe", lambda host, team_id: (True, None)),
        ):
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["datasets"], team_id=1)
        assert result["datasets"] == expected

    def test_check_endpoint_permissions_treats_network_blips_as_reachable(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(datahub, "make_tracked_session", lambda **kwargs: session)
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (True, None))
        assert check_endpoint_permissions(BASE_URL, TOKEN, ["datasets"], team_id=1) == {"datasets": None}

    def test_check_endpoint_permissions_blocks_unsafe_host_for_all_endpoints(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        result = check_endpoint_permissions("https://10.0.0.1", TOKEN, ["datasets", "users"], team_id=1)
        assert result == {"datasets": "blocked", "users": "blocked"}

    def test_check_endpoint_permissions_rejects_ambiguous_url_for_all_endpoints(self) -> None:
        result = check_endpoint_permissions(
            "https://169.254.169.254\\@datahub.example.com", TOKEN, ["datasets", "users"], team_id=1
        )
        assert result == {"datasets": "Invalid DataHub instance URL", "users": "Invalid DataHub instance URL"}
