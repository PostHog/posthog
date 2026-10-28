import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub import datahub
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.datahub import (
    PAGE_SIZE,
    DatahubHostNotAllowedError,
    DatahubResponseTooLargeError,
    DatahubResumeConfig,
    DatahubRetryableError,
    DatahubTimeseriesScrollUnsupportedError,
    DatahubTooManyPagesError,
    _extract_page,
    _timeseries_row_id,
    check_endpoint_permissions,
    normalize_instance_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source import DatahubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datahub import (
    DatahubSourceConfig,
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


class TestDatahub:
    @staticmethod
    def _driver(instance_url: str = BASE_URL) -> SourceDriver:
        return SourceDriver(DatahubSource(), DatahubSourceConfig(instance_url=instance_url, api_token=TOKEN))

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

    # --- scroll envelope extraction ---

    @parameterized.expand(
        [
            ("page_with_cursor", "entities", {"scrollId": "abc", "entities": [{"urn": "u1"}]}, [{"urn": "u1"}], "abc"),
            ("final_page", "entities", {"entities": [{"urn": "u2"}]}, [{"urn": "u2"}], None),
            # An empty final page may omit the items key entirely — that's a valid empty result.
            ("empty_without_key", "entities", {}, [], None),
            # An empty-string scrollId must not be followed as a cursor.
            ("empty_cursor", "entities", {"scrollId": "", "entities": []}, [], None),
            # The timeseries endpoint wraps its rows under `results` instead of `entities`.
            ("timeseries_page", "results", {"scrollId": "abc", "results": [{"urn": "u1"}]}, [{"urn": "u1"}], "abc"),
            ("timeseries_final_page", "results", {"results": [{"urn": "u2"}]}, [{"urn": "u2"}], None),
            # An entity envelope read with the timeseries key must not silently yield entity rows.
            ("wrong_key_reads_empty", "results", {"entities": [{"urn": "u1"}]}, [], None),
        ]
    )
    def test_extract_page(
        self, _name: str, items_key: str, payload: Any, expected_rows: list[dict], expected_cursor: str | None
    ) -> None:
        assert _extract_page(payload, "http://url", items_key) == (expected_rows, expected_cursor)

    @parameterized.expand(
        [
            ("bare_list", "entities", [{"urn": "u1"}]),
            ("entities_not_a_list", "entities", {"entities": {"urn": "u1"}}),
            ("results_not_a_list", "results", {"results": {"urn": "u1"}}),
        ]
    )
    def test_extract_page_rejects_unexpected_payloads(self, _name: str, items_key: str, payload: Any) -> None:
        with pytest.raises(DatahubRetryableError):
            _extract_page(payload, "http://url", items_key)

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

    def test_scroll_aborts_past_page_budget(self, monkeypatch: Any) -> None:
        # A hostile instance can echo a fresh non-empty page and cursor forever; the empty-page
        # guard never fires, so the sweep must abort at the page budget instead of writing rows
        # until the activity times out.
        monkeypatch.setattr(datahub, "MAX_PAGES_PER_SWEEP", 3)

        def endless_page(request: RecordedRequest) -> ScriptedResponse:
            cursor = request.param("scrollId")
            n = int(cursor) + 1 if cursor else 1
            return ScriptedResponse(json={"scrollId": str(n), "entities": [{"urn": f"u{n}"}]})

        result = self._driver().run("datasets", endless_page)

        # Pages up to the budget are still yielded; the cursor past the budget is never persisted,
        # so a resume restarts from the last good page rather than walking deeper into the stream.
        assert isinstance(result.raised, DatahubTooManyPagesError)
        assert [r["urn"] for r in result.rows] == ["u1", "u2", "u3"]
        assert result.params("scrollId") == [None, "1", "2"]
        assert result.saved_states == [DatahubResumeConfig(scroll_id="1"), DatahubResumeConfig(scroll_id="2")]
        assert result.final_state == DatahubResumeConfig(scroll_id="2")

    @pytest.mark.parametrize("status_code", [400, 404, 410])
    def test_stale_resumed_cursor_restarts_from_scratch(self, status_code: int) -> None:
        # Scroll contexts are server-side and expire; a rejected saved cursor must restart the
        # sweep (merge dedupes re-pulled rows) instead of wedging the sync.
        result = self._driver().run(
            "datasets",
            [ScriptedResponse(status=status_code), ScriptedResponse(json={"entities": [{"urn": "u1"}]})],
            resume_state=DatahubResumeConfig(scroll_id="stale"),
        )
        assert result.raised is None
        assert [r["urn"] for r in result.rows] == ["u1"]
        assert result.params("scrollId") == ["stale", None]
        assert result.final_state is None

    def test_stale_cursor_mid_sweep_is_not_swallowed(self) -> None:
        # Only a cursor loaded from resume state gets the restart treatment — a 4xx on a cursor
        # the server just handed us is a real error and must fail the sync.
        result = self._driver().run(
            "datasets",
            [
                ScriptedResponse(json={"scrollId": "cursor-1", "entities": [{"urn": "u1"}]}),
                ScriptedResponse(status=400),
            ],
        )
        assert isinstance(result.raised, requests.HTTPError)
        assert result.params("scrollId") == [None, "cursor-1"]
        assert result.rows == [{"urn": "u1"}]
        assert result.saved_states == [DatahubResumeConfig(scroll_id="cursor-1")]
        assert result.committed_states == []
        assert result.final_state is None

    def test_get_rows_blocks_unsafe_hosts(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(datahub, "_is_host_safe", lambda host, team_id: (False, "blocked"))
        result = self._driver("https://10.0.0.1").run("datasets", [])
        assert isinstance(result.raised, DatahubHostNotAllowedError)
        assert result.requests == []

    def test_get_rows_blocks_ambiguous_url(self) -> None:
        result = self._driver("https://169.254.169.254\\@datahub.example.com").run("datasets", [])
        assert isinstance(result.raised, DatahubHostNotAllowedError)
        assert result.requests == []

    # --- timeseries aspect endpoints ---

    @pytest.mark.parametrize("last_value", [1500, None])
    def test_timeseries_sweep_windows_every_page(self, last_value: Optional[int]) -> None:
        # The cursor is a stateless search_after token, so the server only keeps the time bound
        # while we keep sending it. Drop it after page one and an incremental sync walks back
        # through the whole history instead of stopping at the watermark. A full refresh must send
        # no bound at all.
        result = self._driver().run(
            "dataset_profiles",
            [
                ScriptedResponse(json={"scrollId": "cursor-1", "results": [{"urn": "u1", "timestampMillis": 3000}]}),
                ScriptedResponse(json={"results": [{"urn": "u1", "timestampMillis": 2000}]}),
            ],
            should_use_incremental_field=last_value is not None,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [r["timestampMillis"] for r in result.rows] == [3000, 2000]
        assert result.paths == ["/openapi/v2/timeseries/dataset/datasetProfile"] * 2
        assert result.params("startTimeMillis") == [str(last_value) if last_value is not None else None] * 2
        assert result.params("count") == [str(PAGE_SIZE)] * 2
        # The endpoint takes no sort parameter, so none of the entity scroll's sort params apply.
        assert result.params("sortCriteria") == [None, None]
        assert result.saved_states == [DatahubResumeConfig(scroll_id="cursor-1")]

    def test_timeseries_full_page_without_a_cursor_fails_instead_of_truncating(self, monkeypatch: Any) -> None:
        # DataHub before v1.4.0 never returns a scroll cursor from the timeseries endpoint, so the
        # sweep would end after one page and write a silently truncated table. A fixed instance
        # always pairs a full page with a cursor, so this shape only happens on an old one.
        monkeypatch.setattr(datahub, "PAGE_SIZE", 2)
        result = self._driver().run(
            "dataset_profiles",
            [
                ScriptedResponse(
                    json={"results": [{"urn": "u1", "timestampMillis": 3000}, {"urn": "u2", "timestampMillis": 2000}]}
                )
            ],
        )
        assert isinstance(result.raised, DatahubTimeseriesScrollUnsupportedError)
        assert result.rows == []

    @parameterized.expand(
        [
            # urn plus timestamp alone is not unique: one dataset can carry a daily and an hourly
            # bucket, one row per partition, and separately ingested events with distinct ids. A
            # key that collapses those loses rows and makes every later merge multi-match.
            ("event_granularity", {"event": {"eventGranularity": {"unit": "HOUR", "multiple": 1}}}, False),
            ("partition_spec", {"event": {"partitionSpec": {"partition": "2026-09-01"}}}, False),
            ("message_id", {"messageId": "m2"}, False),
            # Metric values stay out of the key, so a bucket the instance restates merges onto
            # itself rather than landing twice.
            ("restated_metric", {"event": {"rowCount": 11}}, True),
        ]
    )
    def test_timeseries_row_id_keys_on_identity_not_metrics(
        self, _name: str, delta: dict[str, Any], expect_same: bool
    ) -> None:
        base: dict[str, Any] = {"urn": "u1", "timestampMillis": 3000, "messageId": "m1", "event": {"rowCount": 10}}
        same = _timeseries_row_id(base) == _timeseries_row_id({**base, **delta})
        assert same is expect_same

    # --- SourceResponse assembly ---

    @parameterized.expand(
        [
            ("datasets", ["urn"], "asc"),
            ("users", ["urn"], "asc"),
            ("tags", ["urn"], "asc"),
            ("schema_fields", ["urn"], "asc"),
            # The timeseries endpoint always returns newest first and has no sort parameter, so a
            # response claiming "asc" would checkpoint the watermark to now after the first batch.
            ("dataset_profiles", ["id"], "desc"),
            ("assertion_run_events", ["id"], "desc"),
        ]
    )
    def test_datahub_source_primary_key_and_sort_mode(
        self, endpoint: str, expected_keys: list[str], expected_sort: str
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json={"results": [], "entities": []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort

    # --- credential validation ---

    def test_validate_credentials_invalid_token(self) -> None:
        # DataHub 401s carry an empty body, so the message must stand on its own.
        with scripted_network([ScriptedResponse(status=401)]) as network:
            valid, message = validate_credentials(BASE_URL, TOKEN)
        assert valid is False
        assert message is not None and "Invalid DataHub access token" in message
        assert network.requests_log[0].path == "/openapi/v3/entity/dataPlatform"
        assert network.requests_log[0].headers["authorization"] == f"Bearer {TOKEN}"
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == (TOKEN,)

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may lack the view privilege for the probe entity; source creation must
        # still go through, and per-schema syncs surface their own permission errors.
        with scripted_network([ScriptedResponse(status=403, json={"message": "denied"})]):
            assert validate_credentials(BASE_URL, TOKEN) == (True, None)

    def test_validate_credentials_rejects_403_for_scoped_probe(self) -> None:
        with scripted_network([ScriptedResponse(status=403, json={"message": "denied"})]):
            valid, message = validate_credentials(BASE_URL, TOKEN, schema_name="users")
        assert valid is False
        assert message == "denied"

    def test_validate_credentials_scoped_probe_targets_schema_entity(self) -> None:
        with scripted_network([ScriptedResponse(json={"entities": []})]) as network:
            assert validate_credentials(BASE_URL, TOKEN, schema_name="users") == (True, None)
        assert network.requests_log[0].url.startswith(f"{BASE_URL}/openapi/v3/entity/corpuser?")
        assert network.requests_log[0].param("count") == "1"

    def test_validate_credentials_rejects_redirects(self) -> None:
        # A redirect could bounce the probe to an internal address, defeating the host check.
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://other.example.com"})]
        ) as network:
            valid, _ = validate_credentials(BASE_URL, TOKEN)
        assert valid is False
        assert len(network.requests_log) == 1

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

    def test_validate_credentials_handles_connection_errors(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            valid, message = validate_credentials(BASE_URL, TOKEN)
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
        with scripted_network(
            always(ScriptedResponse(status=status_code, json={"message": "no view privilege"}))
        ) as network:
            result = check_endpoint_permissions(BASE_URL, TOKEN, ["datasets"], team_id=1)
        assert result["datasets"] == expected
        assert {request.path for request in network.requests_log} == {"/openapi/v3/entity/dataset"}

    def test_check_endpoint_permissions_treats_network_blips_as_reachable(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
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
