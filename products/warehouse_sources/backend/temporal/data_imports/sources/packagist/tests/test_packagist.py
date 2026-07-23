import json
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.packagist import (
    MAX_PACKAGES,
    PACKAGIST_BASE_URL,
    PackagistResumeConfig,
    PackagistRetryableError,
    _advisory_rows,
    _download_rows,
    _fetch_json,
    _format_from_date,
    _package_rows,
    _package_url,
    _version_rows,
    expand_vendors,
    get_rows,
    packagist_source,
    parse_packages,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.settings import PACKAGIST_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.packagist.packagist"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {PACKAGIST_BASE_URL}", response=requests.Response()
        )
    return resp


def _metadata_document(name: str = "monolog/monolog") -> dict[str, Any]:
    return {
        "package": {
            "name": name,
            "description": "Logging for PHP",
            "time": "2011-09-27T00:35:19+00:00",
            "downloads": {"total": 100, "monthly": 10, "daily": 1},
            "versions": {
                "3.10.0": {"name": name, "version": "3.10.0", "time": "2025-01-01T00:00:00+00:00"},
                "dev-main": {"name": name, "version": "dev-main", "time": "2026-07-01T00:00:00+00:00"},
                "bad": "not-a-dict",
            },
        }
    }


def _stats_document(name: str = "monolog/monolog") -> dict[str, Any]:
    return {
        "labels": ["2026-07-01", "2026-07-02"],
        "values": {name: [678190, 695724]},
        "average": "daily",
    }


def _advisories_document() -> dict[str, Any]:
    return {
        "advisories": {
            "monolog/monolog": [
                {"advisoryId": "PKSA-1", "packageName": "monolog/monolog", "title": "Header injection"},
                {"packageName": "monolog/monolog", "title": "missing id, skipped"},
            ],
            "empty/package": "not-a-list",
        }
    }


class _FakeResumableManager:
    def __init__(self, state: PackagistResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PackagistResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PackagistResumeConfig | None:
        return self._state

    def save_state(self, data: PackagistResumeConfig) -> None:
        self.saved.append(data)


class TestParsePackages:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("monolog/monolog", ["monolog/monolog"]),
            ("monolog/monolog\nsymfony/console", ["monolog/monolog", "symfony/console"]),
            ("monolog/monolog, symfony/console", ["monolog/monolog", "symfony/console"]),
            # A bare vendor token is kept as-is for sync-time expansion.
            ("symfony", ["symfony"]),
            # Composer names are lowercase; user input is normalized before validation.
            ("Monolog/Monolog", ["monolog/monolog"]),
            ("monolog/monolog\nMONOLOG/MONOLOG", ["monolog/monolog"]),
            ("monolog/monolog\n\n  \nsymfony", ["monolog/monolog", "symfony"]),
            # Separator shapes Composer allows: `.`/`_`/`-` in both halves, `--` in the package half.
            ("my-vendor/my_package.name", ["my-vendor/my_package.name"]),
            ("vendor.name/pkg--name", ["vendor.name/pkg--name"]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_packages(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , "])
    def test_empty_raises(self, raw):
        with pytest.raises(ValueError):
            parse_packages(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            # Path-traversal or URL-breaking tokens must be rejected, not fetched.
            "../etc/passwd",
            "monolog/mono/log",
            "monolog/",
            "/monolog",
            "monolog monolog",
            "a--b",
            # Long almost-valid tokens must be rejected in linear time — with ambiguous nested
            # quantifiers in the name regexes these hang the API worker (ReDoS) instead.
            "a" * 5000 + "!",
            "vendor/" + "a" * 5000 + "!",
        ],
    )
    def test_malformed_raises(self, raw):
        with pytest.raises(ValueError):
            parse_packages(raw)

    def test_rejects_too_many_entries(self):
        raw = "\n".join(f"vendor{i}/pkg" for i in range(MAX_PACKAGES + 1))
        with pytest.raises(ValueError, match="Too many entries"):
            parse_packages(raw)


class TestExpandVendors:
    def test_expands_vendor_tokens_and_passes_packages_through(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"packageNames": ["symfony/console", "symfony/yaml"]})

        packages = expand_vendors(session, ["monolog/monolog", "symfony", "symfony/console"], structlog.get_logger())

        # Vendor expands in place; the duplicate of an already-expanded package is dropped.
        assert packages == ["monolog/monolog", "symfony/console", "symfony/yaml"]
        session.get.assert_called_once()
        assert "vendor=symfony" in session.get.call_args[0][0]

    def test_unknown_vendor_is_skipped(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"packageNames": []})

        packages = expand_vendors(session, ["ghost-vendor", "monolog/monolog"], structlog.get_logger())

        assert packages == ["monolog/monolog"]

    def test_expansion_is_capped(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.MAX_PACKAGES", 3)
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"packageNames": [f"big/pkg{i}" for i in range(10)]})

        packages = expand_vendors(session, ["big"], structlog.get_logger())

        assert packages == ["big/pkg0", "big/pkg1", "big/pkg2"]


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_json.__wrapped__  # type: ignore[attr-defined]


class TestFetchJson:
    def test_404_returns_none(self):
        session = mock.MagicMock()
        session.get.return_value = _response(404)

        assert _fetch_once(session, "https://packagist.org/x", structlog.get_logger()) is None

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(PackagistRetryableError):
            _fetch_once(session, "https://packagist.org/x", structlog.get_logger())

    def test_other_client_error_raises(self):
        session = mock.MagicMock()
        session.get.return_value = _response(400)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "https://packagist.org/x", structlog.get_logger())


class TestRowBuilders:
    def test_package_rows_drop_versions(self):
        rows = list(_package_rows(_metadata_document()))

        assert len(rows) == 1
        assert rows[0]["name"] == "monolog/monolog"
        assert "versions" not in rows[0]

    def test_package_rows_skip_document_without_name(self):
        assert list(_package_rows({"package": {}})) == []

    def test_version_rows_stamp_package_and_skip_malformed(self):
        rows = list(_version_rows("monolog/monolog", _metadata_document()))

        # The "bad" (non-dict) version entry is skipped.
        assert {(r["package"], r["version"]) for r in rows} == {
            ("monolog/monolog", "3.10.0"),
            ("monolog/monolog", "dev-main"),
        }

    def test_download_rows_zip_labels_and_values(self):
        rows = list(_download_rows("monolog/monolog", _stats_document()))

        assert rows == [
            {"package": "monolog/monolog", "date": "2026-07-01", "downloads": 678190},
            {"package": "monolog/monolog", "date": "2026-07-02", "downloads": 695724},
        ]

    def test_download_rows_fall_back_to_single_values_entry(self):
        # Packagist keys `values` by its canonical spelling, which can differ from the requested
        # token; with exactly one entry the mismatch must not drop the whole stream.
        document = {"labels": ["2026-07-01"], "values": {"Monolog/Monolog": [5]}}

        rows = list(_download_rows("monolog/monolog", document))

        assert rows == [{"package": "monolog/monolog", "date": "2026-07-01", "downloads": 5}]

    def test_advisory_rows_flatten_and_require_advisory_id(self):
        rows = list(_advisory_rows(_advisories_document()))

        assert len(rows) == 1
        assert rows[0]["advisoryId"] == "PKSA-1"


class TestFormatFromDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2026-07-01", "2026-07-01"),
            ("2026-07-01T12:34:56+00:00", "2026-07-01"),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_strings(self, value, expected):
        assert _format_from_date(value) == expected

    def test_date_and_datetime(self):
        from datetime import date, datetime

        assert _format_from_date(date(2026, 7, 1)) == "2026-07-01"
        assert _format_from_date(datetime(2026, 7, 1, 12, 30)) == "2026-07-01"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_package_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status, {"package": {"name": "monolog/monolog"}})

            is_valid, _ = validate_credentials("monolog/monolog")

        assert is_valid is expected_valid

    def test_vendor_with_no_packages_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"packageNames": []})

            is_valid, message = validate_credentials("ghost-vendor")

        assert is_valid is False
        assert message is not None and "ghost-vendor" in message

    def test_empty_config_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("monolog/monolog")

        assert is_valid is False
        assert message is not None


class TestGetRows:
    def _run(
        self,
        endpoint: str,
        responses: list[mock.MagicMock],
        manager: _FakeResumableManager | None = None,
        tokens: list[str] | None = None,
        **kwargs: Any,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock, _FakeResumableManager]:
        manager = manager or _FakeResumableManager()
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = responses
            batches = list(
                get_rows(
                    endpoint,
                    tokens or ["monolog/monolog", "symfony/console"],
                    structlog.get_logger(),
                    manager,  # type: ignore[arg-type]
                    **kwargs,
                )
            )
        return batches, mock_session.return_value, manager

    def test_yields_per_package_and_skips_404(self):
        batches, _, _ = self._run(
            "packages",
            [
                _response(200, _metadata_document("monolog/monolog")),
                _response(404),
            ],
        )

        assert len(batches) == 1
        assert batches[0][0]["name"] == "monolog/monolog"

    def test_saves_state_after_each_package(self):
        _, _, manager = self._run(
            "packages",
            [
                _response(200, _metadata_document("monolog/monolog")),
                _response(200, _metadata_document("symfony/console")),
            ],
        )

        assert manager.saved == [
            PackagistResumeConfig(next_package_index=1),
            PackagistResumeConfig(next_package_index=2),
        ]

    def test_resumes_from_saved_state(self):
        batches, session, _ = self._run(
            "packages",
            [_response(200, _metadata_document("symfony/console"))],
            manager=_FakeResumableManager(PackagistResumeConfig(next_package_index=1)),
        )

        # Only the second package is fetched; the first was completed before the crash.
        session.get.assert_called_once()
        assert session.get.call_args[0][0] == _package_url("symfony/console")
        assert batches[0][0]["name"] == "symfony/console"

    def test_downloads_passes_from_param_only_when_incremental(self):
        _, session, _ = self._run(
            "downloads",
            [_response(200, _stats_document())],
            tokens=["monolog/monolog"],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01",
        )
        query = parse_qs(urlparse(session.get.call_args[0][0]).query)
        assert query == {"average": ["daily"], "from": ["2026-07-01"]}

        _, session, _ = self._run(
            "downloads",
            [_response(200, _stats_document())],
            tokens=["monolog/monolog"],
            should_use_incremental_field=False,
        )
        query = parse_qs(urlparse(session.get.call_args[0][0]).query)
        assert query == {"average": ["daily"]}

    def test_advisories_are_batched_and_state_advances_by_batch(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.ADVISORIES_BATCH_SIZE", 2)
        tokens = ["a/one", "b/two", "c/three"]

        batches, session, manager = self._run(
            "security_advisories",
            [_response(200, _advisories_document()), _response(200, {"advisories": {}})],
            tokens=tokens,
        )

        assert session.get.call_count == 2
        first_query = parse_qs(urlparse(session.get.call_args_list[0][0][0]).query)
        assert first_query == {"packages[]": ["a/one", "b/two"]}
        assert manager.saved == [
            PackagistResumeConfig(next_package_index=2),
            PackagistResumeConfig(next_package_index=3),
        ]
        assert len(batches) == 1

    def test_chunks_large_row_sets(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 1)

        batches, _, _ = self._run(
            "downloads",
            [_response(200, _stats_document())],
            tokens=["monolog/monolog"],
        )

        # The stats document has 2 days; at 1 row per chunk that's two batches.
        assert [len(b) for b in batches] == [1, 1]


class TestPackagistSource:
    @pytest.mark.parametrize("endpoint", list(PACKAGIST_ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = packagist_source(endpoint, "monolog/monolog", structlog.get_logger(), _FakeResumableManager())  # type: ignore[arg-type]

        assert response.name == endpoint
        assert response.primary_keys == PACKAGIST_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    def test_only_downloads_is_partitioned(self):
        downloads = packagist_source("downloads", "monolog/monolog", structlog.get_logger(), _FakeResumableManager())  # type: ignore[arg-type]
        packages = packagist_source("packages", "monolog/monolog", structlog.get_logger(), _FakeResumableManager())  # type: ignore[arg-type]

        assert downloads.partition_mode == "datetime"
        assert downloads.partition_keys == ["date"]
        assert packages.partition_mode is None
        assert packages.partition_keys is None

    def test_invalid_packages_raise(self):
        with pytest.raises(ValueError):
            packagist_source("packages", "", structlog.get_logger(), _FakeResumableManager())  # type: ignore[arg-type]
