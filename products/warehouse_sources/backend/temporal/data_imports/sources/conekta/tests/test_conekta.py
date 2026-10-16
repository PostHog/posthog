import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta import (
    ConektaCursorPaginator,
    ConektaResumeConfig,
    to_epoch_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import API_VERSION, PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.source import ConektaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.conekta import (
    ConektaSourceConfig,
)


def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> Response:
    body: dict[str, Any] = {"data": rows, "object": "list", "has_more": next_cursor is not None}
    body["next_page_url"] = (
        f"https://api.conekta.io/orders?limit={PAGE_SIZE}&next={next_cursor}" if next_cursor else None
    )
    body["previous_page_url"] = None
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    return response


def _driver() -> SourceDriver:
    return SourceDriver(ConektaSource(), ConektaSourceConfig(api_key="key_priv"))


def _scripted_page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json=_page(rows, next_cursor).json())


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1676328434, 1676328434),
            (1676328434.9, 1676328434),
            (datetime(2023, 2, 13, 21, 27, 14, tzinfo=UTC), 1676323634),
            ("1676328434", 1676328434),
            ("2023-02-13T21:27:14+00:00", 1676323634),
            ("nonsense", "nonsense"),
        ],
    )
    def test_coerces_watermark_to_epoch_seconds(self, value, expected):
        assert to_epoch_seconds(value) == expected

    def test_date_maps_to_midnight(self):
        assert to_epoch_seconds(date(2023, 2, 13)) == int(datetime(2023, 2, 13).timestamp())


class TestPaginator:
    def _advance(self, paginator: ConektaCursorPaginator, response: Response, request: Request) -> None:
        paginator.update_state(response)
        paginator.update_request(request)

    def test_keeps_original_params_and_adds_cursor(self):
        paginator = ConektaCursorPaginator()
        request = Request(method="GET", url="https://api.conekta.io/orders", params={"limit": 250, "updated_at.gte": 5})

        self._advance(paginator, _page([{"id": "ord_1"}], "ord_1"), request)

        assert paginator.has_next_page is True
        assert request.params == {"limit": 250, "updated_at.gte": 5, "next": "ord_1"}

    @pytest.mark.parametrize(
        "body",
        [
            {"data": [], "has_more": False, "next_page_url": None},
            {"data": [], "has_more": True, "next_page_url": None},
        ],
    )
    def test_stops_when_no_next_page(self, body):
        response = Response()
        response.status_code = 200
        response._content = json.dumps(body).encode()

        paginator = ConektaCursorPaginator()
        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_stops_on_non_json_body(self):
        response = Response()
        response.status_code = 200
        response._content = b"<html>maintenance</html>"

        paginator = ConektaCursorPaginator()
        paginator.update_state(response)

        assert paginator.has_next_page is False


class TestValidateCredentials:
    def test_probes_orders_with_bearer_token_and_versioned_accept(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key_priv") == (True, 200)

        assert network.session_options[0]["headers"]["Accept"] == f"application/vnd.conekta-v{API_VERSION}+json"
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "GET"
        assert request.path == "/orders"
        assert request.param("limit") == "1"
        assert request.headers["authorization"] == "Bearer key_priv"


class TestRequests:
    def test_incremental_filter_survives_pagination(self) -> None:
        result = _driver().run(
            "orders",
            [_scripted_page([{"id": "ord_1"}], "ord_1"), _scripted_page([{"id": "ord_2"}], None)],
            incremental_field="updated_at",
            should_use_incremental_field=True,
            db_incremental_field_last_value=1676328434,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ord_1", "ord_2"]
        # Conekta's next_page_url only echoes limit+next, so the cursor must be re-applied to the
        # original request; otherwise page two drops the filter and walks the whole history.
        assert result.queries == [
            {"limit": (str(PAGE_SIZE),), "updated_at.gte": ("1676328434",)},
            {"limit": (str(PAGE_SIZE),), "updated_at.gte": ("1676328434",), "next": ("ord_1",)},
        ]
        assert result.saved_states == [ConektaResumeConfig(next_cursor="ord_1")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "orders",
            [_scripted_page([{"id": "ord_5"}], None)],
            resume_state=ConektaResumeConfig(next_cursor="ord_4"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ord_5"]
        assert result.queries == [{"limit": (str(PAGE_SIZE),), "next": ("ord_4",)}]
