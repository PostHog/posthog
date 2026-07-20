from typing import Any

from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient


def test_data_map_reshapes_rows_declaratively() -> None:
    config: dict[str, Any] = {
        "client": {"base_url": "https://api.example.com"},
        "resources": [
            {
                "name": "things",
                "endpoint": {"path": "/things"},
                # flatten a JSON:API-style ``attributes`` block into the row root
                "data_map": lambda row: {"id": row["id"], **row.get("attributes", {})},
            }
        ],
    }
    raw_page = [{"id": 1, "attributes": {"name": "x", "active": True}}]
    with patch.object(RESTClient, "paginate", return_value=iter([raw_page])):
        resource = rest_api_resource(config, team_id=1, job_id="j", db_incremental_field_last_value=None)
        rows = [row for page in resource for row in page]

    assert rows == [{"id": 1, "name": "x", "active": True}]
