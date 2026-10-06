import json
import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

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
    build_related_aql_query,
    build_xray_violations_request,
    flatten_related,
    get_rows,
    jfrog_artifactory_source,
    normalize_base_url,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    AQL_PAGE_SIZE,
    JFROG_ARTIFACTORY_ENDPOINTS,
    XRAY_PAGE_SIZE,
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
            if config.kind not in ("aql", "aql_related"):
                continue
            assert config.default_incremental_field in config.aql_fields
            for incremental_field in config.incremental_fields:
                assert incremental_field["field"].removeprefix(config.parent_field_prefix) in config.aql_fields

    def test_static_criteria_combined_with_incremental_filter(self) -> None:
        query = build_aql_query(
            JFROG_ARTIFACTORY_ENDPOINTS["artifact_statistics"],
            incremental_field="created",
            incremental_filter_value="2026-03-04T00:00:00.000+00:00",
        )
        assert query.startswith(
            'items.find({"stat.downloads": {"$gt": 0}, "created": {"$gt": "2026-03-04T00:00:00.000+00:00"}})'
        )
        # The parent page include stays primary-domain only, or AQL ignores sort/offset/limit.
        assert '.include("repo", "path", "name", "created")' in query

    def test_related_query_selects_chunk_without_pagination(self) -> None:
        query = build_related_aql_query(
            JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"],
            [{"name": "app", "number": "1", "created": "x"}, {"name": "app", "number": "2", "created": "y"}],
        )
        assert query.startswith(
            'builds.find({"$or": [{"name": "app", "number": "1"}, {"name": "app", "number": "2"}]})'
        )
        assert '"promotion.created"' in query
        assert ".sort(" not in query and ".offset(" not in query and ".limit(" not in query


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


class TestFlattenRelated:
    @parameterized.expand(
        [
            (
                "bare_nested_keys",
                {
                    "build.name": "app",
                    "build.number": "7",
                    "build.created": "2026-01-01",
                    "modules": [
                        {"module.name": "core", "artifacts": [{"artifact.name": "core.jar", "artifact.sha1": "a1"}]},
                        {"module.name": "web", "artifacts": [{"artifact.name": "web.war", "artifact.sha1": "b2"}]},
                    ],
                },
            ),
            (
                "prefixed_nested_keys",
                {
                    "name": "app",
                    "number": "7",
                    "created": "2026-01-01",
                    "build.modules": [
                        {"name": "core", "module.artifacts": [{"name": "core.jar", "sha1": "a1"}]},
                        {"name": "web", "module.artifacts": [{"name": "web.war", "sha1": "b2"}]},
                    ],
                },
            ),
        ]
    )
    def test_build_artifacts_one_row_per_module_artifact(self, _name: str, item: dict) -> None:
        rows = list(flatten_related(JFROG_ARTIFACTORY_ENDPOINTS["build_artifacts"], item))

        assert rows == [
            {
                "build_name": "app",
                "build_number": "7",
                "build_created": "2026-01-01",
                "module_name": "core",
                "name": "core.jar",
                "sha1": "a1",
            },
            {
                "build_name": "app",
                "build_number": "7",
                "build_created": "2026-01-01",
                "module_name": "web",
                "name": "web.war",
                "sha1": "b2",
            },
        ]

    def test_artifact_statistics_merges_stat_into_item(self) -> None:
        item = {
            "repo": "libs",
            "path": "com/acme",
            "name": "a.jar",
            "created": "2026-01-01",
            "stats": [{"downloads": 12, "downloaded": "2026-02-01", "downloaded_by": "ci"}],
        }

        rows = list(flatten_related(JFROG_ARTIFACTORY_ENDPOINTS["artifact_statistics"], item))

        assert rows == [
            {
                "repo": "libs",
                "path": "com/acme",
                "name": "a.jar",
                "created": "2026-01-01",
                "downloads": 12,
                "downloaded": "2026-02-01",
                "downloaded_by": "ci",
            }
        ]

    def test_parent_without_related_entries_emits_nothing(self) -> None:
        item = {"build.name": "app", "build.number": "7", "build.created": "2026-01-01"}
        assert list(flatten_related(JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"], item)) == []


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

    def safe_point(self) -> None:
        pass


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


def _build(number: int) -> dict:
    return {"build.name": "app", "build.number": str(number), "build.created": f"2026-01-01T00:00:{number:02d}"}


def _promotions_for(query: str) -> dict:
    criteria = json.loads(query[len("builds.find(") : query.index(").include(")])
    return {
        "results": [
            {
                "build.name": parent["name"],
                "build.number": parent["number"],
                "build.created": "2026-01-01",
                "promotions": [{"promotion.created": f"2026-02-{parent['number']}", "promotion.status": "released"}],
            }
            for parent in criteria["$or"]
        ]
    }


def _patch_related_aql(monkeypatch: Any, parent_pages: dict[str, dict], related: Any) -> list[str]:
    queries: list[str] = []

    def fake_post_aql(session: Any, base_url: str, access_token: str, query: str, logger: Any) -> dict:
        queries.append(query)
        if ".offset(" in query:
            return parent_pages[query]
        return related(query)

    monkeypatch.setattr(jfrog_artifactory, "_post_aql", fake_post_aql)
    return queries


class TestGetRowsAqlRelated:
    def test_fetches_related_rows_per_chunk_and_saves_state_per_parent_page(self, monkeypatch: Any) -> None:
        config = dataclasses.replace(JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"], aql_related_chunk_size=2)
        monkeypatch.setitem(JFROG_ARTIFACTORY_ENDPOINTS, "build_promotions", config)
        full_page = [_build(i) for i in range(AQL_PAGE_SIZE)]
        page_1 = build_aql_query(config, offset=0)
        page_2 = build_aql_query(config, offset=AQL_PAGE_SIZE)
        queries = _patch_related_aql(
            monkeypatch,
            {page_1: {"results": full_page}, page_2: {"results": [_build(99)]}},
            _promotions_for,
        )
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint="build_promotions")

        assert len(rows) == AQL_PAGE_SIZE + 1
        assert rows[0] == {
            "build_name": "app",
            "build_number": "0",
            "build_created": "2026-01-01",
            "created": "2026-02-0",
            "status": "released",
        }
        related_queries = [q for q in queries if ".offset(" not in q]
        assert len(related_queries) == AQL_PAGE_SIZE // 2 + 1
        assert manager.saved == [JfrogArtifactoryResumeConfig(next_offset=AQL_PAGE_SIZE, incremental_filter_value=None)]

    def test_incremental_cursor_on_build_created_filters_parent_created(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["build_artifacts"]
        parent_query = build_aql_query(
            config, incremental_field="created", incremental_filter_value="2026-03-04T00:00:00.000+00:00"
        )
        queries = _patch_related_aql(monkeypatch, {parent_query: {"results": []}}, lambda q: {"results": []})

        _collect(
            _FakeResumableManager(),
            endpoint="build_artifacts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="build_created",
        )

        assert queries == [parent_query]

    def test_oversized_related_query_splits_before_request(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"]
        parents = [_build(i) for i in range(4)]
        two_parent_query = build_related_aql_query(config, parents[:2])
        monkeypatch.setattr(jfrog_artifactory, "AQL_RELATED_QUERY_MAX_BYTES", len(two_parent_query.encode()) - 1)
        queries = _patch_related_aql(
            monkeypatch, {build_aql_query(config, offset=0): {"results": parents}}, _promotions_for
        )

        rows = _collect(_FakeResumableManager(), endpoint="build_promotions")

        assert sorted(r["build_number"] for r in rows) == ["0", "1", "2", "3"]
        assert all(query.count('{"name"') == 1 for query in queries if ".offset(" not in query)

    def test_oversized_related_response_splits_chunk(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"]
        parents = [_build(i) for i in range(4)]

        def related(query: str) -> dict:
            if query.count('{"name"') > 1:
                raise JfrogArtifactoryResponseTooLargeError(RESPONSE_LIMIT_ERROR)
            return _promotions_for(query)

        _patch_related_aql(monkeypatch, {build_aql_query(config, offset=0): {"results": parents}}, related)

        rows = _collect(_FakeResumableManager(), endpoint="build_promotions")

        assert sorted(r["build_number"] for r in rows) == ["0", "1", "2", "3"]

    def test_single_parent_over_cap_still_raises(self, monkeypatch: Any) -> None:
        config = JFROG_ARTIFACTORY_ENDPOINTS["build_promotions"]

        def related(query: str) -> dict:
            raise JfrogArtifactoryResponseTooLargeError(RESPONSE_LIMIT_ERROR)

        _patch_related_aql(monkeypatch, {build_aql_query(config, offset=0): {"results": [_build(1)]}}, related)

        with pytest.raises(JfrogArtifactoryResponseTooLargeError):
            _collect(_FakeResumableManager(), endpoint="build_promotions")

    def test_duplicate_related_entries_are_dropped(self, monkeypatch: Any) -> None:
        # Duplicate primary keys in one batch would seed duplicate rows that every later merge multi-matches.
        config = JFROG_ARTIFACTORY_ENDPOINTS["build_dependencies"]
        dependency = {"dependency.name": "lib", "dependency.scope": "compile"}
        _patch_related_aql(
            monkeypatch,
            {build_aql_query(config, offset=0): {"results": [_build(1)]}},
            lambda q: {
                "results": [
                    {
                        "build.name": "app",
                        "build.number": "1",
                        "build.created": "2026-01-01",
                        "modules": [{"module.name": "core", "dependencies": [dependency, dependency]}],
                    }
                ]
            },
        )

        rows = _collect(_FakeResumableManager(), endpoint="build_dependencies")

        assert [(r["module_name"], r["name"]) for r in rows] == [("core", "lib")]


def _violation(created: str) -> dict:
    return {"issue_id": "XRAY-1", "created": created, "violation_details_url": f"https://x/{created}"}


def _patch_xray(monkeypatch: Any, responder: Any) -> list[dict]:
    bodies: list[dict] = []

    def fake_post_xray(session: Any, base_url: str, access_token: str, path: str, body: dict, logger: Any) -> dict:
        assert path == "/v1/violations"
        bodies.append(body)
        return responder(body)

    monkeypatch.setattr(jfrog_artifactory, "_post_xray", fake_post_xray)
    return bodies


class TestGetRowsXray:
    def test_pages_ascending_from_watermark_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            1: [_violation("2026-03-05T00:00:00+00:00")] * XRAY_PAGE_SIZE,
            2: [_violation("2026-03-06T00:00:00+00:00")],
        }
        bodies = _patch_xray(monkeypatch, lambda body: {"violations": pages[body["pagination"]["offset"]]})
        manager = _FakeResumableManager()

        rows = _collect(
            manager,
            endpoint="xray_violations",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created",
        )

        assert len(rows) == XRAY_PAGE_SIZE + 1
        assert bodies == [
            build_xray_violations_request("2026-03-04T00:00:00.000+00:00", 1),
            build_xray_violations_request("2026-03-04T00:00:00.000+00:00", 2),
        ]
        assert bodies[0]["pagination"]["order_by"] == "created"
        assert bodies[0]["pagination"]["direction"] == "asc"
        assert manager.saved == [
            JfrogArtifactoryResumeConfig(next_offset=2, incremental_filter_value="2026-03-04T00:00:00.000+00:00")
        ]

    def test_full_refresh_sends_no_created_from(self, monkeypatch: Any) -> None:
        bodies = _patch_xray(monkeypatch, lambda body: {"violations": []})

        _collect(_FakeResumableManager(), endpoint="xray_violations")

        assert bodies == [build_xray_violations_request(None, 1)]
        assert bodies[0]["filters"] == {}

    def test_restarts_scroll_from_last_created_before_depth_cap(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(jfrog_artifactory, "XRAY_MAX_SCROLL_ROWS", 2 * XRAY_PAGE_SIZE)
        calls: list[tuple[str | None, int]] = []

        def responder(body: dict) -> dict:
            calls.append((body["filters"].get("created_from"), body["pagination"]["offset"]))
            if len(calls) == 1:
                return {"violations": [_violation("2026-03-05T10:00:00+00:00")] * XRAY_PAGE_SIZE}
            if len(calls) == 2:
                return {"violations": [_violation("2026-03-05T12:00:00+02:00")] * XRAY_PAGE_SIZE}
            return {"violations": []}

        _patch_xray(monkeypatch, responder)

        _collect(_FakeResumableManager(), endpoint="xray_violations")

        # After two pages the scroll restarts one second before the last row's created time (in UTC).
        assert calls == [(None, 1), (None, 2), ("2026-03-05T09:59:59.000+00:00", 1)]

    def test_resumes_saved_page_and_filter(self, monkeypatch: Any) -> None:
        bodies = _patch_xray(monkeypatch, lambda body: {"violations": [_violation("2026-03-05T00:00:00+00:00")]})

        rows = _collect(
            _FakeResumableManager(
                JfrogArtifactoryResumeConfig(next_offset=3, incremental_filter_value="2026-03-01T00:00:00.000+00:00")
            ),
            endpoint="xray_violations",
        )

        assert len(rows) == 1
        assert bodies == [build_xray_violations_request("2026-03-01T00:00:00.000+00:00", 3)]


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
            ("artifact_statistics", ["repo", "path", "name"], None),
            ("build_artifacts", ["build_name", "build_number", "module_name", "name"], "build_created"),
            ("build_dependencies", ["build_name", "build_number", "module_name", "name"], "build_created"),
            ("build_promotions", ["build_name", "build_number", "created", "status"], "created"),
            ("xray_violations", ["violation_details_url"], "created"),
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

    def test_xray_probe_posts_single_row_violations_search(self, monkeypatch: Any) -> None:
        session = _FakeSession(status_code=404)
        monkeypatch.setattr(jfrog_artifactory, "_get_session", lambda access_token: session)

        ok, status = probe_endpoint("https://acme.jfrog.io", "token", endpoint="xray_violations")

        assert (ok, status) == (False, 404)
        method, url, data = session.requests[0]
        assert (method, url) == ("POST", "https://acme.jfrog.io/xray/api/v1/violations")
        assert data is not None and json.loads(data)["pagination"]["limit"] == 1

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

    @parameterized.expand(
        [
            # A compact body of many containers or scalars stays under the byte cap but json.loads
            # allocates one object per value, amplifying far past its size. The token guard counts
            # `,`/`{`/`[` and must reject either shape before parsing.
            ("containers", b"[" + b"{}," * 60 + b"{}]"),
            ("scalars", b'{"results":[' + b"0.0," * 60 + b"0.0]}"),
        ]
    )
    def test_over_token_cap_raises_non_retryable(self, _name: str, body: bytes) -> None:
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[body])

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_JSON_TOKENS", 10)
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert session.request.call_count == 1

    def test_transfer_deadline_aborts_slow_stream(self) -> None:
        # A transfer that keeps yielding chunks but drags past the wall-clock deadline must abort
        # (before parsing) rather than run indefinitely; the check runs between chunks.
        session = MagicMock()
        session.request.return_value = _streamed_response(chunks=[b"a", b"b"])

        with pytest.raises(JfrogArtifactoryResponseTooLargeError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(jfrog_artifactory, "MAX_TRANSFER_SECONDS", -1)  # any elapsed time is past it
                _request(session, "GET", "https://acme.jfrog.io/api/x", {}, MagicMock())

        assert RESPONSE_LIMIT_ERROR in str(exc.value)
        assert session.request.call_count == 1
