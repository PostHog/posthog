import json
import datetime as dt
from typing import Any, Optional

import pytest
import time_machine
from unittest import mock

import requests
import structlog
from parameterized import parameterized

from products.warehouse_sources.sources.rubygems._config import RubygemsSourceConfig
from products.warehouse_sources.sources.rubygems.rubygems import (
    MAX_GEMS,
    RUBYGEMS_BASE_URL,
    TIMEFRAME_PAGE_SIZE,
    RubyGemsRetryableError,
    _fetch,
    parse_gems,
    rubygems_source,
    validate_credentials,
)
from products.warehouse_sources.sources.rubygems.source import RubygemsSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

MODULE = "products.warehouse_sources.sources.rubygems.rubygems"


def _response(status: int = 200, body: Optional[Any] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else {}
    resp.text = json.dumps(body if body is not None else {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {RUBYGEMS_BASE_URL}", response=requests.Response()
        )
    return resp


def _gem_document(name: str = "rails") -> dict[str, Any]:
    return {
        "name": name,
        "downloads": 766763345,
        "version": "8.1.3",
        "version_downloads": 10458162,
        "platform": "ruby",
        "authors": "David Heinemeier Hansson",
        "licenses": ["MIT"],
    }


def _versions_document(name: str = "rails") -> list[Any]:
    return [
        {
            "number": "8.1.3",
            "platform": "ruby",
            "created_at": "2026-03-24T20:27:42.098Z",
            "downloads_count": 10463551,
            "authors": name,
        },
        {
            "number": "8.1.2.1",
            "platform": "ruby",
            "created_at": "2026-03-23T19:45:37.709Z",
            "downloads_count": 1093372,
        },
        "not-a-dict",
        {"number": "8.1.2.1", "platform": None},  # missing platform: unmergeable, must be dropped
        {"number": None, "platform": "ruby"},  # missing number: unmergeable, must be dropped
    ]


class TestParseGems:
    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , "])
    def test_empty_raises(self, raw):
        with pytest.raises(ValueError):
            parse_gems(raw)

    def test_rejects_too_many_gems(self):
        raw = "\n".join(f"gem{i}" for i in range(MAX_GEMS + 1))
        with pytest.raises(ValueError, match="Too many gems"):
            parse_gems(raw)


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(RubyGemsRetryableError):
            _fetch_once(session, f"{RUBYGEMS_BASE_URL}/gems/rails.json", "rails", structlog.get_logger())

    def test_other_client_error_raises(self):
        session = mock.MagicMock()
        session.get.return_value = _response(400)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, f"{RUBYGEMS_BASE_URL}/gems/rails.json", "rails", structlog.get_logger())


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (404, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            is_valid, _ = validate_credentials("rails")

        assert is_valid is expected_valid

    def test_empty_gems_is_invalid_without_request(self):
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []


class TestGetRows:
    def test_yields_a_batch_per_gem_and_skips_404(self):
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails\nnope\nrspec"))

        result = driver.run(
            "gems",
            [
                ScriptedResponse(json=_gem_document(name="rails")),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json=_gem_document(name="rspec")),
            ],
        )

        # The 404 gem is skipped, so only two batches come back.
        assert len(result.items) == 2
        assert result.items[0][0]["name"] == "rails"
        assert result.items[1][0]["name"] == "rspec"

    def test_chunks_large_version_history(self, monkeypatch):
        # A gem with a large version history must not be yielded as one oversized list; it's split
        # into bounded chunks so downstream Arrow conversion stays capped.
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 1)
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails"))

        result = driver.run("versions", [ScriptedResponse(json=_versions_document(name="rails"))])

        # The document has 2 valid version rows; at 1 row per chunk that's [1, 1].
        assert [len(b) for b in result.items] == [1, 1]


class TestRubyGemsSource:
    def test_only_versions_is_partitioned(self):
        # `versions` has a stable created_at timestamp; `gems` has no stable datetime column.
        versions = rubygems_source("versions", "rails", structlog.get_logger())
        gems = rubygems_source("gems", "rails", structlog.get_logger())

        assert versions.partition_mode == "datetime"
        assert versions.partition_keys == ["created_at"]
        assert gems.partition_mode is None
        assert gems.partition_keys is None

    def test_invalid_gems_raise(self):
        with pytest.raises(ValueError):
            rubygems_source("gems", "", structlog.get_logger())


class TestPerGemTables:
    @parameterized.expand(
        [
            (
                "owners",
                "owners.json",
                [{"id": 1, "handle": "qrush", "role": "owner"}, {"handle": "no-id"}, "not-a-dict"],
                [{"id": 1, "handle": "qrush", "role": "owner", "gem_name": "rails"}],
            ),
            (
                "reverse_dependencies",
                "reverse_dependencies.json",
                ["jeweler", "", None, "soup"],
                [
                    {"gem_name": "rails", "dependent_name": "jeweler"},
                    {"gem_name": "rails", "dependent_name": "soup"},
                ],
            ),
        ]
    )
    def test_rows_are_stamped_with_the_gem_and_404_gems_are_skipped(self, endpoint, suffix, body, expected_rows):
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails\nnope"))

        result = driver.run(endpoint, [ScriptedResponse(json=body), ScriptedResponse(status=404, json={})])

        assert result.raised is None
        assert result.paths == [f"/api/v1/gems/rails/{suffix}", f"/api/v1/gems/nope/{suffix}"]
        assert result.rows == expected_rows


class TestFeedTables:
    @parameterized.expand(
        [
            (
                "latest_gems",
                "/api/v1/activity/latest.json",
                [{"name": "brand-new", "version": "0.1.0"}, {"version": "no-name"}],
                [{"name": "brand-new", "version": "0.1.0"}],
            ),
            (
                "just_updated_gems",
                "/api/v1/activity/just_updated.json",
                [
                    {"name": "nokogiri", "version": "1.18.0", "platform": "ruby"},
                    {"name": "nokogiri", "version": "1.18.0", "platform": "java"},
                    {"name": "nokogiri", "version": "1.18.0", "platform": None},
                ],
                [
                    {"name": "nokogiri", "version": "1.18.0", "platform": "ruby"},
                    {"name": "nokogiri", "version": "1.18.0", "platform": "java"},
                ],
            ),
        ]
    )
    def test_one_request_ignores_configured_gems_and_drops_rows_without_a_key(self, endpoint, path, body, expected):
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails\nrspec"))

        result = driver.run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.paths == [path]
        assert result.rows == expected


def _timeframe_page(count: int, created_at: str = "2026-11-01T00:00:00.000Z") -> list[dict[str, Any]]:
    return [{"name": f"gem{i}", "number": "1.0.0", "platform": "ruby", "created_at": created_at} for i in range(count)]


class TestTimeframeVersions:
    @pytest.fixture(autouse=True)
    def _frozen_now(self):
        with time_machine.travel(dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC), tick=False):
            yield

    @parameterized.expand(
        [
            ("incremental_watermark", True, "2026-11-01T06:30:00.000Z", None, "2026-11-01T06:30:00Z"),
            (
                "full_refresh_uses_history_start",
                False,
                "2026-11-01T06:30:00Z",
                dt.datetime(2026, 10, 30, tzinfo=dt.UTC),
                "2026-10-30T00:00:00Z",
            ),
            (
                "incremental_without_watermark_uses_history_start",
                True,
                None,
                dt.datetime(2026, 10, 30, tzinfo=dt.UTC),
                "2026-10-30T00:00:00Z",
            ),
            ("no_bound_falls_back_to_lookback", False, None, None, "2026-10-27T12:00:00Z"),
        ]
    )
    def test_start_of_the_read(self, _name, incremental, last_value, history_start, expected_from):
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails"))

        result = driver.run(
            "timeframe_versions",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=incremental,
            incremental_field="created_at",
            db_incremental_field_last_value=last_value,
            history_start=history_start,
        )

        assert result.raised is None
        assert result.params("from") == [expected_from]
        assert result.params("to") == ["2026-11-03T12:00:00Z"]

    def test_walks_pages_and_seven_day_windows_to_now(self):
        driver = SourceDriver(RubygemsSource(), RubygemsSourceConfig(gems="rails"))

        result = driver.run(
            "timeframe_versions",
            [
                # First window: a full page, then a short page ends it.
                ScriptedResponse(json=_timeframe_page(TIMEFRAME_PAGE_SIZE)),
                ScriptedResponse(json=[*_timeframe_page(2), {"name": "no-platform", "number": "1.0.0"}]),
                # Second window: an empty first page ends it, and the walk stops at now.
                ScriptedResponse(json=[]),
            ],
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value="2026-10-27T00:00:00Z",
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/timeframe_versions.json"] * 3
        assert result.params("from") == ["2026-10-27T00:00:00Z", "2026-10-27T00:00:00Z", "2026-11-03T00:00:00Z"]
        assert result.params("to") == ["2026-11-03T00:00:00Z", "2026-11-03T00:00:00Z", "2026-11-03T12:00:00Z"]
        assert result.params("page") == ["1", "2", "1"]
        assert len(result.rows) == TIMEFRAME_PAGE_SIZE + 2
        assert result.response is not None
        assert result.response.sort_mode is None
        assert result.response.partition_keys == ["created_at"]
