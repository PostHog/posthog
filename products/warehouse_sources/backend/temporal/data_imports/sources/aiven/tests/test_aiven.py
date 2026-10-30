from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.aiven import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import AIVEN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.source import AivenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aiven import AivenSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(AivenSource(), AivenSourceConfig.from_dict({"api_token": "tok"}))


class TestListExtraction:
    @parameterized.expand(
        [
            ("present", {"projects": [{"project_name": "p1"}]}, [{"project_name": "p1"}]),
            ("missing_key", {"other": []}, []),
            ("null_value", {"projects": None}, []),
            ("empty_list", {"projects": []}, []),
        ]
    )
    def test_extracts_rows_under_data_key(
        self, _name: str, body: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        result = _driver().run("projects", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.paths == ["/v1/project"]
        assert result.rows == expected


class TestFanOut:
    def test_fan_out_project_injects_parent_project_name(self) -> None:
        # `services` items carry no project field, so the parent's `project_name` must be injected
        # to keep the composite primary key unique across projects.
        result = _driver().run(
            "services",
            route(
                {
                    "/project": [ScriptedResponse(json={"projects": [{"project_name": "p1"}, {"project_name": "p2"}]})],
                    "/project/p1/service": [ScriptedResponse(json={"services": [{"service_name": "s1"}]})],
                    "/project/p2/service": [ScriptedResponse(json={"services": [{"service_name": "s2"}]})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"service_name": "s1", "project_name": "p1"},
            {"service_name": "s2", "project_name": "p2"},
        ]

    def test_fan_out_organization_injects_org(self) -> None:
        result = _driver().run(
            "organization_users",
            route(
                {
                    "/organizations": [ScriptedResponse(json={"organizations": [{"organization_id": "org1"}]})],
                    "/organization/org1/user": [ScriptedResponse(json={"users": [{"user_id": "u1"}]})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1", "organization_id": "org1"}]

    def test_fan_out_organization_setdefault_keeps_existing_org_id(self) -> None:
        # billing_groups already carry organization_id; injection must not clobber it.
        result = _driver().run(
            "billing_groups",
            route(
                {
                    "/organizations": [ScriptedResponse(json={"organizations": [{"organization_id": "org1"}]})],
                    "/organization/org1/billing-groups": [
                        ScriptedResponse(
                            json={"billing_groups": [{"billing_group_id": "bg1", "organization_id": "org-real"}]}
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"billing_group_id": "bg1", "organization_id": "org-real"}]

    def test_fan_out_invoice_two_levels_injects_org_and_invoice(self) -> None:
        result = _driver().run(
            "invoice_lines",
            route(
                {
                    "/organizations": [ScriptedResponse(json={"organizations": [{"organization_id": "org1"}]})],
                    "/organization/org1/invoices": [
                        ScriptedResponse(json={"invoices": [{"invoice_number": "inv1"}, {"invoice_number": "inv2"}]})
                    ],
                    "/organization/org1/invoice/inv1/lines": [
                        ScriptedResponse(json={"lines": [{"line_type": "usage"}]})
                    ],
                    "/organization/org1/invoice/inv2/lines": [
                        ScriptedResponse(json={"lines": [{"line_type": "credit"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"line_type": "usage", "organization_id": "org1", "invoice_number": "inv1"},
            {"line_type": "credit", "organization_id": "org1", "invoice_number": "inv2"},
        ]

    def test_two_level_injects_both_org_and_group(self) -> None:
        # user_group_members fans out organization -> user-groups -> members; the child rows carry
        # neither id, so both must be injected to keep the composite key unique table-wide.
        result = _driver().run(
            "user_group_members",
            route(
                {
                    "/organizations": [ScriptedResponse(json={"organizations": [{"organization_id": "org1"}]})],
                    "/organization/org1/user-groups": [
                        ScriptedResponse(json={"user_groups": [{"user_group_id": "g1"}]})
                    ],
                    "/organization/org1/user-groups/g1/members": [
                        ScriptedResponse(json={"members": [{"user_id": "u1"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1", "organization_id": "org1", "user_group_id": "g1"}]

    def test_two_level_single_placeholder_injects_only_declared_param(self) -> None:
        # billing_group_projects binds only {billing_group_id}, so only that id is injected — the
        # grandparent organization_id must not leak onto the row.
        result = _driver().run(
            "billing_group_projects",
            route(
                {
                    "/organizations": [ScriptedResponse(json={"organizations": [{"organization_id": "org1"}]})],
                    "/organization/org1/billing-groups": [
                        ScriptedResponse(json={"billing_groups": [{"billing_group_id": "bg1"}]})
                    ],
                    "/billing-group/bg1/projects": [ScriptedResponse(json={"projects": [{"project_name": "p1"}]})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"project_name": "p1", "billing_group_id": "bg1"}]


class TestFailLoud:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_surface(self, _name: str, status: int) -> None:
        # A 4xx is non-retryable and must fail the sync loudly rather than syncing 0 rows silently.
        result = _driver().run("projects", [ScriptedResponse(status=status, json={"message": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.rows == []


class TestSourceResponse:
    @parameterized.expand(list(AIVEN_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        config = AIVEN_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(ScriptedResponse(json={})))
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_maps_status_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("tok") is expected

        # The real stack retries a 5xx, so the count of requests is not fixed.
        assert {request.path for request in network.requests_log} == {"/v1/me"}
        assert network.requests_log[0].headers["authorization"] == "aivenv1 tok"
