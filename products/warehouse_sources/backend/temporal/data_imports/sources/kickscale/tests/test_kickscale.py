from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kickscale import (
    KickscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.kickscale import (
    KickscaleAuth,
    KickscalePageNumberPaginator,
    KickscaleResumeConfig,
    _client_config,
    _format_kickscale_datetime,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source import KickscaleSource


class TestKickscaleAuth:
    def test_sets_both_headers(self) -> None:
        auth = KickscaleAuth(api_key="key-1", client_id="client-1")
        request = Request(method="GET", url="https://api.kickscale.com/meetings").prepare()

        auth(request)

        assert request.headers["api-key"] == "key-1"
        assert request.headers["client-id"] == "client-1"

    def test_secret_values_reports_both_credentials(self) -> None:
        auth = KickscaleAuth(api_key="key-1", client_id="client-1")
        assert set(auth.secret_values()) == {"key-1", "client-1"}


class TestKickscalePageNumberPaginator:
    @parameterized.expand(
        [
            ("full_page_keeps_going", 100, 100, True),
            ("short_page_is_terminal", 100, 40, False),
            ("empty_page_is_terminal", 100, 0, False),
        ]
    )
    def test_termination(self, _name: str, page_size: int, row_count: int, expected_has_next: bool) -> None:
        paginator = KickscalePageNumberPaginator(page_size=page_size)
        response = Mock()
        response.json.return_value = [{"id": str(i)} for i in range(row_count)]
        data = [{"id": str(i)} for i in range(row_count)]

        paginator.update_state(response, data=data)

        assert paginator.has_next_page is expected_has_next


@parameterized.expand(
    [
        ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
        ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
        ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
    ]
)
def test_format_kickscale_datetime(_name: str, value: Any, expected: str) -> None:
    assert _format_kickscale_datetime(value) == expected


class TestGetResource:
    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_incremental_resource(self, endpoint: str) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        assert incremental["start_param"] == "startDate"
        assert incremental["cursor_path"] == "date"


def test_client_config_pins_host_and_blocks_redirects() -> None:
    # A redirect off the Kickscale host would otherwise replay the api-key/client-id headers.
    config = _client_config("key", "client")
    assert config["allowed_hosts"] == []
    assert config["allow_redirects"] is False


@parameterized.expand(
    [
        (200, True, None),
        (403, False, "Check both values"),
        (500, False, "unexpected status code"),
    ]
)
def test_validate_credentials_status_mapping(status: int, expected_valid: bool, message_fragment: str | None) -> None:
    with scripted_network(always(ScriptedResponse(status=status))) as network:
        is_valid, message = validate_credentials("kickscale-key", "kickscale-client")

    assert is_valid is expected_valid
    if message_fragment is None:
        assert message is None
    else:
        assert message is not None and message_fragment in message

    assert {request.path for request in network.requests_log} == {"/meetings"}
    assert {request.origin for request in network.requests_log} == {"https://api.kickscale.com"}
    assert all(request.headers["api-key"] == "kickscale-key" for request in network.requests_log)
    assert all(request.headers["client-id"] == "kickscale-client" for request in network.requests_log)
    # The validation session must refuse redirects so a 3xx can't replay the credentials off-host.
    assert network.session_options[0]["allow_redirects"] is False


class TestKickscaleSourceResumeBehavior:
    """End-to-end resume behaviour of ``KickscaleSource`` via ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(KickscaleSource(), KickscaleSourceConfig(api_key="test-key", client_id="test-client"))

    @staticmethod
    def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
        return ScriptedResponse(
            json={"data": rows, "meta": {"total": 101, "returned": len(rows), "page": 0, "pageSize": 100}}
        )

    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_fresh_run_pages_until_short_page(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            [
                self._page([{"id": f"m{i}"} for i in range(100)]),
                self._page([{"id": "m100"}]),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["0", "1"]
        assert [row["id"] for row in result.rows] == [f"m{i}" for i in range(101)]
        assert result.saved_states == [KickscaleResumeConfig(page=1)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "meetings", [self._page([{"id": "m1"}])], resume_state=KickscaleResumeConfig(page=3)
        )

        assert result.raised is None
        assert result.params("page") == ["3"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("meetings", [self._page([{"id": "a"}])])

        assert result.raised is None
        assert result.params("page") == ["0"]
