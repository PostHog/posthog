import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest

from requests import Request, Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    LoopReturnsPaginator,
    LoopReturnsResumeConfig,
    endpoint_permissions,
    next_cursor,
    resolve_window_start,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    LOOP_RETURNS_ENDPOINTS,
    RETURN_STATES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.source import LoopReturnsSource

WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
API_KEY = "loop_test_key"
API_VERSION = "v1"


def _http_response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _paginator(endpoint: str = "returns", *, days: int = 250) -> LoopReturnsPaginator:
    return LoopReturnsPaginator(
        config=LOOP_RETURNS_ENDPOINTS[endpoint],
        window_start=WINDOW_START,
        window_end=WINDOW_START + timedelta(days=days),
        filter_field="created_at",
    )


def _request() -> Request:
    return Request(method="GET", url="https://api.loopreturns.com/api/v1/warehouse/return/list")


def _walk(paginator: LoopReturnsPaginator, responses: list[Any], max_pages: int = 40) -> list[dict[str, Any]]:
    """Drive the paginator through `responses` and return the params of each request it built."""
    request = _request()
    paginator.init_request(request)
    sent = [dict(request.params or {})]

    for body in responses:
        if len(sent) >= max_pages:
            break
        paginator.update_state(_http_response(body))
        paginator.update_request(request)
        if not paginator.has_next_page:
            break
        sent.append(dict(request.params or {}))

    return sent


class TestLoopReturnsPaginator:
    @pytest.mark.parametrize(
        ("label", "second_body"),
        [
            ("next_link_without_a_cursor", {"returns": [], "nextPageUrl": "https://api.loopreturns.com/next"}),
            (
                "repeated_cursor",
                {"returns": [], "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc"},
            ),
        ],
    )
    def test_pagination_that_cannot_advance_moves_on_instead_of_looping(self, label: str, second_body: Any) -> None:
        first_body = {
            "returns": [],
            "nextPageUrl": "https://api.loopreturns.com/api/v1/warehouse/return/list?cursor=abc",
        }
        sent = _walk(_paginator(days=10), [first_body, second_body, {"returns": [], "nextPageUrl": None}])

        # Page three is the next state's pass over the same window, not a third fetch of the cursor.
        assert [params["state"] for params in sent[:3]] == ["open", "open", "closed"]
        assert sent[2].get("cursor") is None

    @pytest.mark.parametrize(
        ("label", "state"),
        [
            ("missing_window_start", {}),
            ("null_window_start", {"window_start": None}),
        ],
    )
    def test_unusable_resume_state_is_ignored(self, label: str, state: dict[str, Any]) -> None:
        paginator = _paginator(days=10)
        paginator.set_resume_state(state)
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["from"] == "2024-01-01T00:00:00.000Z"

    def test_a_watermark_after_the_window_end_never_inverts_the_range(self) -> None:
        # A watermark at (or past) "now" must not produce `to` before `from`, which Loop rejects.
        paginator = LoopReturnsPaginator(
            config=LOOP_RETURNS_ENDPOINTS["returns"],
            window_start=WINDOW_START,
            window_end=WINDOW_START - timedelta(days=1),
            filter_field="created_at",
        )
        request = _request()
        paginator.init_request(request)

        assert request.params is not None
        assert request.params["to"] == request.params["from"]

    def test_endpoint_without_pagination_or_states_only_windows(self) -> None:
        sent = _walk(_paginator("advanced_shipping_notices", days=200), [[], [], []])

        assert [(params["from"], params["to"]) for params in sent] == [
            ("2024-01-01T00:00:00.000Z", "2024-03-31T00:00:00.000Z"),
            ("2024-03-31T00:00:00.000Z", "2024-06-29T00:00:00.000Z"),
            ("2024-06-29T00:00:00.000Z", "2024-07-19T00:00:00.000Z"),
        ]
        assert all("state" not in params and "cursor" not in params for params in sent)
        # The ASN report doesn't accept the `filter` param, so it must not be sent.
        assert all("filter" not in params for params in sent)


class TestNextCursor:
    @pytest.mark.parametrize(
        ("label", "body", "expected"),
        [
            ("cursor_in_next_link", {"nextPageUrl": "https://api.loopreturns.com/x?cursor=c1&pageSize=250"}, "c1"),
            ("last_page", {"nextPageUrl": None}, None),
            ("no_next_link", {"returns": []}, None),
            ("next_link_without_cursor", {"nextPageUrl": "https://api.loopreturns.com/x?pageSize=250"}, None),
            ("bare_array_body", [{"id": "1"}], None),
        ],
    )
    def test_next_cursor(self, label: str, body: Any, expected: Optional[str]) -> None:
        assert next_cursor(_http_response(body)) == expected

    def test_non_json_body_has_no_cursor(self) -> None:
        response = Response()
        response.status_code = 200
        response._content = b"<html>error</html>"

        assert next_cursor(response) is None


class TestResolveWindowStart:
    def test_a_naive_watermark_is_treated_as_utc(self) -> None:
        assert resolve_window_start(
            now=WINDOW_START,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 3, 4, 5, 6, 7),
        ) == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)


class TestLoopReturnsSource:
    @staticmethod
    def _driver(start_date: str | None = None) -> SourceDriver:
        return SourceDriver(LoopReturnsSource(), LoopReturnsSourceConfig(api_key=API_KEY, start_date=start_date))

    def test_an_incremental_run_starts_at_the_watermark_and_windows_on_the_chosen_field(self) -> None:
        result = self._driver().run(
            "returns",
            always(ScriptedResponse(json={"returns": [], "nextPageUrl": None})),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-12-25T00:00:00Z",
            incremental_field="updated_at",
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.requests[0].param("from") == "2023-12-25T00:00:00.000Z"
        assert result.requests[0].param("filter") == "updated_at"

    def test_a_resumed_run_picks_up_at_the_saved_state_pass(self) -> None:
        start = (datetime.now(UTC) - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        resumed_window_start = start + timedelta(hours=12)
        result = self._driver(start.strftime("%Y-%m-%dT%H:%M:%SZ")).run(
            "returns",
            always(ScriptedResponse(json={"returns": [], "nextPageUrl": None})),
            resume_state=LoopReturnsResumeConfig(
                window_start=resumed_window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), state_index=3, cursor="c9"
            ),
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.requests[0].param("state") == RETURN_STATES[3]
        assert result.requests[0].param("cursor") == "c9"
        assert result.requests[0].param("from") == resumed_window_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # The next pass restarts at the configured start date, not the resumed window.
        assert result.requests[1].param("from") == start.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def test_destinations_are_not_resumed_or_windowed(self) -> None:
        result = self._driver().run(
            "destinations",
            [ScriptedResponse(json={"destinations": []})],
            resume_state=LoopReturnsResumeConfig(window_start="2023-12-31T00:00:00.000Z", state_index=2, cursor="c9"),
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.queries == [{}]
        assert result.saved_states == []

    @pytest.mark.parametrize(
        ("label", "last_next_page_url"),
        [
            ("null_next_link", None),
        ],
    )
    def test_a_cursor_endpoint_walks_pages_until_the_next_link_ends(
        self, label: str, last_next_page_url: str | None
    ) -> None:
        result = self._driver().run(
            "orders",
            [
                ScriptedResponse(
                    json={
                        "orders": [{"id": 1}, {"id": 2}],
                        "next_page_url": "https://api.loopreturns.com/api/v1/orders?cursor=c1",
                    }
                ),
                ScriptedResponse(json={"orders": [{"id": 3}], "next_page_url": last_next_page_url}),
            ],
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.params("cursor") == [None, "c1"]
        # Our own page size and sort stay on every page, whatever Loop's next link carries.
        assert result.params("limit") == ["250", "250"]
        assert result.params("sort_order") == ["asc", "asc"]
        assert result.saved_states == [LoopReturnsResumeConfig(cursor="c1")]

    @pytest.mark.parametrize(
        ("label", "second_link", "message"),
        [
            ("repeated_cursor", "https://api.loopreturns.com/api/v1/orders?cursor=c1", "not advancing"),
            ("link_without_cursor", "https://api.loopreturns.com/api/v1/orders?limit=250", "no usable cursor"),
        ],
    )
    def test_a_cursor_endpoint_fails_when_the_next_link_cannot_be_followed(
        self, label: str, second_link: str, message: str
    ) -> None:
        result = self._driver().run(
            "orders",
            [
                ScriptedResponse(
                    json={"orders": [{"id": 1}], "next_page_url": "https://api.loopreturns.com/api/v1/orders?cursor=c1"}
                ),
                ScriptedResponse(json={"orders": [{"id": 2}], "next_page_url": second_link}),
            ],
            api_version=API_VERSION,
        )

        assert isinstance(result.raised, ValueError)
        assert message in str(result.raised)

    def test_a_resumed_cursor_endpoint_starts_at_the_saved_cursor(self) -> None:
        result = self._driver().run(
            "customers",
            [ScriptedResponse(json={"customers": [{"id": 7}], "next_page_url": None})],
            resume_state=LoopReturnsResumeConfig(cursor="c5"),
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert result.params("cursor") == ["c5"]
        assert [row["id"] for row in result.rows] == [7]

    def test_product_variants_fan_out_over_every_product(self) -> None:
        result = self._driver().run(
            "product_variants",
            route(
                {
                    "/products": [
                        ScriptedResponse(json={"products": [{"id": 10}, {"id": 20}], "next_page_url": None}),
                    ],
                    "/products/10/product-variants": [
                        ScriptedResponse(
                            json={
                                "product_variants": [{"id": 1}],
                                "next_page_url": "https://api.loopreturns.com/api/v1/products/10/product-variants?cursor=v1",
                            }
                        ),
                        ScriptedResponse(json={"product_variants": [{"id": 2}], "next_page_url": None}),
                    ],
                    # A product deleted after the product listing ran.
                    "/products/20/product-variants": [ScriptedResponse(status=404, json={"message": "Not found"})],
                }
            ),
            api_version=API_VERSION,
        )

        assert result.raised is None
        assert [(row["product_id"], row["id"]) for row in result.rows] == [(10, 1), (10, 2)]
        assert all("_products_id" not in row for row in result.rows)
        assert result.paths == [
            "/api/v1/products",
            "/api/v1/products/10/product-variants",
            "/api/v1/products/10/product-variants",
            "/api/v1/products/20/product-variants",
        ]
        assert result.params("cursor") == [None, None, "v1", None]
        assert result.saved_states == []


class TestCredentialValidation:
    @pytest.mark.parametrize(
        ("label", "status_codes", "expected_valid"),
        [
            ("returns_readable", [200], True),
            # A key scoped only for destinations still works, just for fewer tables.
            ("returns_denied_destinations_readable", [401, 200], True),
            # One probe per scope: returns, destinations, orders, products, then customers.
            ("only_customers_readable", [401, 401, 401, 401, 200], True),
            ("everything_denied", [401] * 5, False),
            ("forbidden", [403] * 5, False),
            ("server_error", [500], False),
        ],
    )
    def test_validate_credentials(self, label: str, status_codes: list[int], expected_valid: bool) -> None:
        responses = [ScriptedResponse(status=code, json={}) for code in status_codes]
        script = always(responses[0]) if status_codes == [500] else responses
        with scripted_network(script):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    def test_a_denied_key_names_the_scope_to_add(self) -> None:
        with scripted_network(always(ScriptedResponse(status=401))):
            _, error = validate_credentials(API_KEY, API_VERSION)

        assert error is not None
        assert "Returns" in error

    @pytest.mark.parametrize(
        ("schema_name", "expected_url"),
        [
            ("destinations", "https://api.loopreturns.com/api/v1/destinations"),
            # A variant request needs a product id, so the product list stands in for it.
            ("product_variants", "https://api.loopreturns.com/api/v1/products?limit=1"),
        ],
    )
    def test_validating_one_schema_probes_only_that_endpoint(self, schema_name: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            is_valid, error = validate_credentials(API_KEY, API_VERSION, schema_name=schema_name)

        assert (is_valid, error) == (True, None)
        assert [request.url for request in network.requests_log] == [expected_url]

    def test_a_network_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(RequestsConnectionError("no route to host"))):
            is_valid, error = validate_credentials(API_KEY, API_VERSION)

        assert is_valid is False
        assert error is not None and "no route to host" in error

    def test_endpoint_permissions_reports_each_table_separately(self) -> None:
        responses = [ScriptedResponse(status=200, json={}), ScriptedResponse(status=401, json={})]
        with scripted_network(responses):
            permissions = endpoint_permissions(API_KEY, API_VERSION, ["returns", "destinations"])

        assert permissions["returns"] is None
        assert permissions["destinations"] is not None
        assert "Destinations (Read)" in str(permissions["destinations"])
