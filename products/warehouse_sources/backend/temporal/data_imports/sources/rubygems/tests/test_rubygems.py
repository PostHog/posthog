import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.rubygems import (
    MAX_GEMS,
    RUBYGEMS_BASE_URL,
    RubyGemsRetryableError,
    _fetch,
    get_rows,
    parse_gems,
    rubygems_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.rubygems"


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
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("rails")

        assert is_valid is expected_valid

    def test_empty_gems_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("rails")

        assert is_valid is False
        assert message is not None


class TestGetRows:
    def test_yields_a_batch_per_gem_and_skips_404(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _gem_document(name="rails")),
                _response(404),
                _response(200, _gem_document(name="rspec")),
            ]

            batches = list(get_rows("gems", ["rails", "nope", "rspec"], structlog.get_logger()))

        # The 404 gem is skipped, so only two batches come back.
        assert len(batches) == 2
        assert batches[0][0]["name"] == "rails"
        assert batches[1][0]["name"] == "rspec"

    def test_chunks_large_version_history(self, monkeypatch):
        # A gem with a large version history must not be yielded as one oversized list; it's split
        # into bounded chunks so downstream Arrow conversion stays capped.
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 1)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, _versions_document(name="rails"))

            batches = list(get_rows("versions", ["rails"], structlog.get_logger()))

        # The document has 2 valid version rows; at 1 row per chunk that's [1, 1].
        assert [len(b) for b in batches] == [1, 1]


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
