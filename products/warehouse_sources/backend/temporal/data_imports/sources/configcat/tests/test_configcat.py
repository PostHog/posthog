from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat import configcat
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.configcat import (
    CONFIGCAT_BASE_URL,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import (
    CONFIGCAT_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.source import ConfigCatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.configcat import (
    ConfigCatSourceConfig,
)


def _driver() -> SourceDriver:
    config = ConfigCatSourceConfig(basic_auth_username="user", basic_auth_password="pass")
    return SourceDriver(ConfigCatSource(), config)


def _run(endpoint: str, bodies: dict[str, Any], **inputs: Any) -> DriveResult:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        path = request.url.removeprefix(CONFIGCAT_BASE_URL)
        if path not in bodies:
            raise UnexpectedRequest(f"no scripted answer for {path}")
        return ScriptedResponse(json=bodies[path])

    return _driver().run(endpoint, respond, **inputs)


class TestConfigCatSource:
    def test_non_list_body_fails_loud(self) -> None:
        result = _run("products", {"/v1/products": {"error": "nope"}})

        # A 200 body that isn't a bare array means the response shape changed — fail loud instead of
        # syncing the stray object as a single row.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestConfigCatFanOut:
    @parameterized.expand(
        [
            ("configs", "/v1/products/{}/configs", "configId"),
            ("environments", "/v1/products/{}/environments", "environmentId"),
        ]
    )
    def test_product_children_are_fetched_once_per_product(self, endpoint: str, child_path: str, id_field: str) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}, {"productId": "p2"}],
            child_path.format("p1"): [{id_field: "a"}],
            child_path.format("p2"): [{id_field: "b"}],
        }
        result = _run(endpoint, bodies)

        assert result.raised is None
        assert result.rows == [{id_field: "a"}, {id_field: "b"}]
        assert result.paths == ["/v1/products", child_path.format("p1"), child_path.format("p2")]

    def test_settings_walk_products_then_configs(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1"}, {"configId": "c2"}],
            "/v1/configs/c1/settings": [{"settingId": 1, "configId": "c1"}],
            "/v1/configs/c2/settings": [{"settingId": 1, "configId": "c2"}],
        }
        result = _run("settings", bodies)

        # `settingId` repeats across configs, which is why the key is composite.
        assert result.raised is None
        assert result.rows == [{"settingId": 1, "configId": "c1"}, {"settingId": 1, "configId": "c2"}]
        assert result.paths[-2:] == ["/v1/configs/c1/settings", "/v1/configs/c2/settings"]

    def test_setting_values_pair_configs_with_environments_of_the_same_product(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}, {"productId": "p2"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v1/products/p2/configs": [{"configId": "c2", "evaluationVersion": "v2"}],
            "/v1/products/p2/environments": [{"environmentId": "e2"}],
            "/v2/configs/c1/environments/e1/values": {
                "settingFormulas": [{"setting": {"settingId": 7}, "defaultValue": {"boolValue": True}}]
            },
            "/v2/configs/c2/environments/e2/values": {
                "settingFormulas": [{"setting": {"settingId": 7}, "defaultValue": {"boolValue": False}}]
            },
        }
        result = _run("setting_values", bodies)

        # A config only has values in its own product's environments — c1/e2 is not a valid pair.
        assert result.raised is None
        assert [path for path in result.paths if path.startswith("/v2/")] == [
            "/v2/configs/c1/environments/e1/values",
            "/v2/configs/c2/environments/e2/values",
        ]
        # The envelope carries the config and environment, so they're lifted onto each row to
        # complete the primary key.
        assert [(row["configId"], row["environmentId"], row["settingId"]) for row in result.rows] == [
            ("c1", "e1", 7),
            ("c2", "e2", 7),
        ]
        assert result.rows[0]["defaultValue"] == {"boolValue": True}

    def test_setting_values_non_object_body_fails_loud(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v2/configs/c1/environments/e1/values": [],
        }
        result = _run("setting_values", bodies)
        assert isinstance(result.raised, ValueError)
        assert "non-object values body" in str(result.raised)

    def test_v1_setting_values_use_v1_endpoint(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v1"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v1/configs/c1/environments/e1/values": {"settingValues": [{"setting": {"settingId": 7}, "value": True}]},
        }

        result = _run("setting_values", bodies)

        assert result.raised is None
        assert result.paths[-1] == "/v1/configs/c1/environments/e1/values"
        assert result.rows == [
            {
                "setting": {"settingId": 7},
                "settingId": 7,
                "value": True,
                "configId": "c1",
                "environmentId": "e1",
            }
        ]

    @parameterized.expand(
        [
            ("non_object_row", [{"productId": "p1"}, "bad"], "non-object row"),
            ("missing_id", [{"name": "missing id"}], "invalid productId"),
        ]
    )
    def test_malformed_fan_out_parent_fails_loud(self, _name: str, products: Any, error: str) -> None:
        result = _run("configs", {"/v1/products": products})
        assert isinstance(result.raised, ValueError)
        assert error in str(result.raised)

    def test_malformed_setting_formula_fails_loud(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v2/configs/c1/environments/e1/values": {"settingFormulas": [{"setting": {}}]},
        }

        result = _run("setting_values", bodies)
        assert isinstance(result.raised, ValueError)
        assert "invalid settingId" in str(result.raised)

    def test_fan_out_list_endpoint_non_list_body_fails_loud(self) -> None:
        result = _run("configs", {"/v1/products": {"error": "nope"}})
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


def _audit_page(rows: list[dict[str, Any]], has_next: bool) -> dict[str, Any]:
    return {"data": rows, "paging": {"currentPage": 1, "totalPages": 1, "pageSize": 100, "hasNext": has_next}}


class TestConfigCatAuditLogs:
    def test_empty_page_stops_the_walk_even_when_has_next_stays_true(self) -> None:
        # A page past the end comes back empty. Trusting `hasNext` alone would page forever.
        bodies = {
            "/v1/organizations": [{"organizationId": "o1"}],
            "/v2/organizations/o1/auditlogs?pageNumber=1&pageSize=100": _audit_page([{"auditLogId": 1}], True),
            "/v2/organizations/o1/auditlogs?pageNumber=2&pageSize=100": _audit_page([], True),
        }
        result = _run("audit_logs", bodies)

        assert result.raised is None
        assert result.rows == [{"auditLogId": 1, "organizationId": "o1"}]
        assert len(result.paths) == 3

    def test_incremental_run_bounds_the_request_with_the_watermark(self) -> None:
        bodies = {
            "/v1/organizations": [{"organizationId": "o1"}],
            "/v2/organizations/o1/auditlogs"
            "?pageNumber=1&pageSize=100&fromUtcDateTime=2024-05-01T10%3A00%3A00%2B00%3A00": _audit_page([], False),
        }
        result = _run(
            "audit_logs",
            bodies,
            incremental_field="auditLogDateTime",
            db_incremental_field_last_value=datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.requests[1].param("fromUtcDateTime") == "2024-05-01T10:00:00+00:00"

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 5, 1, 10, 0), "2024-05-01T10:00:00+00:00"),
            (
                "other_timezone",
                datetime(2024, 5, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))),
                "2024-05-01T10:00:00+00:00",
            ),
            ("iso_string", "2024-05-01T10:00:00+00:00", "2024-05-01T10:00:00+00:00"),
            ("unparseable_string", "not a date", None),
            ("no_watermark", None, None),
        ]
    )
    def test_watermark_is_coerced_to_utc(self, _name: str, value: Any, expected: str | None) -> None:
        # `fromUtcDateTime` is a UTC filter, so a naive or offset value has to be converted rather
        # than sent as written — a two-hour offset would otherwise skip two hours of history.
        assert configcat._to_configcat_datetime(value) == expected

    @parameterized.expand(
        [
            ("missing_data", {"paging": {"hasNext": False}}, "invalid auditlogs data"),
            ("missing_paging", {"data": []}, "invalid auditlogs paging"),
            ("non_boolean_has_next", {"data": [], "paging": {"hasNext": "yes"}}, "invalid auditlogs paging"),
        ]
    )
    def test_malformed_page_fails_loud(self, _name: str, page: dict[str, Any], error: str) -> None:
        # Losing `hasNext` would otherwise end the walk quietly, and the run would commit a
        # watermark past every row it never asked for.
        bodies = {
            "/v1/organizations": [{"organizationId": "o1"}],
            "/v2/organizations/o1/auditlogs?pageNumber=1&pageSize=100": page,
        }
        result = _run("audit_logs", bodies)
        assert isinstance(result.raised, ValueError)
        assert error in str(result.raised)


class TestConfigCatEnvelopeEndpoints:
    def test_stale_flags_flatten_to_one_row_per_flag(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/staleflags": {
                "productId": "p1",
                "name": "Main",
                "environments": [{"environmentId": "e1", "name": "Production"}],
                "configs": [
                    {
                        "configId": "c1",
                        "name": "Main config",
                        "settings": [
                            {
                                "settingId": 1,
                                "key": "old_flag",
                                "settingValues": [{"environmentId": "e1", "isStale": True}],
                            },
                            {"settingId": 2, "key": "older_flag", "settingValues": []},
                        ],
                    }
                ],
            },
        }
        result = _run("stale_flags", bodies)

        # The report nests flags under configs under one product, and repeats neither id on the
        # flag, so both are lifted onto each row to complete the primary key.
        assert result.raised is None
        assert [(row["productId"], row["configId"], row["settingId"]) for row in result.rows] == [
            ("p1", "c1", 1),
            ("p1", "c1", 2),
        ]
        assert result.rows[0]["configName"] == "Main config"
        assert result.rows[0]["settingValues"] == [{"environmentId": "e1", "isStale": True}]

    def test_organization_members_keep_one_row_per_role(self) -> None:
        bodies = {
            "/v1/organizations": [{"organizationId": "o1"}],
            "/v2/organizations/o1/members": {
                "admins": [{"userId": "u1", "email": "a@example.com"}],
                "billingManagers": [{"userId": "u1", "email": "a@example.com"}],
                "members": [{"userId": "u2", "email": "b@example.com", "permissions": []}],
            },
        }
        result = _run("organization_members", bodies)

        # u1 is both an admin and a billing manager, which is why the role is part of the key —
        # without it the two rows would collide and the merge would keep only one.
        assert result.raised is None
        assert [(row["organizationId"], row["userId"], row["memberType"]) for row in result.rows] == [
            ("o1", "u1", "admin"),
            ("o1", "u1", "billingManager"),
            ("o1", "u2", "member"),
        ]

    @parameterized.expand(
        [
            (
                "stale_flags",
                {"/v1/products": [{"productId": "p1"}], "/v1/products/p1/staleflags": []},
                "non-object staleflags body",
            ),
            (
                "organization_members",
                {"/v1/organizations": [{"organizationId": "o1"}], "/v2/organizations/o1/members": {"admins": []}},
                "invalid billingManagers",
            ),
        ]
    )
    def test_malformed_envelope_fails_loud(self, endpoint: str, bodies: dict[str, Any], error: str) -> None:
        result = _run(endpoint, bodies)
        assert isinstance(result.raised, ValueError)
        assert error in str(result.raised)

    @parameterized.expand(
        [
            ("product_members", "/v1/products/{}/members", {"userId": "u1", "productId": "p1"}),
            ("tags", "/v1/products/{}/tags", {"tagId": 4, "name": "cleanup"}),
        ]
    )
    def test_product_listings_are_fetched_once_per_product(
        self, endpoint: str, child_path: str, row: dict[str, Any]
    ) -> None:
        bodies = {"/v1/products": [{"productId": "p1"}], child_path.format("p1"): [row]}
        result = _run(endpoint, bodies)

        assert result.raised is None
        assert result.rows == [row]
        assert result.paths == ["/v1/products", child_path.format("p1")]

    def test_tag_settings_walk_products_then_tags(self) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/tags": [{"tagId": 4}, {"tagId": 5}],
            "/v1/tags/4/settings": [{"settingId": 1, "configId": "c1"}],
            "/v1/tags/5/settings": [{"settingId": 1, "configId": "c1"}],
        }
        result = _run("tag_settings", bodies)

        # The same flag carries both tags, so the tag is part of the key and is lifted onto the row
        # as the integer the tags table stores it under.
        assert result.raised is None
        assert [(row["tagId"], row["configId"], row["settingId"]) for row in result.rows] == [
            (4, "c1", 1),
            (5, "c1", 1),
        ]
        assert result.paths[-2:] == ["/v1/tags/4/settings", "/v1/tags/5/settings"]


class TestCheckAccess:
    @parameterized.expand(
        [
            (200, True, 200, None),
        ]
    )
    def test_status_mapping(
        self,
        status: int,
        _ok: bool,
        expected_status: int,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access("user", "pass") == (expected_status, expected_message)
        assert network.requests_log[0].path == "/v1/organizations"


class TestConfigCatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == CONFIGCAT_ENDPOINTS[endpoint].primary_keys
        # Only an endpoint with a stable timestamp is partitioned on it; the rest expose none.
        partition_key = CONFIGCAT_ENDPOINTS[endpoint].partition_key
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)

    @parameterized.expand([(name,) for name, config in CONFIGCAT_ENDPOINTS.items() if config.parent is not None])
    def test_fan_out_keys_include_every_parent_in_the_path(self, endpoint: str) -> None:
        # A fan-out table aggregates rows from every parent, so a key missing a parent id seeds
        # duplicates that every later merge multi-matches.
        config = CONFIGCAT_ENDPOINTS[endpoint]
        for placeholder in ("configId", "environmentId", "tagId", "organizationId"):
            if f"{{{placeholder}}}" in config.path:
                assert placeholder in config.primary_keys
