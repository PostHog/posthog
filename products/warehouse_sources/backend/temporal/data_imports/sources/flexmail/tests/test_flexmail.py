from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail import (
    PAGE_SIZE,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import (
    ENDPOINTS,
    FLEXMAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source import FlexmailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flexmail import (
    FlexmailSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        FlexmailSource(), FlexmailSourceConfig(account_id="12345", personal_access_token="flexmail-token")
    )


def _envelope(items: list[dict[str, Any]], total: int, offset: int = 0) -> ScriptedResponse:
    # Flexmail's HAL collection envelope: rows under `_embedded.item`, row count in `total`.
    return ScriptedResponse(json={"total": total, "limit": PAGE_SIZE, "offset": offset, "_embedded": {"item": items}})


class TestPagination:
    def test_follows_offset_pagination_until_total(self) -> None:
        first_page = [{"id": i} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "contacts",
            [
                _envelope(first_page, total=PAGE_SIZE + 1),
                _envelope([{"id": 999}], total=PAGE_SIZE + 1, offset=PAGE_SIZE),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        # State is saved after the first page (points at the next offset), then we stop.
        assert [state.offset for state in result.saved_states] == [PAGE_SIZE]


class TestUnpaginatedEndpoints:
    @parameterized.expand([("segments",), ("opt_in_forms",), ("custom_fields",)])
    def test_fetches_once_never_paginates_and_strips_links(self, endpoint: str) -> None:
        items = [{"id": "u-1", "_links": {"self": {"href": "/x"}}}]
        result = _driver().run(endpoint, [ScriptedResponse(json={"_embedded": {"item": items}})])

        assert result.raised is None
        assert result.rows == [{"id": "u-1"}]
        # A single request with no pagination params, and no resume state persisted.
        assert len(result.requests) == 1
        assert result.requests[0].param("offset") is None
        assert result.requests[0].param("limit") is None
        assert result.saved_states == []


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", [ScriptedResponse(status=status, json={}), _envelope([{"id": 1}], total=1)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, Exception)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            assert validate_credentials("12345", "flexmail-token") == (expected_valid, expected_message)

        assert {request.path for request in network.requests_log} == {"/sources"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}

    def test_transport_error_is_not_validated(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("12345", "flexmail-token") == (
                False,
                "Could not validate Flexmail credentials",
            )

        assert {request.path for request in network.requests_log} == {"/sources"}


class TestContactFanout:
    def test_checkpoints_which_contacts_finished(self) -> None:
        result = _driver().run(
            "contact_sources",
            [
                _envelope([{"id": 29}], total=1),
                _envelope([{"id": 7, "name": "import"}], total=1),
            ],
        )

        assert result.raised is None
        assert result.saved_states, "the fan-out must checkpoint its progress through the contact list"
        last_state = result.saved_states[-1]
        assert last_state.fanout_state is not None
        assert "/contacts/29/sources" in last_state.fanout_state["completed"]


class TestFlexmailSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_envelope([], total=0)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        # Wired from the endpoint config, not hardcoded: a fan-out table keyed on the bare
        # sub-resource id would seed a duplicate row per contact.
        assert result.response.primary_keys == FLEXMAIL_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp exists on most resources, so we don't partition.
        assert result.response.partition_mode is None
