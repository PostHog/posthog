from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.packagist import (
    PackagistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.packagist import (
    MAX_PACKAGES,
    PackagistResumeConfig,
    PackagistRetryableError,
    _download_rows,
    _format_from_date,
    _package_rows,
    _version_rows,
    parse_packages,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source import PackagistSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.packagist.packagist"


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


def _driver(packages: str = "monolog/monolog\nsymfony/console") -> SourceDriver:
    return SourceDriver(PackagistSource(), PackagistSourceConfig(packages=packages))


class TestParsePackages:
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
        result = _driver("monolog/monolog\nsymfony\nsymfony/console").run(
            "packages",
            [
                ScriptedResponse(json={"packageNames": ["symfony/console", "symfony/yaml"]}),
                ScriptedResponse(json=_metadata_document("monolog/monolog")),
                ScriptedResponse(json=_metadata_document("symfony/console")),
                ScriptedResponse(json=_metadata_document("symfony/yaml")),
            ],
        )

        # Vendor expands in place; the duplicate of an already-expanded package is dropped.
        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["monolog/monolog", "symfony/console", "symfony/yaml"]
        assert result.requests[0].param("vendor") == "symfony"
        assert result.paths == [
            "/packages/list.json",
            "/packages/monolog/monolog.json",
            "/packages/symfony/console.json",
            "/packages/symfony/yaml.json",
        ]

    def test_unknown_vendor_is_skipped(self):
        result = _driver("ghost-vendor\nmonolog/monolog").run(
            "packages",
            [
                ScriptedResponse(json={"packageNames": []}),
                ScriptedResponse(json=_metadata_document()),
            ],
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["monolog/monolog"]
        assert result.paths == ["/packages/list.json", "/packages/monolog/monolog.json"]

    def test_expansion_is_capped(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.MAX_PACKAGES", 3)
        result = _driver("big").run(
            "packages",
            [
                ScriptedResponse(json={"packageNames": [f"big/pkg{i}" for i in range(10)]}),
                *(ScriptedResponse(json=_metadata_document(f"big/pkg{i}")) for i in range(3)),
            ],
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["big/pkg0", "big/pkg1", "big/pkg2"]
        assert result.paths == [
            "/packages/list.json",
            "/packages/big/pkg0.json",
            "/packages/big/pkg1.json",
            "/packages/big/pkg2.json",
        ]


class TestFetchJson:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        result = _driver("monolog/monolog").run("packages", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, PackagistRetryableError)
        assert set(result.paths) == {"/packages/monolog/monolog.json"}

    def test_other_client_error_raises(self):
        result = _driver("monolog/monolog").run("packages", [ScriptedResponse(status=400)])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/packages/monolog/monolog.json"]


class TestRowBuilders:
    def test_package_rows_skip_document_without_name(self):
        assert list(_package_rows({"package": {}})) == []

    def test_version_rows_stamp_package_and_skip_malformed(self):
        rows = list(_version_rows("monolog/monolog", _metadata_document()))

        # The "bad" (non-dict) version entry is skipped.
        assert {(r["package"], r["version"]) for r in rows} == {
            ("monolog/monolog", "3.10.0"),
            ("monolog/monolog", "dev-main"),
        }

    def test_download_rows_fall_back_to_single_values_entry(self):
        # Packagist keys `values` by its canonical spelling, which can differ from the requested
        # token; with exactly one entry the mismatch must not drop the whole stream.
        document = {"labels": ["2026-07-01"], "values": {"Monolog/Monolog": [5]}}

        rows = list(_download_rows("monolog/monolog", document))

        assert rows == [{"package": "monolog/monolog", "date": "2026-07-01", "downloads": 5}]


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
        ],
    )
    def test_package_status_mapping(self, status, expected_valid):
        with scripted_network(
            [ScriptedResponse(status=status, json={"package": {"name": "monolog/monolog"}})]
        ) as network:
            is_valid, _ = validate_credentials("monolog/monolog")

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/packages/monolog/monolog.json"}

    def test_vendor_with_no_packages_is_invalid(self):
        with scripted_network([ScriptedResponse(json={"packageNames": []})]) as network:
            is_valid, message = validate_credentials("ghost-vendor")

        assert is_valid is False
        assert message is not None and "ghost-vendor" in message
        assert network.requests_log[0].param("vendor") == "ghost-vendor"

    def test_empty_config_is_invalid_without_request(self):
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self):
        with scripted_network([ConnectionError("boom")]) as network:
            is_valid, message = validate_credentials("monolog/monolog")

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/packages/monolog/monolog.json"}


class TestGetRows:
    def test_yields_per_package_and_skips_404(self):
        result = _driver().run(
            "packages",
            [
                ScriptedResponse(json=_metadata_document("monolog/monolog")),
                ScriptedResponse(status=404),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert result.items[0][0]["name"] == "monolog/monolog"
        assert result.paths == ["/packages/monolog/monolog.json", "/packages/symfony/console.json"]

    def test_resumes_from_saved_state(self):
        result = _driver().run(
            "packages",
            [ScriptedResponse(json=_metadata_document("symfony/console"))],
            resume_state=PackagistResumeConfig(next_package_index=1),
        )

        # Only the second package is fetched; the first was completed before the crash.
        assert result.raised is None
        assert result.paths == ["/packages/symfony/console.json"]
        assert result.rows[0]["name"] == "symfony/console"

    def test_downloads_passes_from_param_only_when_incremental(self):
        result = _driver("monolog/monolog").run(
            "downloads",
            [ScriptedResponse(json=_stats_document())],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01",
        )
        assert result.raised is None
        assert result.queries == [{"average": ("daily",), "from": ("2026-07-01",)}]

        result = _driver("monolog/monolog").run(
            "downloads",
            [ScriptedResponse(json=_stats_document())],
            should_use_incremental_field=False,
        )
        assert result.raised is None
        assert result.queries == [{"average": ("daily",)}]

    def test_advisories_are_batched_and_state_advances_by_batch(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.ADVISORIES_BATCH_SIZE", 2)
        tokens = ["a/one", "b/two", "c/three"]

        result = _driver("\n".join(tokens)).run(
            "security_advisories",
            [ScriptedResponse(json=_advisories_document()), ScriptedResponse(json={"advisories": {}})],
        )

        assert result.raised is None
        assert result.paths == ["/api/security-advisories/", "/api/security-advisories/"]
        assert result.queries[0] == {"packages[]": ("a/one", "b/two")}
        assert result.saved_states == [
            PackagistResumeConfig(next_package_index=2),
            PackagistResumeConfig(next_package_index=3),
        ]
        assert len(result.items) == 1

    def test_chunks_large_row_sets(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 1)

        result = _driver("monolog/monolog").run(
            "downloads",
            [ScriptedResponse(json=_stats_document())],
        )

        # The stats document has 2 days; at 1 row per chunk that's two batches.
        assert result.raised is None
        assert [len(batch) for batch in result.items] == [1, 1]


class TestPackagistSource:
    def test_only_downloads_is_partitioned(self):
        driver = _driver("monolog/monolog")
        downloads = driver.run("downloads", [ScriptedResponse(json=_stats_document())]).response
        packages = driver.run("packages", [ScriptedResponse(json=_metadata_document())]).response

        assert downloads is not None
        assert packages is not None
        assert downloads.partition_mode == "datetime"
        assert downloads.partition_keys == ["date"]
        assert packages.partition_mode is None
        assert packages.partition_keys is None

    def test_invalid_packages_raise(self):
        result = _driver("").run("packages", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []
