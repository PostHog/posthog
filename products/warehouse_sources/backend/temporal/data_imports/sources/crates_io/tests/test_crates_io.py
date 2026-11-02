import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.crates_io import (
    CRATES_IO_BASE_URL,
    EXTRA_DOWNLOADS_VERSION_ID,
    MAX_CRATES,
    MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES,
    MAX_VERSIONS_PER_CRATE_FOR_VERSION_DOWNLOADS,
    CratesIORetryableError,
    _fetch_json,
    crates_io_source,
    parse_crates,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source import CratesIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cratesio import (
    CratesIOSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.crates_io"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    # The crawler-policy throttle would add a real 1s sleep between mocked requests.
    monkeypatch.setattr(f"{MODULE}.THROTTLE_SECONDS", 0.0)


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {CRATES_IO_BASE_URL}", response=requests.Response()
        )
    return resp


def _crate_detail(name: str = "serde") -> dict[str, Any]:
    return {
        "crate": {
            "id": name,
            "name": name,
            "created_at": "2014-12-05T20:20:32Z",
            "updated_at": "2025-09-27T16:51:35Z",
            "downloads": 1000,
        },
        "versions": [],
        "keywords": [],
        "categories": [],
    }


def _versions_page(nums: list[str], next_page: str | None) -> dict[str, Any]:
    return {
        "versions": [
            {"id": index + 1, "crate": "serde", "num": num, "created_at": "2020-01-01T00:00:00Z"}
            for index, num in enumerate(nums)
        ],
        "meta": {"total": len(nums), "next_page": next_page},
    }


def _dependencies_document(version_id: int, crate_ids: list[str]) -> dict[str, Any]:
    return {
        "dependencies": [
            {"id": 100 + index, "version_id": version_id, "crate_id": crate_id, "kind": "normal"}
            for index, crate_id in enumerate(crate_ids)
        ]
    }


def _downloads_document() -> dict[str, Any]:
    return {
        "version_downloads": [
            {"version": 1748414, "downloads": 1731354, "date": "2026-07-01"},
            {"version": 1748414, "downloads": 1650000, "date": "2026-07-02"},
            {"downloads": 5, "date": ""},
        ],
        "meta": {
            "extra_downloads": [
                {"date": "2026-07-01", "downloads": 526826},
            ]
        },
    }


def _driver(crates: str = "serde") -> SourceDriver:
    return SourceDriver(CratesIOSource(), CratesIOSourceConfig(crates=crates))


class TestParseCrates:
    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , "])
    def test_empty_raises(self, raw):
        with pytest.raises(ValueError):
            parse_crates(raw)

    def test_rejects_too_many_crates(self):
        raw = "\n".join(f"crate{i}" for i in range(MAX_CRATES + 1))
        with pytest.raises(ValueError, match="Too many crates"):
            parse_crates(raw)


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_json.__wrapped__  # type: ignore[attr-defined]


def _throttle() -> mock.MagicMock:
    return mock.MagicMock()


class TestFetchJson:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(CratesIORetryableError):
            _fetch_once(session, _throttle(), "url", structlog.get_logger())

    def test_other_client_error_raises(self):
        session = mock.MagicMock()
        session.get.return_value = _response(400)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, _throttle(), "url", structlog.get_logger())


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (404, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, _ = validate_credentials("serde")

        assert is_valid is expected_valid
        assert network.requests_log[0].path == "/api/v1/crates/serde"

    def test_empty_crates_is_invalid_without_request(self):
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self):
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("serde")

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/api/v1/crates/serde"}


class TestGetRows:
    def test_crates_yields_a_batch_per_crate_and_skips_404(self):
        result = _driver("serde\nnope\ntokio").run(
            "crates",
            [
                ScriptedResponse(json=_crate_detail("serde")),
                ScriptedResponse(status=404),
                ScriptedResponse(json=_crate_detail("tokio")),
            ],
        )

        # The 404 crate is skipped, so only two batches come back.
        assert result.raised is None
        assert len(result.items) == 2
        assert result.items[0][0]["id"] == "serde"
        assert result.items[1][0]["id"] == "tokio"
        assert result.paths == ["/api/v1/crates/serde", "/api/v1/crates/nope", "/api/v1/crates/tokio"]

    def test_downloads_stamps_canonical_crate_and_sentinel_version(self):
        result = _driver("serde-json").run(
            "downloads",
            [
                # The canonical id (`serde_json`) differs from the user's spelling (`serde-json`);
                # rows must be keyed on the canonical form so joins with `crates`/`versions` align.
                ScriptedResponse(json=_crate_detail("serde_json")),
                ScriptedResponse(json=_downloads_document()),
            ],
        )

        assert result.raised is None
        rows = result.rows
        # The malformed entry without a `date` (a primary key component) is dropped.
        assert len(rows) == 3
        assert all(row["crate"] == "serde_json" for row in rows)
        # Aggregate `extra_downloads` rows carry the sentinel version id so the primary key stays
        # non-null and daily totals stay complete.
        extra_rows = [row for row in rows if row["version"] == EXTRA_DOWNLOADS_VERSION_ID]
        assert [(row["date"], row["downloads"]) for row in extra_rows] == [("2026-07-01", 526826)]

    def test_owners_stamps_canonical_crate(self):
        result = _driver().run(
            "owners",
            [
                ScriptedResponse(json=_crate_detail("serde")),
                ScriptedResponse(json={"users": [{"id": 3618, "login": "dtolnay", "kind": "user"}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 3618, "login": "dtolnay", "kind": "user", "crate": "serde"}]]

    def test_dependencies_stamps_parent_crate_and_version(self):
        result = _driver().run(
            "dependencies",
            [
                ScriptedResponse(json=_versions_page(["1.0.1", "1.0.0"], next_page=None)),
                ScriptedResponse(json=_dependencies_document(1, ["serde_derive"])),
                ScriptedResponse(status=404),
            ],
        )

        # The endpoint's own `crate_id` names the crate being depended on, so the declaring crate
        # and version only exist on the row because the connector stamps them.
        assert result.raised is None
        assert result.rows == [
            {
                "id": 100,
                "version_id": 1,
                "crate_id": "serde_derive",
                "kind": "normal",
                "crate": "serde",
                "version_num": "1.0.1",
            }
        ]
        # Only the most recently published versions are walked, so the version list must be capped
        # and date-sorted. Sorting by semver would drop a backport released onto an older line.
        assert result.urls[0] == (
            f"{CRATES_IO_BASE_URL}/crates/serde/versions?per_page={MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES}&sort=date"
        )
        # A version whose dependencies 404 is skipped rather than failing the crate.
        assert result.urls[1:] == [
            f"{CRATES_IO_BASE_URL}/crates/serde/1.0.1/dependencies",
            f"{CRATES_IO_BASE_URL}/crates/serde/1.0.0/dependencies",
        ]

    def test_version_downloads_stamps_crate_and_version_num(self):
        result = _driver("serde-json").run(
            "version_downloads",
            [
                ScriptedResponse(json=_versions_page(["1.0.1", "1.0.0", "0.9.0"], next_page=None)),
                ScriptedResponse(
                    json={
                        "version_downloads": [
                            {"version": 1, "downloads": 40, "date": "2026-07-01"},
                            {"version": 1, "downloads": 7, "date": ""},
                            {"downloads": 9, "date": "2026-07-02"},
                        ]
                    }
                ),
                ScriptedResponse(status=404),
                ScriptedResponse(json={"version_downloads": []}),
            ],
        )

        # The endpoint returns only the numeric version id, so the crate and version number exist on
        # the row only because the connector stamps them. Rows missing a primary key part are dropped.
        assert result.raised is None
        assert result.rows == [
            {"version": 1, "downloads": 40, "date": "2026-07-01", "crate": "serde", "version_num": "1.0.1"}
        ]
        assert result.urls == [
            f"{CRATES_IO_BASE_URL}/crates/serde-json/versions?per_page={MAX_VERSIONS_PER_CRATE_FOR_VERSION_DOWNLOADS}&sort=date",
            # A version whose downloads 404 is skipped rather than failing the crate.
            f"{CRATES_IO_BASE_URL}/crates/serde-json/1.0.1/downloads",
            f"{CRATES_IO_BASE_URL}/crates/serde-json/1.0.0/downloads",
            f"{CRATES_IO_BASE_URL}/crates/serde-json/0.9.0/downloads",
        ]

    def test_reverse_dependencies_joins_the_dependent_version(self):
        document = {
            "dependencies": [
                {"id": 1, "version_id": 900, "crate_id": "posthog-rs"},
                {"id": 2, "version_id": 999, "crate_id": "posthog-rs"},
            ],
            "versions": [{"id": 900, "crate": "tauri-plugin-posthog", "num": "0.2.4"}],
            "meta": {"total": 2},
        }
        result = _driver("posthog-rs").run("reverse_dependencies", [ScriptedResponse(json=document)])

        assert result.raised is None
        rows = result.rows
        # Without the join a row identifies its dependent only by a numeric version id.
        assert (rows[0]["crate"], rows[0]["dependent_crate"], rows[0]["dependent_version_num"]) == (
            "posthog-rs",
            "tauri-plugin-posthog",
            "0.2.4",
        )
        # An edge whose version is missing from the page still yields, with no dependent stamped.
        assert (rows[1]["dependent_crate"], rows[1]["dependent_version_num"]) == (None, None)

    def test_reverse_dependencies_stops_at_the_page_cap(self, monkeypatch):
        # crates.io serves empty pages past the end of the list instead of erroring, so a crate
        # with tens of thousands of reverse dependencies must not walk the list unbounded.
        monkeypatch.setattr(f"{MODULE}.LIST_PER_PAGE", 1)
        monkeypatch.setattr(f"{MODULE}.MAX_REVERSE_DEPENDENCY_PAGES", 3)
        result = _driver().run(
            "reverse_dependencies",
            [ScriptedResponse(json={"dependencies": [{"id": 1}], "versions": []}) for _ in range(3)],
        )

        assert result.raised is None
        assert len(result.requests) == 3
        assert len(result.rows) == 3

    @pytest.mark.parametrize("endpoint", ["categories", "keywords"])
    def test_registry_wide_lookups_are_walked_once(self, endpoint, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.LIST_PER_PAGE", 2)
        result = _driver("serde\ntokio").run(
            endpoint,
            [
                ScriptedResponse(json={endpoint: [{"id": "a"}, {"id": "b"}]}),
                ScriptedResponse(json={endpoint: [{"id": "c"}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        # These tables cover the whole registry, so two configured crates must not walk them twice.
        base = f"{CRATES_IO_BASE_URL}/{endpoint}"
        assert result.urls == [
            f"{base}?sort=alpha&per_page=2&page=1",
            f"{base}?sort=alpha&per_page=2&page=2",
        ]

    def test_chunks_large_version_history(self, monkeypatch):
        # A crate with a large version history must not be yielded as one oversized list; it's
        # split into bounded chunks so downstream Arrow conversion stays capped.
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 2)
        result = _driver().run(
            "versions",
            [ScriptedResponse(json=_versions_page(["1.0.2", "1.0.1", "1.0.0"], next_page=None))],
        )

        # Three versions at 2 rows per chunk is [2, 1].
        assert result.raised is None
        assert [len(batch) for batch in result.items] == [2, 1]


class TestCratesIOSourceResponse:
    def test_only_streams_with_stable_dates_are_partitioned(self):
        # `versions` has a stable publish timestamp and `downloads` a stable day; `crates` and
        # `owners` have no stable datetime column.
        versions = crates_io_source("versions", "serde", structlog.get_logger())
        downloads = crates_io_source("downloads", "serde", structlog.get_logger())
        crates = crates_io_source("crates", "serde", structlog.get_logger())
        owners = crates_io_source("owners", "serde", structlog.get_logger())

        assert versions.partition_mode == "datetime"
        assert versions.partition_keys == ["created_at"]
        assert downloads.partition_mode == "datetime"
        assert downloads.partition_keys == ["date"]
        assert crates.partition_mode is None
        assert crates.partition_keys is None
        assert owners.partition_mode is None
        assert owners.partition_keys is None

    def test_invalid_crates_raise(self):
        with pytest.raises(ValueError):
            crates_io_source("crates", "", structlog.get_logger())
