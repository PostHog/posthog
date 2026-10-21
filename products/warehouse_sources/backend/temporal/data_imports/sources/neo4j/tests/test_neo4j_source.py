import json
from typing import Any

import pytest
from unittest.mock import patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.neo4j import Neo4jSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.neo4j.source import Neo4jSource


@pytest.mark.parametrize("names", [None, [], ["node_Person"], ["rel_KNOWS"], ["missing"]])
def test_live_schema_discovery_and_filtering(names: list[str] | None) -> None:
    payloads: list[dict[str, Any]] = [
        {"data": {"fields": ["label"], "values": [["Person"], ["Person_Record"], ["two words"]]}},
        {"data": {"fields": ["relationshipType"], "values": [["KNOWS"], ["Person"]]}},
    ]
    responses = []
    for payload in payloads:
        response = Response()
        response.status_code = 202
        response._content = json.dumps(payload).encode()
        responses.append(response)
    config = Neo4jSourceConfig(
        host="https://graph.example.com", database="neo4j", username="reader", password="test-password"
    )
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid",
            return_value=(True, None),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport.TrackedHTTPAdapter.send",
            side_effect=responses,
        ) as send,
    ):
        schemas = Neo4jSource().get_schemas(config, 1, names=names)
    expected = ["node_Person", "node_Person_Record", "node_two words", "rel_KNOWS", "rel_Person"]
    assert [schema.name for schema in schemas] == [name for name in expected if names is None or name in names]
    assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
    statements = [json.loads(call.args[0].body)["statement"] for call in send.call_args_list]
    assert statements == [
        "CALL db.labels() YIELD label RETURN label ORDER BY label",
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType",
    ]
