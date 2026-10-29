from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightfield import (
    LightfieldSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield import check_token
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import (
    STANDARD_DEFINITION_RESOURCES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.source import LightfieldSource


def _driver() -> SourceDriver:
    return SourceDriver(LightfieldSource(), LightfieldSourceConfig(api_key="sk_lf_test"))


class TestLightfieldSourceResponse:
    @parameterized.expand(
        [
            ("accounts", ["id"], ["createdAt"], "datetime"),
            ("custom_objects", ["objectType", "id"], ["createdAt"], "datetime"),
            ("field_definitions", ["ownerObjectType", "key"], None, None),
            ("relationship_definitions", ["ownerObjectType", "key"], None, None),
        ]
    )
    def test_source_response_shape(
        self,
        endpoint: str,
        primary_keys: list[str],
        partition_keys: list[str] | None,
        partition_mode: str | None,
    ) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json={"data": [], "totalCount": 0})))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.partition_keys == partition_keys
        assert result.response.partition_mode == partition_mode


class TestCustomObjects:
    def test_walks_every_type_to_its_terminal_page_and_tags_rows(self) -> None:
        first_page = [{"id": f"p{i}", "createdAt": "2026-01-01T00:00:00Z"} for i in range(25)]
        result = _driver().run(
            "custom_objects",
            [
                ScriptedResponse(json={"data": [{"objectType": "project"}, {"objectType": "vendor"}]}),
                ScriptedResponse(json={"data": first_page, "totalCount": 26}),
                ScriptedResponse(json={"data": [{"id": "p25"}], "totalCount": 26}),
                ScriptedResponse(json={"data": [{"id": "p0"}], "totalCount": 1}),
            ],
        )

        assert result.raised is None
        assert [(row["objectType"], row["id"]) for row in result.rows] == [
            *[("project", f"p{i}") for i in range(26)],
            ("vendor", "p0"),
        ]
        assert result.paths == [
            "/v1/objects",
            "/v1/objects/project",
            "/v1/objects/project",
            "/v1/objects/vendor",
        ]
        assert result.params("offset") == [None, "0", "25", "0"]
        assert all(request.headers["lightfield-version"] == "2026-03-01" for request in result.requests)

    def test_unavailable_custom_objects_fail_the_table(self) -> None:
        result = _driver().run("custom_objects", [ScriptedResponse(status=403, json={"error": "forbidden"})])

        assert isinstance(result.raised, HTTPError)


class TestDefinitions:
    @parameterized.expand(
        [
            ("custom_objects_listed", 200, ["account", "contact", "project"]),
            ("custom_objects_unavailable", 404, ["account", "contact"]),
        ]
    )
    def test_flattens_each_readable_type(self, _name: str, objects_status: int, expected_owners: list[str]) -> None:
        answers = [
            ScriptedResponse(
                status=objects_status,
                json={"data": [{"objectType": "project", "label": "Project"}]},
            )
        ]
        readable = {"account", "contact"}
        for resource in STANDARD_DEFINITION_RESOURCES:
            if resource.object_type in readable:
                answers.append(
                    ScriptedResponse(
                        json={
                            "objectType": resource.object_type,
                            "fieldDefinitions": {"$name": {"label": "Name", "valueType": "TEXT"}},
                            "relationshipDefinitions": {
                                "$owner": {"label": "Owner", "cardinality": "HAS_ONE", "objectType": "member"}
                            },
                        },
                    )
                )
            else:
                answers.append(ScriptedResponse(status=403, json={"error": "missing scope"}))
        if objects_status == 200:
            answers.append(
                ScriptedResponse(
                    json={
                        "objectType": "project",
                        "fieldDefinitions": {"budget": {"label": "Budget", "valueType": "CURRENCY"}},
                        "relationshipDefinitions": {},
                    }
                )
            )

        field_result = _driver().run("field_definitions", answers)
        relationship_result = _driver().run("relationship_definitions", answers)

        assert field_result.raised is None
        assert relationship_result.raised is None
        assert [row["ownerObjectType"] for row in field_result.rows] == expected_owners
        assert {(row["ownerObjectType"], row["key"]) for row in field_result.rows} >= {("account", "$name")}
        assert relationship_result.rows == [
            {
                "label": "Owner",
                "cardinality": "HAS_ONE",
                "objectType": "member",
                "ownerObjectType": owner,
                "key": "$owner",
            }
            for owner in ["account", "contact"]
        ]


class TestCheckToken:
    @parameterized.expand(
        [
            (
                "active_key_with_scopes",
                200,
                {"active": True, "scopes": ["accounts:read"], "tokenType": "api_key"},
                (True, ["accounts:read"], None),
            ),
            (
                "active_key_without_scope_list",
                200,
                {"active": True},
                (True, None, None),
            ),
            (
                "inactive_key",
                200,
                {"active": False, "scopes": []},
                (False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."),
            ),
            (
                "unauthorized",
                401,
                {"error": "unauthorized"},
                (False, None, "Invalid Lightfield API key. Check the key and try again."),
            ),
            (
                "server_error",
                503,
                {"error": "oops"},
                (False, None, "Lightfield returned an unexpected status (503) while validating the key."),
            ),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        body: dict[str, Any],
        expected: tuple[bool, list[str] | None, str | None],
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            actual = check_token("sk_lf_test", "2026-03-01")

        assert actual == expected
        assert {request.method for request in network.requests_log} == {"GET"}
        assert {request.path for request in network.requests_log} == {"/v1/auth/validate"}
        assert all(request.headers["authorization"] == "Bearer sk_lf_test" for request in network.requests_log)
        assert all(request.headers["lightfield-version"] == "2026-03-01" for request in network.requests_log)
        assert network.session_options == [{"redact_values": ("sk_lf_test",)}]
