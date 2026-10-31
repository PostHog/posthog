from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko import (
    ClinikoResumeConfig,
    _to_iso8601,
    base_url,
    get_resource,
    shard_from_api_key,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.source import ClinikoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cliniko import (
    ClinikoSourceConfig,
)


class TestShardDetection:
    @pytest.mark.parametrize(
        ("api_key", "expected_shard"),
        [
            ("MS0xLWl4SzYYYYdtR3V2-au1", "au1"),
            ("MS0xLWl4SzYYYYdtR3V2-uk1", "uk1"),
            ("MS0xLWl4SzYYYYdtR3V2-ca1", "ca1"),
            ("MS0xLWl4SzYYYYdtR3V2-us12", "us12"),
            # Keys minted before sharding existed carry no suffix and default to au1.
            ("MS0xLWl4SzYYYYdtR3V2", "au1"),
            # A hyphen that isn't a valid shard suffix (e.g. inside a UUID-like key) is ignored.
            ("some-key-without-a-shard", "au1"),
        ],
    )
    def test_shard_from_api_key(self, api_key: str, expected_shard: str) -> None:
        assert shard_from_api_key(api_key) == expected_shard

    def test_base_url_derives_from_shard(self) -> None:
        assert base_url("test-key-uk1") == "https://api.uk1.cliniko.com/v1"
        assert base_url("test-key") == "https://api.au1.cliniko.com/v1"


class TestToIso8601:
    def test_aware_datetime_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        aware = datetime(2024, 1, 2, 13, 0, 0, tzinfo=timezone(timedelta(hours=10)))
        assert _to_iso8601(aware) == "2024-01-02T03:00:00Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _to_iso8601(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"


class TestGetResource:
    def test_incremental_sets_merge_disposition_and_filter(self) -> None:
        resource = get_resource("invoices", should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = cast(Endpoint, resource["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["sort"] == "updated_at:asc"
        # `params` values are typed as a resolve/incremental/Any union, so the
        # cast makes the runtime shape (an incremental filter dict, including `convert`) explicit.
        q_filter = cast(dict[str, Any], params["q[]"])
        assert q_filter["type"] == "incremental"
        assert q_filter["convert"](datetime(2024, 1, 1, tzinfo=UTC)) == "updated_at:>2024-01-01T00:00:00Z"


class TestClinikoSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ClinikoSource(), ClinikoSourceConfig(api_key="test-key-au1"))

    @staticmethod
    def _page(endpoint: str, rows: list[dict[str, str]], next_url: str | None = None) -> ScriptedResponse:
        return ScriptedResponse(json={endpoint: rows, "links": {"next": next_url} if next_url else {}})

    def test_fresh_run_follows_links_next_and_saves_state(self) -> None:
        result = self._driver().run(
            "patients",
            [
                self._page("patients", [{"id": "1"}], "https://api.au1.cliniko.com/v1/patients?page=2"),
                self._page("patients", [{"id": "2"}], "https://api.au1.cliniko.com/v1/patients?page=3"),
                self._page("patients", [{"id": "3"}]),
            ],
        )

        # The first request is built from the endpoint config (path + params); the
        # paginator only takes over the URL once a `links.next` has been seen.
        assert result.paths == ["/v1/patients"] * 3
        assert result.urls[0].startswith("https://api.au1.cliniko.com/v1/patients?")
        assert result.urls[1:] == [
            "https://api.au1.cliniko.com/v1/patients?page=2",
            "https://api.au1.cliniko.com/v1/patients?page=3",
        ]
        assert result.queries[0] == {"per_page": ("100",), "sort": ("created_at:asc",)}
        # Subsequent requests carry no separate params — the next-page URL is self-contained.
        assert result.queries[1:] == [{"page": ("2",)}, {"page": ("3",)}]

        assert result.rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        assert result.raised is None
        assert result.saved_states == [
            ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=2"),
            ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=3"),
        ]

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        result = self._driver().run(
            "patients",
            [self._page("patients", [{"id": "resumed"}])],
            resume_state=ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=5"),
        )

        assert result.urls == ["https://api.au1.cliniko.com/v1/patients?page=5"]
        assert result.rows == [{"id": "resumed"}]
        assert result.raised is None

    def test_incremental_run_sends_updated_at_filter(self) -> None:
        result = self._driver().run(
            "invoices",
            [self._page("invoices", [{"id": "1"}])],
            should_use_incremental_field=True,
        )

        assert result.requests[0].param("q[]") == "updated_at:>1970-01-01T00:00:00Z"
        assert result.requests[0].param("sort") == "updated_at:asc"
        assert result.raised is None


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(429, False)])
    def test_status_code_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            assert validate_credentials("test-key-au1") is expected

    def test_request_carries_required_headers_and_shard_url(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("test-key-uk1")

        assert network.requests_log[0].url == "https://api.uk1.cliniko.com/v1/patients?per_page=1"
        assert network.requests_log[0].headers["accept"] == "application/json"
        assert "PostHog" in network.requests_log[0].headers["user-agent"]
        assert network.requests_log[0].headers["authorization"].startswith("Basic ")
