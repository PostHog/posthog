from datetime import UTC, datetime

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.gorgias._config import GorgiasSourceConfig
from products.warehouse_sources.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    get_base_url,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.sources.gorgias.settings import ENDPOINTS, GORGIAS_ENDPOINTS
from products.warehouse_sources.sources.gorgias.source import GorgiasSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(GorgiasSource(), GorgiasSourceConfig(gorgias_domain="acme", email="e@acme.com", api_key="key"))


def _page(rows: list[dict], cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "meta": {"next_cursor": cursor}})


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("bare_subdomain", "acme", "acme"),
            ("full_host", "acme.gorgias.com", "acme"),
            ("https_url", "https://acme.gorgias.com", "acme"),
            ("https_url_with_path", "https://acme.gorgias.com/api/", "acme"),
            ("uppercase_and_spaces", "  ACME  ", "acme"),
            ("trailing_slash", "acme/", "acme"),
        ]
    )
    def test_normalize_domain(self, _name: str, value: str, expected: str) -> None:
        assert normalize_domain(value) == expected

    @parameterized.expand(
        [
            # Crafted inputs that would otherwise break out of the .gorgias.com host
            # and redirect the request (and the Basic-auth header) elsewhere.
            ("fragment", "attacker.example.com#"),
            ("query", "169.254.169.254?x="),
            ("userinfo", "user@attacker.example.com"),
            ("port", "attacker.example.com:8080"),
            ("dotted", "evil.com"),
            ("empty", "   "),
            ("leading_hyphen", "-acme"),
        ]
    )
    def test_get_base_url_rejects_unsafe_domains(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            get_base_url(domain)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("acme", "you@acme.com", "key")
        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert network.requests_log[0].path == "/api/account"

    def test_empty_domain_fails_without_request(self) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials("   ", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        assert network.requests_log == []
        assert network.session_options == []

    def test_unsafe_domain_fails_without_request(self) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials("attacker.example.com#", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        assert network.requests_log == []
        assert network.session_options == []


class TestGetRows:
    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run("tickets", [_page([])], resume_state=GorgiasResumeConfig(cursor="resume-token"))

        assert result.raised is None
        assert result.params("cursor") == ["resume-token"]

    def test_page_cursor_conflict_is_classified_non_retryable(self) -> None:
        # A 409 on a page fetch means the cursor no longer matches the current list (e.g. a merged
        # or deleted customer shifted it), not a transient blip — every retry would replay the same
        # now-invalid cursor and fail identically.
        result = _driver().run("customers", [_page([{"id": 1}], cursor="c2"), ScriptedResponse(status=409)])

        assert isinstance(result.raised, requests.HTTPError)
        error_message = str(result.raised)
        assert any(key in error_message for key in GorgiasSource().get_non_retryable_errors())


class TestTopLevelRows:
    @parameterized.expand(
        [
            (
                "integration_credentials_dropped",
                "integrations",
                {
                    "data": [
                        {
                            "id": 1,
                            "type": "http",
                            "http": {
                                "url": "https://example.com/hook",
                                "headers": {"Authorization": "Bearer fake-token"},
                                "oauth2": {"client_secret": "fake-secret"},
                            },
                        },
                        {"id": 2, "type": "email", "http": None},
                    ],
                    "meta": {"next_cursor": None},
                },
                [
                    {"id": 1, "type": "http", "http": {"url": "https://example.com/hook"}},
                    {"id": 2, "type": "email", "http": None},
                ],
            ),
            ("rules_bare_array", "rules", [{"id": 5, "name": "auto-close"}], [{"id": 5, "name": "auto-close"}]),
            ("widgets_bare_array", "widgets", [{"id": 7, "order": 1}], [{"id": 7, "order": 1}]),
        ]
    )
    def test_rows(self, _name: str, endpoint: str, body: object, expected: list[dict]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.paths == [f"/api/{endpoint}"]
        assert result.params("order_by") == ["created_datetime:asc"]
        assert result.rows == expected


class TestParamVariants:
    @parameterized.expand(
        [
            ("voice_calls", "phone/voice-calls"),
            ("voice_call_events", "phone/voice-call-events"),
            ("voice_call_recordings", "phone/voice-call-recordings"),
        ]
    )
    def test_voice_endpoints_send_no_order_by(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.paths == [f"/api/{path}"]
        assert result.requests[0].origin == "https://acme.gorgias.com"
        assert result.params("limit") == ["100"]
        assert result.params("order_by") == [None]


class TestTicketChildTables:
    def _rows(self, endpoint: str, tickets: list[dict]) -> list[dict]:
        result = _driver().run(endpoint, [_page(tickets)])
        assert result.raised is None
        assert result.paths == ["/api/tickets"]
        return result.rows

    def test_ticket_tags_flattens_one_row_per_tag(self) -> None:
        rows = self._rows(
            "ticket_tags",
            [
                {
                    "id": 10,
                    "created_datetime": "2024-01-01T00:00:00+00:00",
                    "tags": [{"id": 1, "name": "urgent"}, {"name": "no-id"}],
                },
                {"id": 11, "created_datetime": "2024-02-01T00:00:00+00:00", "tags": []},
            ],
        )

        assert rows == [
            {"id": 1, "name": "urgent", "ticket_id": 10, "ticket_created_datetime": "2024-01-01T00:00:00+00:00"}
        ]

    def test_ticket_field_values_keys_by_field_and_keeps_value_one_type(self) -> None:
        rows = self._rows(
            "ticket_field_values",
            [
                {
                    "id": 10,
                    "created_datetime": "2024-01-01T00:00:00+00:00",
                    "custom_fields": {
                        "5": {"id": 5, "value": "Order::Status", "prediction": None},
                        "6": {"id": 6, "value": 3},
                        "7": {"id": 7, "value": True},
                        "8": {"id": 8, "value": None},
                    },
                },
                {"id": 11, "created_datetime": "2024-02-01T00:00:00+00:00", "custom_fields": None},
            ],
        )

        assert [(r["ticket_id"], r["field_id"], r["value"]) for r in rows] == [
            (10, 5, "Order::Status"),
            (10, 6, "3"),
            (10, 7, "true"),
            (10, 8, None),
        ]
        assert all(r["ticket_created_datetime"] == "2024-01-01T00:00:00+00:00" for r in rows)


class TestCustomerFieldValues:
    def test_fans_out_per_customer_and_skips_deleted_customers(self) -> None:
        result = _driver().run(
            "customer_field_values",
            [
                _page(
                    [
                        {"id": 1, "created_datetime": "2024-01-01T00:00:00"},
                        {"id": 2, "created_datetime": "2024-02-01T00:00:00"},
                        {"id": 3, "created_datetime": "2024-03-01T00:00:00"},
                    ]
                ),
                ScriptedResponse(
                    json={
                        "data": [
                            {"field": {"id": 5, "label": "Plan"}, "value": "pro"},
                            {"field": {"id": 6, "label": "Seats"}, "value": 12},
                        ]
                    }
                ),
                ScriptedResponse(status=404),
                # Some list endpoints return a bare array rather than a `data` envelope.
                ScriptedResponse(json=[{"field": {"id": 5, "label": "Plan"}, "value": None}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/customers",
            "/api/customers/1/custom-fields",
            "/api/customers/2/custom-fields",
            "/api/customers/3/custom-fields",
        ]
        assert [(r["customer_id"], r["field_id"], r["value"], r["customer_created_datetime"]) for r in result.rows] == [
            (1, 5, "pro", "2024-01-01T00:00:00"),
            (1, 6, "12", "2024-01-01T00:00:00"),
            (3, 5, None, "2024-03-01T00:00:00"),
        ]

    def test_child_error_other_than_404_fails_the_sync(self) -> None:
        result = _driver().run("customer_field_values", [_page([{"id": 1}]), ScriptedResponse(status=403)])

        assert isinstance(result.raised, requests.HTTPError)

    def test_stages_parent_cursor_and_reaches_safe_point_on_pages_without_values(self) -> None:
        result = _driver().run(
            "customer_field_values",
            [
                _page([{"id": 1}], cursor="c2"),
                ScriptedResponse(json={"data": []}),
                _page([{"id": 2}]),
                ScriptedResponse(json={"data": [{"field": {"id": 5}, "value": "x"}]}),
            ],
        )

        assert result.raised is None
        assert [r["customer_id"] for r in result.rows] == [2]
        assert result.saved_states == [
            GorgiasResumeConfig(cursor="c2", variant=0),
            GorgiasResumeConfig(cursor=None, variant=1),
        ]
        assert result.committed_states == result.saved_states


def _items(ids: list[int], next_items: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": [{"id": i, "created_datetime": f"2024-01-0{i}T00:00:00+00:00"} for i in ids],
            "meta": {"next_items": next_items},
        }
    )


VIEWS_PAGE = _page(
    [
        {"id": 3, "type": "ticket-list"},
        {"id": 1, "type": "ticket-list"},
        {"id": 2, "type": "customer-list"},
        {"id": 4, "type": "ticket-list", "deactivated_datetime": "2024-01-01T00:00:00"},
        {"id": 5},
    ]
)
NEXT_LINK = "/api/views/1/items/?direction=next&ignored_item=11&cursor=abc"


class TestViewItems:
    def test_walks_ticket_views_in_id_order_following_next_items(self) -> None:
        result = _driver().run(
            "view_items",
            [
                VIEWS_PAGE,
                _items([1, 2], next_items=NEXT_LINK),
                # A link that points back at the same page must not loop forever.
                _items([3], next_items=NEXT_LINK),
                ScriptedResponse(status=404),
                _items([]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/views",
            "/api/views/1/items",
            "/api/views/1/items",
            "/api/views/3/items",
            "/api/views/5/items",
        ]
        assert [(r.param("cursor"), r.param("ignored_item"), r.param("order_by")) for r in result.requests[1:]] == [
            (None, None, "created_datetime:asc"),
            ("abc", "11", "created_datetime:asc"),
            (None, None, "created_datetime:asc"),
            (None, None, "created_datetime:asc"),
        ]
        assert [(r["view_id"], r["ticket_id"], r["ticket_created_datetime"]) for r in result.rows] == [
            (1, 1, "2024-01-01T00:00:00+00:00"),
            (1, 2, "2024-01-02T00:00:00+00:00"),
            (1, 3, "2024-01-03T00:00:00+00:00"),
        ]
        assert result.saved_states == [
            GorgiasResumeConfig(cursor=NEXT_LINK, parent_id=1),
            GorgiasResumeConfig(cursor=None, parent_id=1),
            GorgiasResumeConfig(cursor=None, parent_id=3),
            GorgiasResumeConfig(cursor=None, parent_id=5),
        ]
        assert result.final_state == GorgiasResumeConfig(cursor=None, parent_id=5)

    @parameterized.expand(
        [
            ("mid_view", GorgiasResumeConfig(cursor=NEXT_LINK, parent_id=3), "/api/views/3/items", "abc"),
            ("view_complete", GorgiasResumeConfig(cursor=None, parent_id=3), "/api/views/5/items", None),
            ("view_deleted", GorgiasResumeConfig(cursor=NEXT_LINK, parent_id=2), "/api/views/3/items", None),
        ]
    )
    def test_resume_skips_completed_views(
        self, _name: str, state: GorgiasResumeConfig, first_path: str, first_cursor: str | None
    ) -> None:
        result = _driver().run("view_items", [VIEWS_PAGE, _items([]), _items([])], resume_state=state)

        assert result.raised is None
        assert result.paths[1] == first_path
        assert result.requests[1].param("cursor") == first_cursor
        assert "/api/views/1/items" not in result.paths


class TestServerFilteredIncremental:
    def test_filters_from_watermark_ascending_on_every_page(self) -> None:
        result = _driver().run(
            "events",
            [
                _page([{"id": 1, "created_datetime": "2023-06-01T00:00:00"}], cursor="c2"),
                _page([{"id": 2, "created_datetime": "2023-06-02T00:00:00"}]),
            ],
            incremental_field="created_datetime",
            db_incremental_field_last_value=datetime(2023, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == [1, 2]
        assert [
            (r.param("order_by"), r.param("created_datetime[gte]"), r.param("cursor")) for r in result.requests
        ] == [
            ("created_datetime:asc", "2023-06-01T00:00:00+00:00", None),
            ("created_datetime:asc", "2023-06-01T00:00:00+00:00", "c2"),
        ]


class TestIncrementalSync:
    def test_first_incremental_sync_walks_all_pages(self) -> None:
        result = _driver().run(
            "tickets",
            [
                _page([{"id": 2, "updated_datetime": "2023-07-01T00:00:00+00:00"}], cursor="c2"),
                _page([{"id": 1, "updated_datetime": "2023-01-01T00:00:00+00:00"}]),
            ],
            incremental_field="updated_datetime",
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == [2, 1]
        assert len(result.requests) == 2

    def test_stops_once_page_predates_watermark(self) -> None:
        # Rows arrive newest-first; the third page is never fetched because the second
        # page is entirely older than the watermark.
        result = _driver().run(
            "tickets",
            [
                _page([{"id": 3, "updated_datetime": "2023-07-01T00:00:00+00:00"}], cursor="c2"),
                _page([{"id": 2, "updated_datetime": "2023-05-01T00:00:00+00:00"}], cursor="c3"),
                _page([{"id": 1, "updated_datetime": "2023-04-01T00:00:00+00:00"}]),
            ],
            incremental_field="updated_datetime",
            db_incremental_field_last_value=datetime(2023, 6, 1, tzinfo=UTC),
        )

        # The over-the-watermark page is still yielded (merge dedupes), then we stop.
        assert result.raised is None
        assert [item["id"] for item in result.rows] == [3, 2]
        assert len(result.requests) == 2


# Per-endpoint `order_by` enums quoted from the Gorgias API docs (the `.md` reference for
# each list endpoint). This is the external contract our config must not drift from: if an
# endpoint is configured to sort by a field absent here, Gorgias would reject or ignore it.
DOCUMENTED_ORDER_BY_DATETIME_FIELDS: dict[str, set[str]] = {
    "tickets": {"created_datetime", "updated_datetime"},
    "messages": {"created_datetime"},
    "customers": {"created_datetime", "updated_datetime"},
    "users": {"created_datetime"},  # also name/email/role, but no updated_datetime
    "satisfaction_surveys": {"created_datetime"},
    "macros": {"created_datetime", "updated_datetime"},
    "tags": {"created_datetime"},
    "views": {"created_datetime"},
    "teams": {"created_datetime"},
    "custom_fields": set(),  # only priority:asc/desc
    "voice_calls": set(),  # accepts no order_by
    "ticket_tags": {"created_datetime", "updated_datetime"},
    "ticket_field_values": {"created_datetime", "updated_datetime"},
    "events": {"created_datetime"},
    "voice_call_events": set(),  # accepts no order_by
    "voice_call_recordings": set(),  # accepts no order_by
    "customer_field_values": {"created_datetime", "updated_datetime"},
    "view_items": {"created_datetime"},  # sorts the parent view list
    "integrations": {"created_datetime"},
    "rules": {"created_datetime"},
    "widgets": {"created_datetime"},
}
DOCUMENTED_NON_DATETIME_ORDER_BY: dict[str, set[str]] = {
    "custom_fields": {"priority:asc", "priority:desc"},
    "widgets": {"order:asc", "order:desc"},
}


class TestApiContract:
    """Pin the endpoint config to the documented Gorgias API so it can't silently drift."""

    def test_sortable_fields_match_documented_api(self) -> None:
        assert {name: set(config.sortable_datetime_fields) for name, config in GORGIAS_ENDPOINTS.items()} == (
            DOCUMENTED_ORDER_BY_DATETIME_FIELDS
        )

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_full_refresh_order_by_is_accepted_by_endpoint(self, endpoint: str) -> None:
        config = GORGIAS_ENDPOINTS[endpoint]
        accepted = {
            f"{field}:{direction}"
            for field in DOCUMENTED_ORDER_BY_DATETIME_FIELDS[endpoint]
            for direction in ("asc", "desc")
        } | DOCUMENTED_NON_DATETIME_ORDER_BY.get(endpoint, set())
        if accepted:
            assert config.order_by in accepted
        else:
            assert config.order_by is None

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_advertised_incremental_fields_are_sortable(self, endpoint: str) -> None:
        config = GORGIAS_ENDPOINTS[endpoint]
        advertised = {f["field"] for f in config.incremental_fields}
        # Every advertised cursor field must be one Gorgias actually accepts in order_by.
        assert advertised <= DOCUMENTED_ORDER_BY_DATETIME_FIELDS[endpoint]
        # supports_incremental and the field list must agree.
        assert bool(advertised) == config.supports_incremental

    def test_incremental_endpoints_use_updated_when_available_else_created(self) -> None:
        # Mutable resources must track updates when the API lets them; append-only ones
        # track creation. This guards the core correctness decision per endpoint.
        expected = {
            "tickets": "updated_datetime",
            "customers": "updated_datetime",
            "macros": "updated_datetime",
            "messages": "created_datetime",
            "satisfaction_surveys": "created_datetime",
            "events": "created_datetime",
        }
        actual = {
            name: config.incremental_fields[0]["field"]
            for name, config in GORGIAS_ENDPOINTS.items()
            if config.supports_incremental
        }
        assert actual == expected


class TestGorgiasSource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])] * len(GORGIAS_ENDPOINTS[endpoint].param_variants))
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == list(GORGIAS_ENDPOINTS[endpoint].primary_keys)
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [GORGIAS_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            (name, config.incremental_fields[0]["field"])
            for name, config in GORGIAS_ENDPOINTS.items()
            if config.supports_incremental and not config.filterable_datetime_fields
        ]
    )
    def test_incremental_source_response_sorts_descending(self, endpoint: str, incremental_field: str) -> None:
        result = _driver().run(
            endpoint,
            [_page([])],
            incremental_field=incremental_field,
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.sort_mode == "desc"

    def test_every_endpoint_partitions_on_created_datetime(self) -> None:
        for config in GORGIAS_ENDPOINTS.values():
            assert config.partition_key in ("created_datetime", "ticket_created_datetime", "customer_created_datetime")
            assert "updated" not in config.partition_key
