from datetime import UTC, date, datetime

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry import (
    NpmRegistryResumeConfig,
    _fetch_json,
    _first_license,
    _to_date,
    parse_packages,
    validate_packages,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import MAX_PACKAGES
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source import NpmRegistrySource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry"


def _driver(package_names: str = "react") -> SourceDriver:
    return SourceDriver(NpmRegistrySource(), NpmRegistrySourceConfig(package_names=package_names))


class TestParsePackages:
    @pytest.mark.parametrize("raw", [None, "", "   ", ",,\n,"])
    def test_raises_on_empty_input(self, raw: str | None):
        with pytest.raises(ValueError, match="At least one package name is required"):
            parse_packages(raw)

    def test_raises_when_over_the_cap(self):
        raw = ",".join(f"pkg{i}" for i in range(MAX_PACKAGES + 1))
        with pytest.raises(ValueError, match="Too many packages"):
            parse_packages(raw)


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


class TestFirstLicense:
    def test_empty_array(self):
        assert _first_license([]) is None


class TestGetRowsDownloads:
    @time_machine.travel("2024-02-15", tick=False)
    def test_incremental_starts_the_day_after_the_watermark(self) -> None:
        result = _driver().run(
            "Downloads",
            [ScriptedResponse(json={"downloads": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 2, 1),
        )

        assert result.raised is None
        assert result.paths == ["/downloads/range/2024-02-02:2024-02-15/react"]

    @time_machine.travel("2024-02-15", tick=False)
    def test_resume_starts_from_saved_package_and_window(self) -> None:
        result = _driver("react\nlodash").run(
            "Downloads",
            [ScriptedResponse(json={"downloads": []})],
            resume_state=NpmRegistryResumeConfig(package_index=1, window_start="2024-02-10"),
        )

        # `react` (index 0) is skipped entirely; `lodash` resumes from the saved window.
        assert result.raised is None
        assert result.paths == ["/downloads/range/2024-02-10:2024-02-15/lodash"]

    @time_machine.travel("2024-02-15", tick=False)
    def test_missing_package_is_skipped_without_raising(self) -> None:
        result = _driver("this-package-does-not-exist").run("Downloads", [ScriptedResponse(status=404)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    @time_machine.travel("2024-02-15", tick=False)
    def test_saves_state_after_each_window_and_advances_package_on_completion(self) -> None:
        result = _driver().run(
            "Downloads", always(ScriptedResponse(json={"downloads": [{"day": "2015-01-10", "downloads": 1}]}))
        )

        # Final call always advances to the next package index with no in-progress window.
        assert result.raised is None
        assert len(result.requests) > 1
        assert len(result.saved_states) == len(result.requests)
        assert result.saved_states[-1] == NpmRegistryResumeConfig(package_index=1)
        assert result.committed_states == result.saved_states[:-1]


class TestGetRowsVersions:
    def test_extracts_one_row_per_version(self) -> None:
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
        result = _driver().run("Versions", [ScriptedResponse(json=document)])
        assert result.raised is None
        rows = {row["version"]: row for row in result.rows}

        assert rows["1.0.0"]["package"] == "react"
        assert rows["1.0.0"]["published_at"] == "2020-01-01T00:00:00.000Z"
        assert rows["1.0.0"]["is_latest"] is False
        assert rows["1.0.0"]["license"] == "MIT"
        assert rows["1.0.0"]["node_engine"] == ">=10"

        assert rows["1.1.0"]["is_latest"] is True
        assert rows["1.1.0"]["deprecated"] == "use 2.x instead"
        # Legacy `licenses` array falls back to its first entry's type.
        assert rows["1.1.0"]["license"] == "ISC"

    def test_missing_package_is_skipped_without_raising(self) -> None:
        result = _driver("this-package-does-not-exist").run("Versions", [ScriptedResponse(status=404)])

        assert result.raised is None
        assert result.rows == []


class TestGetRowsVersionDownloads:
    @pytest.mark.parametrize(
        "response,expected_rows",
        [
            (
                ScriptedResponse(json={"package": "react", "downloads": {"1.0.0": 12, "1.0.1": 0, "1.0.2": None}}),
                [
                    {"package": "react", "version": "1.0.0", "downloads": 12},
                    {"package": "react", "version": "1.0.1", "downloads": 0},
                ],
            ),
            # An unknown package returns 200 with an empty map.
            (ScriptedResponse(json={"package": "react", "downloads": {}}), []),
            (ScriptedResponse(json={"error": "not found"}), []),
            (ScriptedResponse(status=404), []),
        ],
    )
    def test_row_shaping(self, response: ScriptedResponse, expected_rows: list[dict]) -> None:
        result = _driver().run("VersionDownloads", [response])

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths == ["/versions/react/last-week"]

    def test_walks_every_package_and_encodes_scoped_names(self) -> None:
        result = _driver("@scope/name\nlodash").run(
            "VersionDownloads",
            [
                ScriptedResponse(json={"package": "@scope/name", "downloads": {"1.0.0": 3}}),
                ScriptedResponse(json={"package": "lodash", "downloads": {"4.0.0": 9}}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/versions/%40scope%2Fname/last-week", "/versions/lodash/last-week"]
        assert result.rows == [
            {"package": "@scope/name", "version": "1.0.0", "downloads": 3},
            {"package": "lodash", "version": "4.0.0", "downloads": 9},
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
    def test_probes_first_configured_package(self, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, _ = validate_packages("react\nlodash")

        assert ok is expected_ok
        # Only the first configured package is probed.
        assert {request.path for request in network.requests_log} == {"/downloads/point/last-day/react"}

    def test_network_failure_returns_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, message = validate_packages("react")

        assert ok is False
        assert message is not None and "Could not reach" in message
        assert {request.path for request in network.requests_log} == {"/downloads/point/last-day/react"}


class TestNpmRegistrySourceResponse:
    @pytest.mark.parametrize(
        "endpoint,primary_keys,partition_key",
        [
            ("Downloads", ["package", "day"], "day"),
            ("Versions", ["package", "version"], "published_at"),
        ],
    )
    @time_machine.travel("2024-02-15", tick=False)
    def test_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"downloads": []} if endpoint == "Downloads" else {"versions": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 2, 14),
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"
