from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry import (
    NpmRegistryResumeConfig,
    _encode_package,
    _fetch_json,
    _first_download_window_start,
    _first_license,
    _to_date,
    get_rows,
    npm_registry_source,
    parse_packages,
    validate_packages,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import MAX_PACKAGES

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry"


def _manager(resume: NpmRegistryResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestParsePackages:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("react", ["react"]),
            ("react,lodash", ["react", "lodash"]),
            ("react\nlodash", ["react", "lodash"]),
            ("react, lodash , vue\n", ["react", "lodash", "vue"]),
            ("@slack/client,react", ["@slack/client", "react"]),
            ("react,react,lodash", ["react", "lodash"]),  # de-duplicated, order preserved
            ("react,, ,lodash", ["react", "lodash"]),  # blank tokens skipped
        ],
    )
    def test_parses_delimited_names(self, raw: str, expected: list[str]):
        assert parse_packages(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", ",,\n,"])
    def test_raises_on_empty_input(self, raw: str | None):
        with pytest.raises(ValueError, match="At least one package name is required"):
            parse_packages(raw)

    def test_raises_when_over_the_cap(self):
        raw = ",".join(f"pkg{i}" for i in range(MAX_PACKAGES + 1))
        with pytest.raises(ValueError, match="Too many packages"):
            parse_packages(raw)

    def test_at_the_cap_is_allowed(self):
        raw = ",".join(f"pkg{i}" for i in range(MAX_PACKAGES))
        assert len(parse_packages(raw)) == MAX_PACKAGES


class TestEncodePackage:
    @pytest.mark.parametrize(
        "package,expected",
        [
            ("react", "react"),
            ("@slack/client", "%40slack%2Fclient"),
        ],
    )
    def test_percent_encodes_scoped_names(self, package: str, expected: str):
        assert _encode_package(package) == expected


class TestToDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC), date(2024, 3, 4)),
            (datetime(2024, 3, 4, 23, 0, 0), date(2024, 3, 4)),
            (date(2024, 3, 4), date(2024, 3, 4)),
            ("2024-03-04T05:06:07", date(2024, 3, 4)),
            ("2024-03-04", date(2024, 3, 4)),
        ],
    )
    def test_to_date(self, value, expected):
        assert _to_date(value) == expected

    @pytest.mark.parametrize("value", ["2024-01", "not-a-date"])
    def test_raises_on_unparseable_fragment(self, value: str):
        with pytest.raises(ValueError, match="Could not derive a yyyy-mm-dd date"):
            _to_date(value)


class TestFirstDownloadWindowStart:
    def test_resume_state_wins(self):
        result = _first_download_window_start("2024-06-01", True, date(2024, 1, 1))
        assert result == date(2024, 6, 1)

    def test_incremental_starts_the_day_after_the_watermark(self):
        result = _first_download_window_start(None, True, date(2024, 1, 1))
        assert result == date(2024, 1, 2)

    def test_first_sync_starts_at_the_earliest_available_date(self):
        result = _first_download_window_start(None, False, None)
        assert result == date(2015, 1, 10)


class TestFirstLicense:
    def test_modern_manifest_has_no_licenses_array(self):
        assert _first_license(None) is None

    def test_legacy_licenses_array(self):
        assert _first_license([{"type": "MIT", "url": "http://example.com"}]) == "MIT"

    def test_empty_array(self):
        assert _first_license([]) is None


class TestGetRowsDownloads:
    @freeze_time("2016-08-01")
    def test_windows_date_range_into_chunks(self):
        # First 540-day window from EARLIEST_DOWNLOAD_DATE runs 2015-01-10..2016-07-02; the second
        # window then starts 2016-07-03 and is clamped to "today" (frozen at 2016-08-01).
        body_by_start = {
            "2015-01-10": {"downloads": [{"day": "2015-01-10", "downloads": 5}]},
            "2016-07-03": {"downloads": [{"day": "2016-07-03", "downloads": 9}]},
        }

        def fake_fetch(_session, url, _logger, _timeout):
            for start, body in body_by_start.items():
                if f"/{start}:" in url:
                    return body
            raise AssertionError(f"unexpected url: {url}")

        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch_json", side_effect=fake_fetch) as fetch:
            batches = list(
                get_rows(
                    endpoint="Downloads",
                    packages=["react"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        rows = [row for batch in batches for row in batch]
        assert rows == [
            {"package": "react", "day": "2015-01-10", "downloads": 5},
            {"package": "react", "day": "2016-07-03", "downloads": 9},
        ]
        assert fetch.call_count == 2

    @freeze_time("2024-02-15")
    def test_incremental_starts_the_day_after_the_watermark(self):
        with mock.patch(f"{_MODULE}._fetch_json", return_value={"downloads": []}) as fetch:
            list(
                get_rows(
                    endpoint="Downloads",
                    packages=["react"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2024, 2, 1),
                )
            )
        assert "2024-02-02:2024-02-15" in fetch.call_args_list[0].args[1]

    @freeze_time("2024-02-15")
    def test_resume_starts_from_saved_package_and_window(self):
        with mock.patch(f"{_MODULE}._fetch_json", return_value={"downloads": []}) as fetch:
            list(
                get_rows(
                    endpoint="Downloads",
                    packages=["react", "lodash"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(
                        NpmRegistryResumeConfig(package_index=1, window_start="2024-02-10")
                    ),
                )
            )
        # `react` (index 0) is skipped entirely; `lodash` resumes from the saved window.
        assert len(fetch.call_args_list) == 1
        url = fetch.call_args_list[0].args[1]
        assert "lodash" in url
        assert "2024-02-10:2024-02-15" in url

    @freeze_time("2024-02-15")
    def test_missing_package_is_skipped_without_raising(self):
        with mock.patch(f"{_MODULE}._fetch_json", return_value=None) as fetch:
            batches = list(
                get_rows(
                    endpoint="Downloads",
                    packages=["this-package-does-not-exist"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        assert batches == []
        assert fetch.call_count == 1

    @freeze_time("2024-02-15")
    def test_saves_state_after_each_window_and_advances_package_on_completion(self):
        manager = _manager()
        with mock.patch(f"{_MODULE}._fetch_json", return_value={"downloads": [{"day": "2015-01-10", "downloads": 1}]}):
            list(
                get_rows(
                    endpoint="Downloads",
                    packages=["react"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        # Final call always advances to the next package index with no in-progress window.
        assert manager.save_state.call_args_list[-1] == mock.call(NpmRegistryResumeConfig(package_index=1))


class TestGetRowsVersions:
    def test_extracts_one_row_per_version(self):
        document = {
            "dist-tags": {"latest": "1.1.0"},
            "time": {"1.0.0": "2020-01-01T00:00:00.000Z", "1.1.0": "2021-01-01T00:00:00.000Z"},
            "versions": {
                "1.0.0": {
                    "version": "1.0.0",
                    "license": "MIT",
                    "description": "first",
                    "dist": {"tarball": "https://example.com/1.0.0.tgz", "shasum": "abc", "integrity": "sha512-abc"},
                    "engines": {"node": ">=10"},
                },
                "1.1.0": {
                    "version": "1.1.0",
                    "deprecated": "use 2.x instead",
                    "licenses": [{"type": "ISC"}],
                    "dist": {"tarball": "https://example.com/1.1.0.tgz"},
                },
            },
        }
        with mock.patch(f"{_MODULE}._fetch_json", return_value=document):
            batches = list(
                get_rows(
                    endpoint="Versions",
                    packages=["react"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        rows = {row["version"]: row for batch in batches for row in batch}

        assert rows["1.0.0"]["package"] == "react"
        assert rows["1.0.0"]["published_at"] == "2020-01-01T00:00:00.000Z"
        assert rows["1.0.0"]["is_latest"] is False
        assert rows["1.0.0"]["license"] == "MIT"
        assert rows["1.0.0"]["node_engine"] == ">=10"

        assert rows["1.1.0"]["is_latest"] is True
        assert rows["1.1.0"]["deprecated"] == "use 2.x instead"
        # Legacy `licenses` array falls back to its first entry's type.
        assert rows["1.1.0"]["license"] == "ISC"

    def test_missing_package_is_skipped_without_raising(self):
        with mock.patch(f"{_MODULE}._fetch_json", return_value=None):
            assert (
                list(
                    get_rows(
                        endpoint="Versions",
                        packages=["this-package-does-not-exist"],
                        logger=mock.MagicMock(),
                        resumable_source_manager=_manager(),
                    )
                )
                == []
            )

    def test_versions_advances_package_index_with_no_window(self):
        manager = _manager()
        document: dict[str, Any] = {"dist-tags": {}, "time": {}, "versions": {}}
        with mock.patch(f"{_MODULE}._fetch_json", return_value=document):
            list(
                get_rows(
                    endpoint="Versions",
                    packages=["react", "lodash"],
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        assert manager.save_state.call_args_list == [
            mock.call(NpmRegistryResumeConfig(package_index=1)),
            mock.call(NpmRegistryResumeConfig(package_index=2)),
        ]


class TestFetchJson:
    def _session(self, *, status: int, chunks: list[bytes]) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = 200 <= status < 400
        response.iter_content.return_value = iter(chunks)
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        session = mock.MagicMock()
        session.get.return_value = response
        return session

    def test_streams_and_parses_body(self):
        session = self._session(status=200, chunks=[b'{"versions":', b'{"1.0.0":1}}'])
        result = _fetch_json(session, "https://example.com/pkg", mock.MagicMock(), 60)
        assert result == {"versions": {"1.0.0": 1}}
        # stream=True keeps us from buffering the whole body up front.
        assert session.get.call_args.kwargs["stream"] is True

    def test_404_returns_none(self):
        session = self._session(status=404, chunks=[])
        assert _fetch_json(session, "https://example.com/missing", mock.MagicMock(), 60) is None

    def test_raises_when_body_exceeds_cap(self):
        # Two chunks over a tiny patched cap: the read must abort instead of buffering the whole body.
        session = self._session(status=200, chunks=[b"x" * 8, b"x" * 8])
        with mock.patch(f"{_MODULE}.MAX_RESPONSE_BYTES", 10):
            with pytest.raises(ValueError, match="exceeded the .*-byte limit"):
                _fetch_json(session, "https://example.com/huge", mock.MagicMock(), 60)


class TestValidatePackages:
    def test_empty_config_is_invalid(self):
        ok, message = validate_packages(None)
        assert ok is False
        assert message is not None and "At least one package name is required" in message

    @pytest.mark.parametrize(
        "status,expected_ok",
        [(200, True), (404, False), (500, False)],
    )
    def test_probes_first_configured_package(self, status: int, expected_ok: bool):
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            ok, _ = validate_packages("react\nlodash")
        assert ok is expected_ok
        # Only the first configured package is probed.
        assert "react" in session.get.call_args.args[0]

    def test_network_failure_returns_error(self):
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            ok, message = validate_packages("react")
        assert ok is False
        assert message is not None and "Could not reach" in message


class TestNpmRegistrySourceResponse:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("Downloads", ["package", "day"], "day"),
            ("Versions", ["package", "version"], "published_at"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = npm_registry_source(
            endpoint=endpoint,
            package_names="react",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"
