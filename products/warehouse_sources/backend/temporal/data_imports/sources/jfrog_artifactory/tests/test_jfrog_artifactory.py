import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory import jfrog_artifactory
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.jfrog_artifactory import (
    RESPONSE_LIMIT_ERROR,
    JfrogArtifactoryResponseTooLargeError,
    JfrogArtifactoryResumeConfig,
    _format_aql_datetime,
    _request,
    _strip_domain_prefix,
    build_aql_query,
    get_rows,
    jfrog_artifactory_source,
    normalize_base_url,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    AQL_PAGE_SIZE,
    JFROG_ARTIFACTORY_ENDPOINTS,
)


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("bare_host", "acme.jfrog.io", "https://acme.jfrog.io"),
            ("https_url", "https://acme.jfrog.io", "https://acme.jfrog.io"),
            ("trailing_slash", "https://acme.jfrog.io/", "https://acme.jfrog.io"),
            ("artifactory_suffix", "https://acme.jfrog.io/artifactory", "https://acme.jfrog.io"),
            ("artifactory_suffix_slash", "acme.jfrog.io/artifactory/", "https://acme.jfrog.io"),
            (
                "self_hosted_with_port",
                "https://artifactory.internal.example.com:8082",
                "https://artifactory.internal.example.com:8082",
            ),
            ("whitespace", "  acme.jfrog.io  ", "https://acme.jfrog.io"),
        ]
    )
    def test_valid_urls(self, _name: str, value: str, expected: str) -> None:
        assert normalize_base_url(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("path", "https://acme.jfrog.io/some/path"),
            ("userinfo_injection", "https://acme.jfrog.io@evil.com"),
            ("backslash_injection", "https://127.0.0.1\\@acme.jfrog.io"),
            ("encoded_backslash", "https://127.0.0.1%5C@acme.jfrog.io"),
            ("bad_scheme", "ftp://acme.jfrog.io"),
        ]
    )
    def test_invalid_urls_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(value)


class TestFormatAqlDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, 123000, tzinfo=UTC), "2026-03-04T02:58:14.123+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14.000+00:00", "2026-03-04T02:58:14.000+00:00"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_aql_datetime(value) == expected


class TestBuildAqlQuery:
    def test_incremental_query_filters_and_sorts_on_cursor_field(self) -> None:
        query = build_aql_query(
            JFROG_ARTIFACTORY_ENDPOINTS["artifacts"],
            incremental_field="modified",
            incremental_filter_value="2026-03-04T02:58:14.000+00:00",
            offset=2000,
        )
        assert query.startswith('items.find({"modified": {"$gt": "2026-03-04T02:58:14.000+00:00"}})')
        assert '.sort({"$asc": ["modified"]})' in query
        assert query.endswith(f".offset(2000).limit({AQL_PAGE_SIZE})")

    def test_full_refresh_query_has_no_criteria_but_stable_sort(self) -> None:
        query = build_aql_query(JFROG_ARTIFACTORY_ENDPOINTS["artifacts"])
        assert query.startswith("items.find()")
        assert '.sort({"$asc": ["modified"]})' in query
        assert f".offset(0).limit({AQL_PAGE_SIZE})" in query

    def test_user_chosen_cursor_field_drives_filter_and_sort(self) -> None:
        query = build_aql_query(
            JFROG_ARTIFACTORY_ENDPOINTS["artifacts"],
            incremental_field="created",
            incremental_filter_value="2026-03-04T00:00:00.000+00:00",
        )
        assert '"created": {"$gt"' in query
        assert '.sort({"$asc": ["created"]})' in query

    def test_builds_query_uses_builds_domain(self) -> None:
        query = build_aql_query(JFROG_ARTIFACTORY_ENDPOINTS["builds"], limit=1)
        assert query.startswith("builds.find()")
        assert '"name", "number", "created"' in query
        assert query.endswith(".offset(0).limit(1)")

    def test_sort_field_always_included_in_output_fields(self) -> None:
        # AQL rejects .sort() on fields absent from a primary-domain .include() list.
        for config in JFROG_ARTIFACTORY_ENDPOINTS.values():
            if config.kind != "aql":
                continue
            assert config.default_incremental_field in config.aql_fields
            for incremental_field in config.incremental_fields:
                assert incremental_field["field"] in config.aql_fields


class TestStripDomainPrefix:
    @parameterized.expand(
        [
            ("prefixed_builds", {"build.name": "b", "build.number": "1"}, "builds", {"name": "b", "number": "1"}),
            ("bare_builds", {"name": "b", "number": "1"}, "builds", {"name": "b", "number": "1"}),
            ("bare_items", {"repo": "r", "path": "p", "name": "n"}, "items", {"repo": "r", "path": "p", "name": "n"}),
        ]
    )
    def test_strip(self, _name: str, item: dict, domain: str, expected: dict) -> None:
        assert _strip_domain_prefix(item, domain) == expected


class _FakeResumableManager:
    def __init__(self, state: JfrogArtifactoryResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JfrogArtifactoryResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JfrogArtifactoryResumeConfig | None:
        return self._state

    def save_state(self, data: JfrogArtifactoryResumeConfig) -> None:
        self.saved.append(data)


def _patch_aql(monkeypatch: Any, pages: dict[str, dict]) -> list[str]:
    queries: list[str] = []

    def fake_post_aql(session: Any, base_url: str, access_token: str, query: str, logger: Any) -> dict:
        queries.append(query)
        return pages[query]

    monkeypatch.setattr(jfrog_artifactory, "_post_aql", fake_post_aql)
    return queries


def _collect(manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        base_url="https://acme.jfrog.io",
        access_token="token",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _artifact(name: str) -> dict:
    return {"repo": "libs", "path": "com/acme", "name": name, "modified": "2026-01-01T00:00:00.000+00:00"}


class TestGetRowsAql:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        full_page = [_artifact(f"a{i}.jar") for i in range(AQL_PAGE_SIZE)]
        config = JFROG_ARTIFACTORY_ENDPOINTS["artifacts"]
        page_1 = build_aql_query(config, offset=0)
        page_2 = build_aql_query(config, offset=AQL_PAGE_SIZE)
        queries = _patch_aql(
            monkeypatch,
            {
                page_1: {"results": full_page, "range": {"start_pos": 0, "end_pos": AQL_PAGE_SIZE}},
                page_2: {"results": [_artifact("last.jar")], "range": {"start_pos": AQL_PAGE_SIZE}},
            },
        )

        rows = _collect(_FakeResumableManager(), endpoint="artifacts")

        assert len(rows) == AQL_PAGE_SIZE + 1
        assert queries == [page_1, page_2]

    def test_saves_resume_state_after_each_yielded_page(self, monkeypatch: Any) -> None:
        full_page = [_artifact(f"a{i}.jar") for i in range(AQL_PAGE_SIZE)]
        config = JFROG_ARTIFACTORY_ENDPOINTS["artifacts"]
        _patch_aql(
            monkeypatch,
            {
                build_aql_query(config, offset=0): {"results": full_page},
                build_aql_query(config, offset=AQL_PAGE_SIZE): {"results": [_artifact("last.jar")]},
            },
        )
        manager = _FakeResumableManager()

        _collect(manager, endpoint="artifacts")

        # State is saved only while more pages remain, never on the final short page.
        assert manager.saved == [JfrogArtifactoryResumeConfig(next_offset=AQL_PAGE_SIZE, incremental_filter_value=None)]

    def test_resumes_from_saved_offset_with_original_filter(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["artifacts"]
        saved_filter = "2026-01-01T00:00:00.000+00:00"
        resume_query = build_aql_query(
            config, incremental_field="modified", incremental_filter_value=saved_filter, offset=AQL_PAGE_SIZE
        )
        queries = _patch_aql(monkeypatch, {resume_query: {"results": [_artifact("resumed.jar")]}})

        rows = _collect(
            _FakeResumableManager(
                JfrogArtifactoryResumeConfig(next_offset=AQL_PAGE_SIZE, incremental_filter_value=saved_filter)
            ),
            endpoint="artifacts",
            should_use_incremental_field=True,
            # The DB watermark has advanced past the saved filter; resuming must reuse the saved
            # value or the offset would point at a different slice of the result set.
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
            incremental_field="modified",
        )

        assert [r["name"] for r in rows] == ["resumed.jar"]
        assert queries == [resume_query]

    def test_incremental_filter_built_from_db_watermark(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["artifacts"]
        query = build_aql_query(
            config,
            incremental_field="modified",
            incremental_filter_value="2026-03-04T02:58:14.000+00:00",
            offset=0,
        )
        queries = _patch_aql(monkeypatch, {query: {"results": [_artifact("new.jar")]}})

        _collect(
            _FakeResumableManager(),
            endpoint="artifacts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="modified",
        )

        assert queries == [query]

    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["artifacts"]
        _patch_aql(monkeypatch, {build_aql_query(config, offset=0): {"results": []}})

        assert _collect(_FakeResumableManager(), endpoint="artifacts") == []

    def test_builds_rows_normalized_from_prefixed_keys(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["builds"]
        _patch_aql(
            monkeypatch,
            {
                build_aql_query(config, offset=0): {
                    "results": [{"build.name": "app", "build.number": "42", "build.created": "2026-01-01"}]
                }
            },
        )

        rows = _collect(_FakeResumableManager(), endpoint="builds")

        assert rows == [{"name": "app", "number": "42", "created": "2026-01-01"}]


class TestGetRowsRest:
    def test_repositories_returns_bare_array(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            jfrog_artifactory,
            "_get_json",
            lambda session, base_url, access_token, path, logger: [{"key": "libs-release", "type": "LOCAL"}],
        )

        rows = _collect(_FakeResumableManager(), endpoint="repositories")

        assert rows == [{"key": "libs-release", "type": "LOCAL"}]

    def test_storage_summary_extracts_repositories_summary_list(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            jfrog_artifactory,
            "_get_json",
            lambda session, base_url, access_token, path, logger: {
                "binariesSummary": {"binariesCount": "100"},
                "repositoriesSummaryList": [{"repoKey": "libs-release", "filesCount": 10}],
            },
        )

        rows = _collect(_FakeResumableManager(), endpoint="storage_summary")

        assert rows == [{"repoKey": "libs-release", "filesCount": 10}]

    def test_storage_summary_missing_key_yields_nothing(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            jfrog_artifactory,
            "_get_json",
            lambda session, base_url, access_token, path, logger: {"binariesSummary": {}},
        )

        assert _collect(_FakeResumableManager(), endpoint="storage_summary") == []


class TestSourceResponse:
    @parameterized.expand(
        [
            ("repositories", ["key"], None),
            ("artifacts", ["repo", "path", "name"], "created"),
            ("builds", ["name", "number"], "created"),
            ("storage_summary", ["repoKey"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = jfrog_artifactory_source(
            base_url="https://acme.jfrog.io",
            access_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]


class _FakeSession:
    def __init__(self, status_code: int = 200) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        self._status_code = status_code

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None, stream: bool = False) -> MagicMock:
        self.requests.append(("GET", url, None))
        return MagicMock(status_code=self._status_code)

    def post(
        self,
        url: str,
        headers: dict | None = None,
        data: str | None = None,
        timeout: int | None = None,
        stream: bool = False,
    ) -> MagicMock:
        self.requests.append(("POST", url, data))
        return MagicMock(status_code=self._status_code)


class TestProbeEndpoint:
    def test_token_probe_gets_repositories(self, monkeypatch: Any) -> None:
        session = _FakeSession()
        monkeypatch.setattr(jfrog_artifactory, "_get_session", lambda access_token: session)

        ok, status = probe_endpoint("https://acme.jfrog.io", "token")

        assert (ok, status) == (True, 200)
        assert session.requests == [("GET", "https://acme.jfrog.io/artifactory/api/repositories", None)]

    def test_aql_endpoint_probe_posts_single_row_query(self, monkeypatch: Any) -> None:
        session = _FakeSession(status_code=403)
        monkeypatch.setattr(jfrog_artifactory, "_get_session", lambda access_token: session)

        ok, status = probe_endpoint("https://acme.jfrog.io", "token", endpoint="builds")

        assert (ok, status) == (False, 403)
        method, url, data = session.requests[0]
        assert (method, url) == ("POST", "https://acme.jfrog.io/artifactory/api/search/aql")
        assert data is not None and data.startswith("builds.find()") and data.endswith(".limit(1)")

    def test_transport_error_returns_none_status(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("nope")
        monkeypatch.setattr(jfrog_artifactory, "_get_session", lambda access_token: session)

        assert probe_endpoint("https://acme.jfrog.io", "token") == (False, None)

    def test_malformed_url_raises(self) -> None:
        with pytest.raises(ValueError):
            probe_endpoint("https://acme.jfrog.io/evil@path", "token")


def _streamed_response(status_code: int = 200, chunks: list[bytes] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.iter_content.return_value = chunks if chunks is not None else [b"{}"]
    return response


class TestRequestBodyCap:
    def test_decodes_streamed_body(self) -> None:
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[b'{"a":', b"1}"])

        result = _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert result == {"a": 1}
        # stream=True keeps a hostile host's body off the wire until we read it under the cap.
        assert session.request.call_args.kwargs["stream"] is True

    def test_over_byte_cap_raises_non_retryable(self) -> None:
        # A hostile/self-hosted host could stream an unbounded (or highly compressed) body and OOM a
        # shared worker. The read must abort past the byte cap before parsing JSON, with a
        # non-retryable error (retrying can't shrink the body) — so session.request runs exactly once.
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[b"aaaa", b"aaaa"])

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_RESPONSE_BYTES", 4)
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert session.request.call_count == 1

    def test_over_container_cap_raises_non_retryable(self) -> None:
        # A compact body of many `{}`/`[]` stays under the byte cap but amplifies into millions of
        # Python objects on json.loads. The container-count guard must reject it before parsing,
        # non-retryably (a second identical body wouldn't parse any smaller).
        body = b"[" + b"{}," * 60 + b"{}]"  # 61 objects nested in 1 array
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[body])

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_JSON_CONTAINERS", 10)
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert session.request.call_count == 1

    def test_body_drip_past_deadline_is_aborted(self) -> None:
        # A host that blocks mid-body (never filling a chunk) keeps requests' per-read timeout from
        # firing. The out-of-band deadline must close the response to unblock the read and abort with
        # a non-retryable error rather than leaving the worker hung.
        released = threading.Event()

        def _blocking_iter(chunk_size: int | None = None) -> Any:
            yield b'{"a":'
            released.wait(timeout=5)
            raise requests.exceptions.ChunkedEncodingError("connection closed")

        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.iter_content.side_effect = _blocking_iter
        response.close.side_effect = lambda: released.set()

        session = MagicMock()
        session.request.return_value = response

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_TRANSFER_SECONDS", 0.05)
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        response.close.assert_called()
        assert session.request.call_count == 1

    def test_header_drip_past_deadline_is_aborted(self) -> None:
        # A host that dribbles response *header* bytes keeps session.request blocked before a response
        # object even exists, so a body-only guard would never fire. The request-level deadline must
        # abort this too, freeing the worker.
        started = threading.Event()

        def _blocking_request(*args: Any, **kwargs: Any) -> Any:
            started.set()
            threading.Event().wait(timeout=5)  # server never finishes sending headers
            raise requests.ConnectionError("connection closed")

        session = MagicMock()
        session.request.side_effect = _blocking_request

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_TRANSFER_SECONDS", 0.05)
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert started.is_set()
        assert session.request.call_count == 1

    def test_request_slot_bound_rejects_when_saturated(self) -> None:
        # Threads pinned by a header drip can't be cancelled, so concurrency is bounded to stop a
        # hostile host accumulating threads/sockets without limit. With every slot held, a new
        # request is rejected before it opens an outbound connection.
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[b"{}"])

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "_request_slots", threading.BoundedSemaphore(1))
                mp.setattr(jfrog_artifactory, "MAX_TRANSFER_SECONDS", 0.05)
                jfrog_artifactory._request_slots.acquire()  # the only slot is held by an in-flight request
                try:
                    _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())
                finally:
                    jfrog_artifactory._request_slots.release()

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert session.request.call_count == 0
