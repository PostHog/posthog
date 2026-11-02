import datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvest import (
    HarvestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.harvest import (
    HARVEST_API_HOST,
    HarvestResumeConfig,
    _to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import (
    ENDPOINTS,
    HARVEST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.source import HarvestSource


def _page(
    rows: list[dict[str, Any]] | None,
    *,
    data_key: str = "time_entries",
    next_url: str | None = None,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {"links": {"next": next_url}}
    if not drop_key:
        body[data_key] = rows or []
    return ScriptedResponse(json=body)


_TOP_LEVEL_ENDPOINTS = [name for name in ENDPOINTS if HARVEST_ENDPOINTS[name].fanout is None]


def _driver() -> SourceDriver:
    return SourceDriver(HarvestSource(), HarvestSourceConfig(account_id="123456", access_token="pat-secret"))


class TestHarvestTransport:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), "2026-05-04T09:30:00Z"),
            ("naive_datetime", datetime.datetime(2026, 5, 4, 9, 30), "2026-05-04T09:30:00Z"),
            (
                "offset_datetime",
                datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))),
                "2026-05-04T07:30:00Z",
            ),
            ("date", datetime.date(2026, 5, 4), "2026-05-04"),
            ("string_passthrough", "2026-05-04T09:30:00Z", "2026-05-04T09:30:00Z"),
        ]
    )
    def test_to_iso8601(self, _name: str, value: Any, expected: str | None) -> None:
        # `updated_since` only filters when it receives ISO 8601; a naive repr would be ignored
        # or rejected, silently turning an incremental sync into a full one.
        assert _to_iso8601(value) == expected

    def test_follows_links_next_across_pages(self) -> None:
        next_url = f"https://{HARVEST_API_HOST}/v2/time_entries?cursor=abc&per_page=1000"
        result = _driver().run(
            "time_entries",
            [
                _page([{"id": 1}], next_url=next_url),
                _page([{"id": 2}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        # The next link is self-contained, so the original params must not be re-appended.
        assert result.urls[1] == next_url
        assert result.requests[1].query == {"cursor": ("abc",), "per_page": ("1000",)}

    def test_resumes_from_saved_next_url(self) -> None:
        saved = f"https://{HARVEST_API_HOST}/v2/time_entries?cursor=xyz"
        result = _driver().run("time_entries", [_page([{"id": 3}])], resume_state=HarvestResumeConfig(next_url=saved))

        # Picks up at the saved page rather than restarting at the first one.
        assert result.raised is None
        assert result.urls[0] == saved
        assert [row["id"] for row in result.rows] == [3]

    def test_off_host_next_link_is_rejected(self) -> None:
        result = _driver().run(
            "time_entries", [_page([{"id": 1}], next_url="https://evil.example.com/v2/time_entries")]
        )

        # Following a spoofed next link would replay the bearer token off-host.
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("first_sync", True, None, None),
            ("with_watermark", True, datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), "2026-05-04T09:30:00Z"),
            ("full_refresh", False, datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), None),
        ]
    )
    def test_updated_since_is_sent_only_for_incremental_syncs(
        self, _name: str, incremental: bool, last_value: Any, expected: str | None
    ) -> None:
        result = _driver().run(
            "time_entries",
            [_page([{"id": 1}])],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].param("updated_since") == expected
        assert result.requests[0].param("per_page") == str(HARVEST_ENDPOINTS["time_entries"].page_size)

    def test_endpoint_without_updated_since_never_sends_the_filter(self) -> None:
        # Roles has no server-side modified-since filter; sending one would be ignored at best.
        result = _driver().run(
            "roles",
            [_page([{"id": 1}], data_key="roles")],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.datetime(2026, 5, 4, tzinfo=datetime.UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_since") is None

    def test_missing_envelope_key_fails_loud(self) -> None:
        result = _driver().run("time_entries", [_page(None, drop_key=True)])

        # A changed response shape must fail rather than silently sync zero rows.
        assert isinstance(result.raised, Exception)
        assert "time_entries" in str(result.raised)

    @parameterized.expand(_TOP_LEVEL_ENDPOINTS)
    def test_every_endpoint_reads_its_own_envelope_and_path(self, endpoint: str) -> None:
        config = HARVEST_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([{"id": 1}], data_key=config.data_key)])

        # A wrong path 404s; a wrong envelope key yields zero rows.
        assert result.raised is None
        assert result.urls[0].startswith(f"https://{HARVEST_API_HOST}/v2/{config.path}")
        assert [row["id"] for row in result.rows] == [1]
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys

    @parameterized.expand(
        [
            ("invoice_payments", "invoices", "invoice_id", True, None),
            ("invoice_payments", "invoices", "invoice_id", False, None),
            ("user_cost_rates", "users", "user_id", True, datetime.datetime(2026, 5, 4, tzinfo=datetime.UTC)),
            (
                "invoice_payments",
                "invoices",
                "invoice_id",
                True,
                datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC),
            ),
        ]
    )
    def test_fanout_walks_every_parent_and_tags_rows_with_the_parent_id(
        self, endpoint: str, parent: str, parent_key: str, incremental: bool, last_value: Any
    ) -> None:
        config = HARVEST_ENDPOINTS[endpoint]
        parent_data_key = HARVEST_ENDPOINTS[parent].data_key
        parent_next = f"https://{HARVEST_API_HOST}/v2/{parent}?cursor=p2"
        result = _driver().run(
            endpoint,
            route(
                {
                    f"/v2/{parent}": [
                        _page([{"id": 10}], data_key=parent_data_key, next_url=parent_next),
                        _page([{"id": 20}], data_key=parent_data_key),
                    ],
                    f"/v2/{config.path.format(**{parent_key: 10})}": [_page([{"id": 1}], data_key=config.data_key)],
                    f"/v2/{config.path.format(**{parent_key: 20})}": [_page([{"id": 2}], data_key=config.data_key)],
                }
            ),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        # Child ids are only unique per parent, so the parent id must land in the row for the key.
        assert sorted((row[parent_key], row["id"]) for row in result.rows) == [(10, 1), (20, 2)]
        response = result.response
        assert response is not None
        assert response.primary_keys == [parent_key, "id"]
        assert response.sort_mode is None
        # Filtering the parent listing would skip children that changed under an unchanged parent.
        parent_requests = [r for r in result.requests if r.path == f"/v2/{parent}"]
        assert [r.param("updated_since") for r in parent_requests] == [None, None]
        child_requests = [r for r in result.requests if r.path != f"/v2/{parent}"]
        expected = "2026-05-04T09:30:00Z" if last_value is not None and config.supports_updated_since else None
        assert [r.param("updated_since") for r in child_requests] == [expected, expected]

    @parameterized.expand([("invoice_payments", "invoices", "invoice_id"), ("user_cost_rates", "users", "user_id")])
    def test_fanout_skips_a_parent_deleted_mid_sync(self, endpoint: str, parent: str, parent_key: str) -> None:
        config = HARVEST_ENDPOINTS[endpoint]
        result = _driver().run(
            endpoint,
            route(
                {
                    f"/v2/{parent}": [_page([{"id": 10}, {"id": 20}], data_key=HARVEST_ENDPOINTS[parent].data_key)],
                    f"/v2/{config.path.format(**{parent_key: 10})}": [ScriptedResponse(status=404)],
                    f"/v2/{config.path.format(**{parent_key: 20})}": [_page([{"id": 2}], data_key=config.data_key)],
                }
            ),
        )

        # One 404 must not abort the fan-out and drop every later parent's rows.
        assert result.raised is None
        assert [(row[parent_key], row["id"]) for row in result.rows] == [(20, 2)]

    def test_fanout_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "invoice_payments",
            route(
                {
                    "/v2/invoices": [_page([{"id": 10}, {"id": 20}], data_key="invoices")],
                    "/v2/invoices/20/payments": [_page([{"id": 2}], data_key="invoice_payments")],
                }
            ),
            resume_state=HarvestResumeConfig(
                fanout_state={"completed": ["invoices/10/payments"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert "/v2/invoices/10/payments" not in result.paths
        assert [row["id"] for row in result.rows] == [2]

    @parameterized.expand([("time_entries", "created_at"), ("invoices", "created_at"), ("roles", None)])
    def test_partitioning_matches_the_endpoint_config(self, endpoint: str, partition_key: str | None) -> None:
        config = HARVEST_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([], data_key=config.data_key)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, reported = validate_credentials("123456", "pat-secret", "v2")
        assert ok is expected_ok
        assert reported == status
        assert network.requests_log[0].path == "/v2/users/me"
