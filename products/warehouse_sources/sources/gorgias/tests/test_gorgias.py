from datetime import UTC, datetime

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gorgias import (
    GorgiasSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    get_base_url,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.settings import (
    ENDPOINTS,
    GORGIAS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source import GorgiasSource


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
}
DOCUMENTED_NON_DATETIME_ORDER_BY: dict[str, set[str]] = {
    "custom_fields": {"priority:asc", "priority:desc"},
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
