from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.lightfield._config import LightfieldSourceConfig
from products.warehouse_sources.sources.lightfield.lightfield import check_token
from products.warehouse_sources.sources.lightfield.settings import STANDARD_DEFINITION_RESOURCES
from products.warehouse_sources.sources.lightfield.source import LightfieldSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(LightfieldSource(), LightfieldSourceConfig(api_key="sk_lf_test"))


class TestLightfieldSourceResponse:
    @parameterized.expand(
        [
            ("accounts", ["id"], ["createdAt"], "datetime"),
            ("custom_objects", ["objectType", "id"], ["createdAt"], "datetime"),
            ("sequence_enrollments", ["sequenceId", "id"], ["enrolledAt"], "datetime"),
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


def _rows(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{i}", "createdAt": "2026-01-01T00:00:00Z"} for i in range(count)]


def _list(list_id: str, object_type: str | None) -> dict[str, Any]:
    fields = {"$name": {"value": list_id, "valueType": "TEXT"}}
    if object_type is not None:
        fields["$objectType"] = {"value": object_type, "valueType": "TEXT"}
    return {"id": list_id, "fields": fields}


class TestTotalCountPaging:
    @parameterized.expand(
        [
            # Access filtering can shorten or empty a page while records remain.
            ("short_and_empty_pages_before_total", [(20, 60), (0, 60), (3, 60)], ["0", "25", "50"], 23),
            ("total_reached_on_full_page", [(25, 50), (25, 50)], ["0", "25"], 50),
            ("no_total_stops_at_short_page", [(25, None), (4, None)], ["0", "25"], 29),
            ("no_total_stops_at_empty_page", [(0, None)], ["0"], 0),
        ]
    )
    def test_messages_page_until_total_count(
        self, _name: str, pages: list[tuple[int, int | None]], expected_offsets: list[str], expected_rows: int
    ) -> None:
        answers = [
            ScriptedResponse(
                json={"data": _rows(f"m{index}_", count), **({"totalCount": total} if total is not None else {})}
            )
            for index, (count, total) in enumerate(pages)
        ]
        result = _driver().run("messages", answers)

        assert result.raised is None
        assert len(result.rows) == expected_rows
        assert set(result.paths) == {"/v1/messages"}
        assert result.params("offset") == expected_offsets
        assert set(result.params("limit")) == {"25"}


class TestSequenceEnrollments:
    def test_walks_each_sequence_and_tags_rows_with_its_id(self) -> None:
        result = _driver().run(
            "sequence_enrollments",
            [
                ScriptedResponse(json={"data": [{"id": "seq_a"}, {"id": "seq_gone"}], "totalCount": 27}),
                ScriptedResponse(json={"data": [{"id": "seq b"}], "totalCount": 27}),
                ScriptedResponse(json={"data": _rows("e", 25), "totalCount": 26}),
                ScriptedResponse(json={"data": [{"id": "e25"}], "totalCount": 26}),
                ScriptedResponse(status=404, json={"error": "not_found"}),
                ScriptedResponse(json={"data": [{"id": "e0"}], "totalCount": 1}),
            ],
        )

        assert result.raised is None
        assert [(row["sequenceId"], row["id"]) for row in result.rows] == [
            *[("seq_a", f"e{i}") for i in range(26)],
            ("seq b", "e0"),
        ]
        assert result.paths == [
            "/v1/sequences",
            "/v1/sequences",
            "/v1/sequences/seq_a/enrollments",
            "/v1/sequences/seq_a/enrollments",
            "/v1/sequences/seq_gone/enrollments",
            "/v1/sequences/seq%20b/enrollments",
        ]
        assert result.params("offset") == ["0", "25", "0", "25", "0", "0"]

    def test_denied_scope_fails_the_table(self) -> None:
        result = _driver().run("sequence_enrollments", [ScriptedResponse(status=403, json={"error": "forbidden"})])

        assert isinstance(result.raised, HTTPError)


class TestListMembers:
    @parameterized.expand(
        [
            ("list_accounts", "accounts", ["acc_list", "acc_list_plain"]),
            ("list_contacts", "contacts", ["con_list"]),
            ("list_opportunities", "opportunities", []),
        ]
    )
    def test_reads_only_lists_of_its_object_type(
        self, endpoint: str, member_path: str, expected_lists: list[str]
    ) -> None:
        lists = [
            _list("acc_list", "$account"),
            _list("con_list", "$contact"),
            _list("acc_list_plain", "account"),
            _list("untyped_list", None),
        ]
        answers = [ScriptedResponse(json={"data": lists, "totalCount": len(lists)})]
        answers += [
            ScriptedResponse(json={"data": [{"id": f"{list_id}_member"}], "totalCount": 1})
            for list_id in expected_lists
        ]
        result = _driver().run(endpoint, answers)

        assert result.raised is None
        assert result.paths == ["/v1/lists", *[f"/v1/lists/{list_id}/{member_path}" for list_id in expected_lists]]
        assert [(row["listId"], row["id"]) for row in result.rows] == [
            (list_id, f"{list_id}_member") for list_id in expected_lists
        ]


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
