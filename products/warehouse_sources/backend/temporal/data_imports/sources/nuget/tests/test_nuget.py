from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nuget import nuget
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.nuget import (
    MAX_PACKAGES,
    MAX_VALIDATED_PACKAGES,
    NugetPackageNotFoundError,
    NugetResumeConfig,
    _resolve_resource,
    get_rows,
    parse_package_ids,
    validate_nuget_connection,
)

SERVICE_INDEX_URL = "https://api.nuget.org/v3/index.json"
SEARCH_URL = "https://azuresearch-usnc.nuget.org/query"
REGISTRATION_URL = "https://api.nuget.org/v3/registration5-gz-semver2/"
CATALOG_INDEX_URL = "https://api.nuget.org/v3/catalog0/index.json"

SERVICE_INDEX = {
    "resources": [
        {"@id": SEARCH_URL, "@type": "SearchQueryService"},
        {"@id": SEARCH_URL, "@type": "SearchQueryService/3.5.0"},
        {"@id": "https://api.nuget.org/v3/registration5-semver1/", "@type": "RegistrationsBaseUrl"},
        {"@id": REGISTRATION_URL, "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": CATALOG_INDEX_URL, "@type": "Catalog/3.0.0"},
    ]
}


def _search_query_url(package_id: str) -> str:
    return f"{SEARCH_URL}?q=packageid%3A{package_id}&prerelease=true&semVerLevel=2.0.0"


def _search_doc(package_id: str, **overrides: Any) -> dict:
    doc = {
        "@id": f"{REGISTRATION_URL}{package_id.lower()}/index.json",
        "@type": "Package",
        "id": package_id,
        "version": "2.0.0",
        "totalDownloads": 100,
        "verified": True,
        "versions": [
            {"version": "1.0.0", "downloads": 40},
            {"version": "2.0.0+sha123", "downloads": 60},
        ],
    }
    doc.update(overrides)
    return doc


class _FakeResumableManager:
    def __init__(self, state: NugetResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NugetResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NugetResumeConfig | None:
        return self._state

    def save_state(self, data: NugetResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> dict:
        fetched.append(url)
        if url not in pages:
            raise AssertionError(f"Unexpected fetch: {url}")
        return pages[url]

    monkeypatch.setattr(nuget, "_fetch_json", fake_fetch)
    return fetched


def _collect(manager: _FakeResumableManager, endpoint: str, package_ids: str = "Foo.Bar", **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        package_ids_raw=package_ids,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestParsePackageIds:
    @parameterized.expand(
        [
            ("commas", "Newtonsoft.Json, Serilog", ["Newtonsoft.Json", "Serilog"]),
            ("newlines", "Newtonsoft.Json\nSerilog\n", ["Newtonsoft.Json", "Serilog"]),
            ("case_insensitive_dedupe", "Serilog, serilog, SERILOG", ["Serilog"]),
            ("whitespace_and_empty_chunks", "  Foo.Bar , , \n Baz ", ["Foo.Bar", "Baz"]),
        ]
    )
    def test_valid_lists(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_package_ids(raw) == expected

    @parameterized.expand([("empty", ""), ("only_separators", " , \n , ")])
    def test_empty_raises(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_package_ids(raw)

    def test_too_many_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_package_ids(",".join(f"pkg{i}" for i in range(MAX_PACKAGES + 1)))

    def test_at_limit_ok(self) -> None:
        assert len(parse_package_ids(",".join(f"pkg{i}" for i in range(MAX_PACKAGES)))) == MAX_PACKAGES


class TestResolveResource:
    def test_prefers_versioned_type(self) -> None:
        assert _resolve_resource(SERVICE_INDEX, ("RegistrationsBaseUrl/3.6.0", "RegistrationsBaseUrl")) == (
            REGISTRATION_URL
        )

    def test_falls_back_to_unversioned_type(self) -> None:
        assert _resolve_resource(SERVICE_INDEX, ("SearchQueryService/9.9.9", "SearchQueryService")) == SEARCH_URL

    def test_missing_resource_raises(self) -> None:
        with pytest.raises(ValueError):
            _resolve_resource({"resources": []}, ("Catalog/3.0.0",))


class TestPackagesEndpoint:
    def test_yields_row_without_versions_or_jsonld_keys(self, monkeypatch: Any) -> None:
        _patch_fetch(
            monkeypatch,
            {SERVICE_INDEX_URL: SERVICE_INDEX, _search_query_url("Foo.Bar"): {"data": [_search_doc("Foo.Bar")]}},
        )
        rows = _collect(_FakeResumableManager(), "packages")

        assert len(rows) == 1
        assert rows[0]["id"] == "Foo.Bar"
        assert rows[0]["totalDownloads"] == 100
        assert "versions" not in rows[0]
        assert "@id" not in rows[0]
        assert "@type" not in rows[0]

    def test_search_miss_skips_package_and_continues(self, monkeypatch: Any) -> None:
        # Unlisted packages are hidden from search; the sync must not fail, just move on.
        _patch_fetch(
            monkeypatch,
            {
                SERVICE_INDEX_URL: SERVICE_INDEX,
                _search_query_url("Gone.Pkg"): {"data": []},
                _search_query_url("Foo.Bar"): {"data": [_search_doc("Foo.Bar")]},
            },
        )
        rows = _collect(_FakeResumableManager(), "packages", package_ids="Gone.Pkg, Foo.Bar")

        assert [row["id"] for row in rows] == ["Foo.Bar"]

    def test_saves_resume_state_between_packages_only(self, monkeypatch: Any) -> None:
        _patch_fetch(
            monkeypatch,
            {
                SERVICE_INDEX_URL: SERVICE_INDEX,
                _search_query_url("A"): {"data": [_search_doc("A")]},
                _search_query_url("B"): {"data": [_search_doc("B")]},
            },
        )
        manager = _FakeResumableManager()
        _collect(manager, "packages", package_ids="A, B")

        assert manager.saved == [NugetResumeConfig(last_package_id="A")]

    def test_resumes_after_bookmarked_package(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(
            monkeypatch,
            {SERVICE_INDEX_URL: SERVICE_INDEX, _search_query_url("B"): {"data": [_search_doc("B")]}},
        )
        rows = _collect(_FakeResumableManager(NugetResumeConfig(last_package_id="a")), "packages", package_ids="A, B")

        assert [row["id"] for row in rows] == ["B"]
        assert _search_query_url("A") not in fetched


class TestPackageVersionsEndpoint:
    def _pages(self) -> dict[str, Any]:
        leaf_1 = {"catalogEntry": {"@id": "leaf1", "id": "Foo.Bar", "version": "1.0.0", "listed": True}}
        leaf_2 = {"catalogEntry": {"@id": "leaf2", "id": "Foo.Bar", "version": "2.0.0+sha123", "listed": True}}
        return {
            SERVICE_INDEX_URL: SERVICE_INDEX,
            _search_query_url("Foo.Bar"): {"data": [_search_doc("Foo.Bar")]},
            f"{REGISTRATION_URL}foo.bar/index.json": {
                "items": [
                    {"items": [leaf_1]},  # inlined page
                    {"@id": f"{REGISTRATION_URL}foo.bar/page/2.json"},  # linked page
                ]
            },
            f"{REGISTRATION_URL}foo.bar/page/2.json": {"items": [leaf_2]},
        }

    def test_walks_inlined_and_linked_pages_and_merges_downloads(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, self._pages())
        rows = _collect(_FakeResumableManager(), "package_versions")

        assert [(row["id"], row["version"]) for row in rows] == [("Foo.Bar", "1.0.0"), ("Foo.Bar", "2.0.0+sha123")]
        # Downloads come from search, matched with SemVer build metadata stripped.
        assert [row["downloads"] for row in rows] == [40, 60]
        assert all("@id" not in row for row in rows)

    def test_unknown_package_raises_not_found(self, monkeypatch: Any) -> None:
        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            if url == SERVICE_INDEX_URL:
                return SERVICE_INDEX
            if url == _search_query_url("Nope"):
                return {"data": []}
            response = MagicMock(status_code=404)
            raise requests.HTTPError(response=response)

        monkeypatch.setattr(nuget, "_fetch_json", fake_fetch)

        with pytest.raises(NugetPackageNotFoundError):
            _collect(_FakeResumableManager(), "package_versions", package_ids="Nope")


def _catalog_item(package_id: str, version: str, timestamp: str, event_type: str = "nuget:PackageDetails") -> dict:
    return {
        "@id": f"https://api.nuget.org/v3/catalog0/data/{timestamp}/{package_id.lower()}.{version}.json",
        "@type": event_type,
        "commitId": f"commit-{timestamp}",
        "commitTimeStamp": timestamp,
        "nuget:id": package_id,
        "nuget:version": version,
    }


class TestCatalogEventsEndpoint:
    PAGE_1_URL = "https://api.nuget.org/v3/catalog0/page1.json"
    PAGE_2_URL = "https://api.nuget.org/v3/catalog0/page2.json"

    def _pages(self) -> dict[str, Any]:
        # The live index lists pages out of time order; items within a page are unsorted too.
        return {
            SERVICE_INDEX_URL: SERVICE_INDEX,
            CATALOG_INDEX_URL: {
                "items": [
                    {"@id": self.PAGE_2_URL, "commitTimeStamp": "2026-02-01T00:00:00.0000000Z"},
                    {"@id": self.PAGE_1_URL, "commitTimeStamp": "2026-01-01T00:00:00.0000000Z"},
                ]
            },
            self.PAGE_1_URL: {
                "items": [
                    _catalog_item("Foo.Bar", "1.1.0", "2026-01-01T00:00:00.0000000Z"),
                    _catalog_item("Foo.Bar", "1.0.0", "2025-12-01T00:00:00.0000000Z"),
                    _catalog_item("Other.Pkg", "9.0.0", "2025-12-15T00:00:00.0000000Z"),
                ]
            },
            self.PAGE_2_URL: {
                "items": [
                    _catalog_item("Foo.Bar", "2.0.0", "2026-02-01T00:00:00.0000000Z", "nuget:PackageDelete"),
                ]
            },
        }

    def test_first_sync_walks_pages_in_ascending_commit_order(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, self._pages())
        rows = _collect(_FakeResumableManager(), "catalog_events")

        # Unsorted index/page items must come out globally ascending (sort_mode="asc" contract),
        # filtered to the tracked package.
        assert [row["package_version"] for row in rows] == ["1.0.0", "1.1.0", "2.0.0"]
        assert [row["package_id"] for row in rows] == ["Foo.Bar"] * 3
        assert rows[0]["commit_timestamp"] == datetime(2025, 12, 1, tzinfo=UTC)
        assert rows[2]["event_type"] == "nuget:PackageDelete"
        assert fetched.index(self.PAGE_1_URL) < fetched.index(self.PAGE_2_URL)

    def test_incremental_cursor_skips_whole_pages_without_fetching(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, self._pages())
        rows = _collect(
            _FakeResumableManager(),
            "catalog_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert self.PAGE_1_URL not in fetched
        assert [row["package_version"] for row in rows] == ["2.0.0"]

    def test_cursor_filters_items_within_a_refetched_page(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, self._pages())
        rows = _collect(
            _FakeResumableManager(),
            "catalog_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 12, 20, tzinfo=UTC),
        )

        assert [row["package_version"] for row in rows] == ["1.1.0", "2.0.0"]

    def test_saves_state_after_each_processed_page(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, self._pages())
        manager = _FakeResumableManager()
        _collect(manager, "catalog_events")

        assert [state.commit_cursor for state in manager.saved] == [
            "2026-01-01T00:00:00.0000000Z",
            "2026-02-01T00:00:00.0000000Z",
        ]

    def test_resume_checkpoint_acts_as_cursor(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, self._pages())
        rows = _collect(
            _FakeResumableManager(NugetResumeConfig(commit_cursor="2026-01-01T00:00:00.0000000Z")),
            "catalog_events",
        )

        assert self.PAGE_1_URL not in fetched
        assert [row["package_version"] for row in rows] == ["2.0.0"]

    def test_later_of_watermark_and_resume_checkpoint_wins(self, monkeypatch: Any) -> None:
        fetched = _patch_fetch(monkeypatch, self._pages())
        rows = _collect(
            _FakeResumableManager(NugetResumeConfig(commit_cursor="2026-02-01T00:00:00.0000000Z")),
            "catalog_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 12, 20, tzinfo=UTC),
        )

        assert rows == []
        assert self.PAGE_1_URL not in fetched
        assert self.PAGE_2_URL not in fetched


class TestValidateNugetConnection:
    def _session(self, registration_status: int = 200) -> MagicMock:
        session = MagicMock()

        def fake_get(url: str, timeout: int = 10) -> MagicMock:
            if url == SERVICE_INDEX_URL:
                return MagicMock(status_code=200, json=lambda: SERVICE_INDEX, raise_for_status=lambda: None)
            return MagicMock(status_code=registration_status)

        session.get.side_effect = fake_get
        return session

    def test_valid_packages(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(nuget, "make_tracked_session", lambda: self._session())
        assert validate_nuget_connection("Foo.Bar, Baz") == (True, None)

    def test_unknown_packages_named_in_error(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(nuget, "make_tracked_session", lambda: self._session(registration_status=404))
        ok, message = validate_nuget_connection("Nope.One, Nope.Two")

        assert ok is False
        assert "Nope.One" in (message or "")
        assert "Nope.Two" in (message or "")

    def test_transient_probe_errors_do_not_block_creation(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(nuget, "make_tracked_session", lambda: self._session(registration_status=503))
        assert validate_nuget_connection("Foo.Bar") == (True, None)

    def test_unreachable_service_index(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        monkeypatch.setattr(nuget, "make_tracked_session", lambda: session)

        ok, message = validate_nuget_connection("Foo.Bar")
        assert ok is False
        assert "Could not reach the NuGet API" in (message or "")

    def test_probe_count_capped(self, monkeypatch: Any) -> None:
        session = self._session()
        monkeypatch.setattr(nuget, "make_tracked_session", lambda: session)
        validate_nuget_connection(", ".join(f"pkg{i}" for i in range(MAX_VALIDATED_PACKAGES + 10)))

        # 1 service-index fetch + at most MAX_VALIDATED_PACKAGES probes.
        assert session.get.call_count == 1 + MAX_VALIDATED_PACKAGES
