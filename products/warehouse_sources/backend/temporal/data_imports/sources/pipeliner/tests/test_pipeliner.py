from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipeliner import (
    PipelinerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner import pipeliner as pipeliner_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.pipeliner import (
    PAGE_SIZE,
    PipelinerHostNotAllowedError,
    PipelinerResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source import PipelinerSource


def _driver(service_url: str = "us-east.api.pipelinersales.com") -> SourceDriver:
    return SourceDriver(
        PipelinerSource(),
        PipelinerSourceConfig(
            service_url=service_url,
            space_id="space-1",
            username="user",
            password="pass",
        ),
    )


def _response(
    items: list[dict[str, Any]],
    *,
    end_cursor: str | None = None,
    has_next_page: bool = False,
) -> ScriptedResponse:
    payload: dict[str, Any] = {"success": True, "data": items}
    if end_cursor is not None or has_next_page:
        payload["page_info"] = {"end_cursor": end_cursor, "has_next_page": has_next_page}
    return ScriptedResponse(json=payload)


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04 02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04 02:58:14"),
            (date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("2026-03-04 00:00:00", "2026-03-04 00:00:00"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestPipelinerSourceTransport:
    @pytest.mark.parametrize(
        "endpoint, entity",
        [
            ("accounts", "Accounts"),
            ("oppty_product_relations", "OpptyProductRelations"),
            ("sales_unit_client_relations", "SalesUnitClientRelations"),
            ("currency_exchange_rates_lists", "CurrencyExchangeRatesLists"),
        ],
    )
    def test_paginates_with_after_cursor_until_last_page(self, endpoint: str, entity: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "1"}, {"id": "2"}], end_cursor="cur1", has_next_page=True),
                _response([{"id": "3"}], end_cursor="cur2", has_next_page=False),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.params("after") == [None, "cur1"]
        assert result.params("first") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.paths == [f"/api/v100/rest/spaces/space-1/entities/{entity}"] * 2
        # The last page still has an end cursor. The has_next_page flag ends the walk.
        assert len(result.requests) == 2

    def test_resumes_from_saved_cursor_and_reapplies_saved_filter(self) -> None:
        result = _driver().run(
            "accounts",
            [_response([{"id": "9"}])],
            resume_state=PipelinerResumeConfig(cursor="resume-cur", filter_value="2026-01-01 00:00:00"),
            # A watermark that advanced mid-job must not replace the filter the cursor was minted under.
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
            incremental_field="modified",
        )

        assert result.raised is None
        assert result.params("after") == ["resume-cur"]
        assert result.params("filter[modified]") == ["2026-01-01 00:00:00"]

    def test_empty_page_terminates_even_when_has_next_page(self) -> None:
        result = _driver().run("accounts", [_response([], end_cursor="cur1", has_next_page=True)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_redirect_response_is_rejected(self) -> None:
        # The service URL is user-controlled; a 3xx could point at an internal address (SSRF).
        result = _driver().run(
            "accounts", [ScriptedResponse(status=302, headers={"Location": "https://evil.example.com"})]
        )

        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised)

    def test_blocks_unsafe_host_before_any_request(self) -> None:
        with mock.patch.object(pipeliner_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver("10.0.0.1").run("accounts", [_response([{"id": "1"}])])

        assert isinstance(result.raised, PipelinerHostNotAllowedError)
        assert result.requests == []


class TestValidateCredentials:
    def test_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"success": True, "data": []})]) as network:
            assert validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass") == (True, None)
        assert network.requests_log[0].param("first") == "1"

    def test_403_at_source_create_is_accepted(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials(
                "us-east.api.pipelinersales.com", "space-1", "user", "pass", schema_name=None
            ) == (True, None)

    def test_403_for_scoped_probe_fails(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials(
                "us-east.api.pipelinersales.com", "space-1", "user", "pass", schema_name="accounts"
            )
        assert valid is False
        assert msg is not None

    @pytest.mark.parametrize("bad_service_url", ["", "not a host!", "https://"])
    def test_invalid_service_url_short_circuits(self, bad_service_url: str) -> None:
        valid, msg = validate_credentials(bad_service_url, "space-1", "user", "pass")
        assert valid is False
        assert msg == "Invalid Pipeliner service URL"

    @pytest.mark.parametrize("bad_space_id", ["", "  ", "space/../../etc"])
    def test_invalid_space_id_short_circuits(self, bad_space_id: str) -> None:
        valid, msg = validate_credentials("us-east.api.pipelinersales.com", bad_space_id, "user", "pass")
        assert valid is False
        assert msg == "Invalid Pipeliner space ID"

    def test_error_message_surfaced_from_api_envelope(self) -> None:
        body = {"code": 404, "name": "ERROR_NOT_FOUND", "message": "Space not found.", "success": False}
        with scripted_network([ScriptedResponse(status=404, json=body)]):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
        assert valid is False
        assert msg == "Space not found."

    def test_rejects_redirect_response(self) -> None:
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://evil.example.com"})]):
            valid, msg = validate_credentials("us-east.api.pipelinersales.com", "space-1", "user", "pass")
        assert valid is False
        assert msg == pipeliner_module.HOST_NOT_ALLOWED_ERROR

    def test_blocks_unsafe_host(self) -> None:
        with (
            mock.patch.object(pipeliner_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", "space-1", "user", "pass", team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []
