from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.tickettailor._config import TicketTailorSourceConfig
from products.warehouse_sources.sources.tickettailor.settings import TICKET_TAILOR_ENDPOINTS
from products.warehouse_sources.sources.tickettailor.source import TicketTailorSource
from products.warehouse_sources.sources.tickettailor.tickettailor import (
    PAGE_SIZE,
    TicketTailorResumeConfig,
    validate_credentials,
)


def _page(items: list[dict[str, Any]] | None, *, next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"links": {"next": next_link, "previous": None}, "data": items or []})


def _run(script: Script, endpoint: str = "orders", resume_state: TicketTailorResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(TicketTailorSource(), TicketTailorSourceConfig(api_key="tt-key"))
    return driver.run(endpoint, script, resume_state=resume_state)


class TestPagination:
    def test_follows_cursor_until_no_next_link(self) -> None:
        first_page = [{"id": f"or_{i}"} for i in range(PAGE_SIZE)]
        result = _run(
            [
                _page(first_page, next_link="https://api.tickettailor.com/v1/orders?starting_after=or_99"),
                _page([{"id": "or_100"}], next_link=None),
            ],
        )

        assert [r["id"] for r in result.rows] == [*(f"or_{i}" for i in range(PAGE_SIZE)), "or_100"]
        # First request carries only limit; the second advances via the last id of page one.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),)}
        assert result.queries[1] == {"limit": (str(PAGE_SIZE),), "starting_after": ("or_99",)}
        # Checkpoint saved once, after the first page (points at the next page); the null next link ends it.
        assert result.saved_states == [TicketTailorResumeConfig(cursor="or_99")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _run([_page([{"id": "or_51"}], next_link=None)], resume_state=TicketTailorResumeConfig(cursor="or_50"))

        assert [r["id"] for r in result.rows] == ["or_51"]
        # The uncursored first page must never be fetched on resume.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),), "starting_after": ("or_50",)}


class TestMalformedBodyIsRetryable:
    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "or_1"}]),
            ("missing_data_key", {"links": {"next": None}}),
        ]
    )
    def test_unexpected_shape_is_retried_then_reraised(self, _name: str, body: Any) -> None:
        # A 200 whose body isn't {"data": [...], ...} is treated as a transient truncation: retried
        # (up to the client's attempt cap) rather than ingested as a stray row.
        result = _run(always(ScriptedResponse(json=body)))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestValidateCredentials:
    def test_connection_error_maps_to_could_not_validate(self) -> None:
        # validate_via_probe swallows transport errors; the probe reports "not validated".
        with scripted_network(always(ConnectionResetError("reset"))):
            assert validate_credentials("tt-key") == (False, "Could not validate Ticket Tailor API key")


class TestListParams:
    @parameterized.expand(
        [
            ("holds", "/v1/holds", {"limit": (str(PAGE_SIZE),)}),
            # The stores list documents no `limit` parameter.
            ("stores", "/v1/stores", {}),
        ]
    )
    def test_first_request(self, endpoint: str, path: str, expected_query: dict[str, tuple[str, ...]]) -> None:
        result = _run([_page([{"id": "x_1"}])], endpoint)

        assert result.raised is None
        assert result.paths == [path]
        assert result.queries == [expected_query]


class TestFanout:
    def test_voucher_codes_walk_every_voucher_and_child_page(self) -> None:
        result = _run(
            route(
                {
                    "/v1/vouchers": [
                        _page([{"id": "vo_3"}, {"id": "vo_2"}], next_link="/v1/vouchers?starting_after=vo_2"),
                        _page([{"id": "vo_1"}]),
                    ],
                    "/v1/vouchers/vo_3/codes": [
                        _page([{"id": "vc_9", "code": "A"}], next_link="/v1/vouchers/vo_3/codes?starting_after=vc_9"),
                        _page([{"id": "vc_8", "code": "B"}]),
                    ],
                    # A voucher deleted after the listing was read.
                    "/v1/vouchers/vo_2/codes": [ScriptedResponse(status=404, json={"message": "Not found"})],
                    "/v1/vouchers/vo_1/codes": [_page([{"id": "vc_1", "code": "C", "voucher_id": "vo_1"}])],
                }
            ),
            "voucher_codes",
        )

        assert result.raised is None
        assert [(r["voucher_id"], r["id"]) for r in result.rows] == [
            ("vo_3", "vc_9"),
            ("vo_3", "vc_8"),
            ("vo_1", "vc_1"),
        ]
        assert result.paths == [
            "/v1/vouchers",
            "/v1/vouchers/vo_3/codes",
            "/v1/vouchers/vo_3/codes",
            "/v1/vouchers/vo_2/codes",
            "/v1/vouchers",
            "/v1/vouchers/vo_1/codes",
        ]
        assert result.params("starting_after") == [None, None, "vc_9", None, "vo_2", None]
        assert result.params("limit") == [str(PAGE_SIZE)] * 6

    def test_waitlist_signups_carry_the_event_series_id(self) -> None:
        result = _run(
            route(
                {
                    "/v1/event_series": [_page([{"id": "es_1"}, {"id": "es_2"}])],
                    "/v1/event_series/es_1/waitlist_signups": [_page([{"id": "ws_1", "event_id": "ev_1"}])],
                    "/v1/event_series/es_2/waitlist_signups": [_page([{"id": "ws_2", "event_id": "ev_2"}])],
                }
            ),
            "waitlist_signups",
        )

        assert result.raised is None
        assert [(r["event_series_id"], r["id"], r["event_id"]) for r in result.rows] == [
            ("es_1", "ws_1", "ev_1"),
            ("es_2", "ws_2", "ev_2"),
        ]
        assert all("_event_series_id" not in r for r in result.rows)

    def test_resume_skips_finished_parents_and_continues_the_current_child(self) -> None:
        result = _run(
            route(
                {
                    "/v1/vouchers": [_page([{"id": "vo_3"}, {"id": "vo_2"}, {"id": "vo_1"}])],
                    "/v1/vouchers/vo_2/codes": [_page([{"id": "vc_4"}])],
                    "/v1/vouchers/vo_1/codes": [_page([{"id": "vc_1"}])],
                }
            ),
            "voucher_codes",
            resume_state=TicketTailorResumeConfig(
                fanout_state={
                    "completed": ["/v1/vouchers/vo_3/codes"],
                    "current": "/v1/vouchers/vo_2/codes",
                    "child_state": {"cursor": "vc_5"},
                }
            ),
        )

        assert result.raised is None
        assert [(r["voucher_id"], r["id"]) for r in result.rows] == [("vo_2", "vc_4"), ("vo_1", "vc_1")]
        assert result.paths == ["/v1/vouchers", "/v1/vouchers/vo_2/codes", "/v1/vouchers/vo_1/codes"]
        assert result.params("starting_after") == [None, "vc_5", None]
        assert all(state.cursor is None and state.fanout_state for state in result.saved_states)


class TestSourceResponseShape:
    @parameterized.expand([(name,) for name, config in TICKET_TAILOR_ENDPOINTS.items() if config.fanout is None])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run([_page([])], endpoint).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists come back newest-first; declaring asc would corrupt a future incremental watermark.
        assert response.sort_mode == "desc"
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
