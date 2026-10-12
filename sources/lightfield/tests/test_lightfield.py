import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import responses
from parameterized import parameterized
from requests import HTTPError, Response

from sources.lightfield.lightfield import check_token, lightfield_source
from sources.lightfield.settings import STANDARD_DEFINITION_RESOURCES

BASE = "https://api.lightfield.app"


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _source(endpoint: str):
    return lightfield_source(
        api_key="sk_lf_test",
        endpoint=endpoint,
        team_id=123,
        job_id="test_job",
        api_version="2026-03-01",
    )


def _rows(endpoint: str) -> list[dict[str, Any]]:
    return [row for page in _source(endpoint).items() for row in page]


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
        source_response = _source(endpoint)

        assert source_response.name == endpoint
        assert source_response.primary_keys == primary_keys
        assert source_response.partition_keys == partition_keys
        assert source_response.partition_mode == partition_mode


class TestCustomObjects:
    @responses.activate
    def test_walks_every_type_to_its_terminal_page_and_tags_rows(self) -> None:
        responses.get(
            f"{BASE}/v1/objects",
            json={"data": [{"objectType": "project", "label": "Project"}, {"objectType": "vendor", "label": "Vendor"}]},
        )
        first_page = [{"id": f"p{i}", "createdAt": "2026-01-01T00:00:00Z"} for i in range(25)]
        responses.get(f"{BASE}/v1/objects/project", json={"data": first_page, "totalCount": 26})
        responses.get(f"{BASE}/v1/objects/project", json={"data": [{"id": "p25"}], "totalCount": 26})
        responses.get(f"{BASE}/v1/objects/vendor", json={"data": [{"id": "p0"}], "totalCount": 1})

        rows = _rows("custom_objects")

        assert [(row["objectType"], row["id"]) for row in rows] == [
            *[("project", f"p{i}") for i in range(26)],
            ("vendor", "p0"),
        ]
        record_calls = [call for call in responses.calls if urlparse(call.request.url).path != "/v1/objects"]
        assert [
            (urlparse(call.request.url).path, parse_qs(urlparse(call.request.url).query)["offset"])
            for call in record_calls
        ] == [("/v1/objects/project", ["0"]), ("/v1/objects/project", ["25"]), ("/v1/objects/vendor", ["0"])]
        assert all(call.request.headers["Lightfield-Version"] == "2026-03-01" for call in responses.calls)

    @responses.activate
    def test_unavailable_custom_objects_fail_the_table(self) -> None:
        responses.get(f"{BASE}/v1/objects", json={"error": "forbidden"}, status=403)

        with pytest.raises(HTTPError):
            _rows("custom_objects")


class TestDefinitions:
    @parameterized.expand(
        [
            ("custom_objects_listed", 200, ["account", "contact", "project"]),
            ("custom_objects_unavailable", 404, ["account", "contact"]),
        ]
    )
    @responses.activate
    def test_flattens_each_readable_type(self, _name: str, objects_status: int, expected_owners: list[str]) -> None:
        responses.get(
            f"{BASE}/v1/objects",
            json={"data": [{"objectType": "project", "label": "Project"}]},
            status=objects_status,
        )
        readable = {"account", "contact"}
        for resource in STANDARD_DEFINITION_RESOURCES:
            if resource.object_type in readable:
                responses.get(
                    f"{BASE}{resource.path}",
                    json={
                        "objectType": resource.object_type,
                        "fieldDefinitions": {"$name": {"label": "Name", "valueType": "TEXT"}},
                        "relationshipDefinitions": {
                            "$owner": {"label": "Owner", "cardinality": "HAS_ONE", "objectType": "member"}
                        },
                    },
                )
            else:
                responses.get(f"{BASE}{resource.path}", json={"error": "missing scope"}, status=403)
        responses.get(
            f"{BASE}/v1/objects/project/definitions",
            json={
                "objectType": "project",
                "fieldDefinitions": {"budget": {"label": "Budget", "valueType": "CURRENCY"}},
                "relationshipDefinitions": {},
            },
        )

        field_rows = _rows("field_definitions")
        relationship_rows = _rows("relationship_definitions")

        assert [row["ownerObjectType"] for row in field_rows] == expected_owners
        assert {(row["ownerObjectType"], row["key"]) for row in field_rows} >= {("account", "$name")}
        assert relationship_rows == [
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
                _make_http_response({"active": True, "scopes": ["accounts:read"], "tokenType": "api_key"}),
                (True, ["accounts:read"], None),
            ),
            (
                "active_key_without_scope_list",
                _make_http_response({"active": True}),
                (True, None, None),
            ),
            (
                "inactive_key",
                _make_http_response({"active": False, "scopes": []}),
                (False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."),
            ),
            (
                "unauthorized",
                _make_http_response({"error": "unauthorized"}, status_code=401),
                (False, None, "Invalid Lightfield API key. Check the key and try again."),
            ),
            (
                "server_error",
                _make_http_response({"error": "oops"}, status_code=503),
                (False, None, "Lightfield returned an unexpected status (503) while validating the key."),
            ),
        ]
    )
    @patch("sources.lightfield.lightfield.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        response: Response,
        expected: tuple[bool, list[str] | None, str | None],
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = response

        assert check_token("sk_lf_test", "2026-03-01") == expected
