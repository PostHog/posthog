import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.crates_io import (
    CRATES_IO_BASE_URL,
    EXTRA_DOWNLOADS_VERSION_ID,
    MAX_CRATES,
    MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES,
    USER_AGENT,
    CratesIORetryableError,
    _canonical_name,
    _crate_url,
    _fetch_json,
    crates_io_source,
    get_rows,
    parse_crates,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.settings import CRATES_IO_ENDPOINTS

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


class TestParseCrates:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("serde", ["serde"]),
            ("serde\ntokio", ["serde", "tokio"]),
            ("serde, tokio", ["serde", "tokio"]),
            ("  serde , tokio \n posthog-rs ", ["serde", "tokio", "posthog-rs"]),
            # De-duplicated while preserving order so the primary key never sees the same crate twice.
            ("serde\nserde\ntokio", ["serde", "tokio"]),
            ("serde\n\n  \ntokio", ["serde", "tokio"]),
            # crates.io treats `-`/`_` as interchangeable and names as case-insensitive; both aliases
            # would resolve to the same canonical crate and emit rows with a colliding primary key.
            ("serde-json\nserde_json", ["serde-json"]),
            ("Serde\nserde", ["Serde"]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_crates(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , "])
    def test_empty_raises(self, raw):
        with pytest.raises(ValueError):
            parse_crates(raw)

    def test_rejects_too_many_crates(self):
        raw = "\n".join(f"crate{i}" for i in range(MAX_CRATES + 1))
        with pytest.raises(ValueError, match="Too many crates"):
            parse_crates(raw)

    def test_allows_max_crates(self):
        raw = "\n".join(f"crate{i}" for i in range(MAX_CRATES))
        assert len(parse_crates(raw)) == MAX_CRATES


class TestCrateUrl:
    def test_encodes_path_segment(self):
        assert _crate_url("serde") == f"{CRATES_IO_BASE_URL}/crates/serde"
        # A stray slash must not escape the /crates/<name> path.
        assert "/" not in _crate_url("a/b").removeprefix(f"{CRATES_IO_BASE_URL}/crates/")


class TestCanonicalName:
    def test_prefers_crate_id(self):
        assert _canonical_name("serde-json", {"crate": {"id": "serde_json"}}) == "serde_json"

    @pytest.mark.parametrize("detail", [{}, {"crate": {}}, {"crate": {"id": None}}])
    def test_falls_back_to_requested_name(self, detail):
        assert _canonical_name("serde-json", detail) == "serde-json"


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_json.__wrapped__  # type: ignore[attr-defined]


def _throttle() -> mock.MagicMock:
    return mock.MagicMock()


class TestFetchJson:
    def test_ok_returns_body(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"crate": {"id": "serde"}})

        assert _fetch_once(session, _throttle(), "url", structlog.get_logger()) == {"crate": {"id": "serde"}}

    def test_404_returns_none(self):
        # A typo'd or deleted crate must be skipped, not fail the whole sync.
        session = mock.MagicMock()
        session.get.return_value = _response(404)

        assert _fetch_once(session, _throttle(), "url", structlog.get_logger()) is None

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
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("serde")

        assert is_valid is expected_valid

    def test_empty_crates_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_probes_first_crate_with_crawler_policy_user_agent(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("serde\ntokio")

            called_url = mock_session.return_value.get.call_args[0][0]
            session_headers = mock_session.call_args.kwargs["headers"]

        assert called_url == f"{CRATES_IO_BASE_URL}/crates/serde"
        # crates.io blocks requests without a descriptive User-Agent.
        assert session_headers["User-Agent"] == USER_AGENT

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("serde")

        assert is_valid is False
        assert message is not None


class TestGetRows:
    def test_crates_yields_a_batch_per_crate_and_skips_404(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _crate_detail("serde")),
                _response(404),
                _response(200, _crate_detail("tokio")),
            ]

            batches = list(get_rows("crates", ["serde", "nope", "tokio"], structlog.get_logger()))

        # The 404 crate is skipped, so only two batches come back.
        assert len(batches) == 2
        assert batches[0][0]["id"] == "serde"
        assert batches[1][0]["id"] == "tokio"

    def test_versions_follows_seek_pagination(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _versions_page(["1.0.1", "1.0.0"], next_page="?per_page=100&seek=abc")),
                _response(200, _versions_page(["0.9.0"], next_page=None)),
            ]

            batches = list(get_rows("versions", ["serde"], structlog.get_logger()))

            second_url = mock_session.return_value.get.call_args_list[1][0][0]

        assert [row["num"] for batch in batches for row in batch] == ["1.0.1", "1.0.0", "0.9.0"]
        # The follow-up request must use the API's ready-made `next_page` query string.
        assert second_url == f"{CRATES_IO_BASE_URL}/crates/serde/versions?per_page=100&seek=abc"

    def test_downloads_stamps_canonical_crate_and_sentinel_version(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                # The canonical id (`serde_json`) differs from the user's spelling (`serde-json`);
                # rows must be keyed on the canonical form so joins with `crates`/`versions` align.
                _response(200, _crate_detail("serde_json")),
                _response(200, _downloads_document()),
            ]

            batches = list(get_rows("downloads", ["serde-json"], structlog.get_logger()))

        rows = [row for batch in batches for row in batch]
        # The malformed entry without a `date` (a primary key component) is dropped.
        assert len(rows) == 3
        assert all(row["crate"] == "serde_json" for row in rows)
        # Aggregate `extra_downloads` rows carry the sentinel version id so the primary key stays
        # non-null and daily totals stay complete.
        extra_rows = [row for row in rows if row["version"] == EXTRA_DOWNLOADS_VERSION_ID]
        assert [(row["date"], row["downloads"]) for row in extra_rows] == [("2026-07-01", 526826)]

    def test_owners_stamps_canonical_crate(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _crate_detail("serde")),
                _response(200, {"users": [{"id": 3618, "login": "dtolnay", "kind": "user"}]}),
            ]

            batches = list(get_rows("owners", ["serde"], structlog.get_logger()))

        assert batches == [[{"id": 3618, "login": "dtolnay", "kind": "user", "crate": "serde"}]]

    def test_dependencies_stamps_parent_crate_and_version(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _versions_page(["1.0.1", "1.0.0"], next_page=None)),
                _response(200, _dependencies_document(1, ["serde_derive"])),
                _response(404),
            ]

            batches = list(get_rows("dependencies", ["serde"], structlog.get_logger()))

            urls = [call[0][0] for call in mock_session.return_value.get.call_args_list]

        # The endpoint's own `crate_id` names the crate being depended on, so the declaring crate
        # and version only exist on the row because the connector stamps them.
        assert [row for batch in batches for row in batch] == [
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
        assert urls[0] == (
            f"{CRATES_IO_BASE_URL}/crates/serde/versions?per_page={MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES}&sort=date"
        )
        # A version whose dependencies 404 is skipped rather than failing the crate.
        assert urls[1:] == [
            f"{CRATES_IO_BASE_URL}/crates/serde/1.0.1/dependencies",
            f"{CRATES_IO_BASE_URL}/crates/serde/1.0.0/dependencies",
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
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [_response(200, document)]

            batches = list(get_rows("reverse_dependencies", ["posthog-rs"], structlog.get_logger()))

        rows = [row for batch in batches for row in batch]
        # Without the join a row identifies its dependent only by a numeric version id.
        assert (rows[0]["crate"], rows[0]["dependent_crate"], rows[0]["dependent_version_num"]) == (
            "posthog-rs",
            "tauri-plugin-posthog",
            "0.2.4",
        )
        # An edge whose version is missing from the page still yields, with no dependent stamped.
        assert (rows[1]["dependent_crate"], rows[1]["dependent_version_num"]) == (None, None)

    def test_reverse_dependencies_walks_pages_until_a_short_one(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.LIST_PER_PAGE", 2)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"dependencies": [{"id": 1}, {"id": 2}], "versions": []}),
                _response(200, {"dependencies": [{"id": 3}], "versions": []}),
            ]

            batches = list(get_rows("reverse_dependencies", ["posthog-rs"], structlog.get_logger()))

            urls = [call[0][0] for call in mock_session.return_value.get.call_args_list]

        assert [row["id"] for batch in batches for row in batch] == [1, 2, 3]
        base = f"{CRATES_IO_BASE_URL}/crates/posthog-rs/reverse_dependencies"
        assert urls == [f"{base}?per_page=2&page=1", f"{base}?per_page=2&page=2"]

    def test_reverse_dependencies_stops_at_the_page_cap(self, monkeypatch):
        # crates.io serves empty pages past the end of the list instead of erroring, so a crate
        # with tens of thousands of reverse dependencies must not walk the list unbounded.
        monkeypatch.setattr(f"{MODULE}.LIST_PER_PAGE", 1)
        monkeypatch.setattr(f"{MODULE}.MAX_REVERSE_DEPENDENCY_PAGES", 3)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"dependencies": [{"id": 1}], "versions": []})

            batches = list(get_rows("reverse_dependencies", ["serde"], structlog.get_logger()))

            request_count = mock_session.return_value.get.call_count

        assert request_count == 3
        assert len([row for batch in batches for row in batch]) == 3

    @pytest.mark.parametrize("endpoint", ["categories", "keywords"])
    def test_registry_wide_lookups_are_walked_once(self, endpoint, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.LIST_PER_PAGE", 2)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {endpoint: [{"id": "a"}, {"id": "b"}]}),
                _response(200, {endpoint: [{"id": "c"}]}),
            ]

            batches = list(get_rows(endpoint, ["serde", "tokio"], structlog.get_logger()))

            urls = [call[0][0] for call in mock_session.return_value.get.call_args_list]

        assert [row["id"] for batch in batches for row in batch] == ["a", "b", "c"]
        # These tables cover the whole registry, so two configured crates must not walk them twice.
        base = f"{CRATES_IO_BASE_URL}/{endpoint}"
        assert urls == [f"{base}?sort=alpha&per_page=2&page=1", f"{base}?sort=alpha&per_page=2&page=2"]

    def test_chunks_large_version_history(self, monkeypatch):
        # A crate with a large version history must not be yielded as one oversized list; it's
        # split into bounded chunks so downstream Arrow conversion stays capped.
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 2)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200, _versions_page(["1.0.2", "1.0.1", "1.0.0"], next_page=None)
            )

            batches = list(get_rows("versions", ["serde"], structlog.get_logger()))

        # Three versions at 2 rows per chunk is [2, 1].
        assert [len(b) for b in batches] == [2, 1]


class TestCratesIOSourceResponse:
    @pytest.mark.parametrize("endpoint", list(CRATES_IO_ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = crates_io_source(endpoint, "serde", structlog.get_logger())

        assert response.name == endpoint
        assert response.primary_keys == CRATES_IO_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

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
