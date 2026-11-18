from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.constants import CIO_API_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.source import CustomerIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.customerio import (
    CustomerIOSourceConfig,
)

# Synthetic payloads in the shape of the App API list responses.
PAYLOADS: dict[str, dict[str, Any]] = {
    "broadcasts": {
        "broadcasts": [
            {
                "id": 1,
                "deduplicate_id": "1:1700000000",
                "name": "Test broadcast",
                "type": "api_triggered",
                "created": 1700000000,
                "updated": 1700000000,
                "active": True,
                "state": "draft",
                "actions": [],
                "first_started": None,
                "tags": [],
                "scheduled_start": None,
                "scheduled_start_should_backfill": False,
                "scheduled_stop": None,
                "scheduled_stop_should_sunset": False,
            }
        ]
    },
    "campaigns": {
        "campaigns": [
            {
                "id": 100,
                "deduplicate_id": "100:1700000000",
                "name": "Welcome series",
                "type": "triggered",
                "created": 1700000000,
                "updated": 1700000000,
                "active": True,
                "state": "running",
                "actions": [200],
                "first_started": 1700000000,
                "tags": ["onboarding"],
                "scheduled_start": None,
                "scheduled_start_should_backfill": False,
                "scheduled_stop": None,
                "scheduled_stop_should_sunset": False,
                "event_name": "signed_up",
                "event_type": "event",
            }
        ]
    },
    "collections": {
        "collections": [
            {
                "id": 1,
                "name": "Products",
                "rows": 0,
                "bytes": 0,
                "created_at": 1700000000,
                "updated_at": 1700000000,
                "schema": {"fields": []},
            }
        ]
    },
    "newsletters": {
        "newsletters": [
            {
                "id": 1,
                "deduplicate_id": "1:1700000000",
                "content_ids": [10],
                "name": "Monthly newsletter",
                "sent_at": 1700000000,
                "created": 1700000000,
                "updated": 1700000000,
                "type": "newsletter",
                "tags": [],
                "recipient_segment_ids": [50],
            }
        ]
    },
    "object_types": {
        "types": [
            {
                "id": "1",
                "name": "Account",
                "enabled": True,
                "icon": "company",
                "singular_name": "Account",
                "slug": "accounts",
                "singular_slug": "account",
            }
        ]
    },
    "segments": {
        "segments": [
            {
                "id": 1,
                "deduplicate_id": "1:1700000000",
                "name": "Active users",
                "description": "Users active in the last 30 days",
                "state": "finished",
                "progress": None,
                "type": "dynamic",
                "tags": [],
                "conditions": "true",
                "created_at": 1700000000,
                "updated_at": 1700000000,
            }
        ]
    },
    "sender_identities": {
        "sender_identities": [
            {
                "id": 1,
                "deduplicate_id": "1:1700000000",
                "name": "Marketing",
                "email": "marketing@example.com",
                "phone": None,
                "address": "1 Example Way",
                "template_type": "transactional",
                "auto_generated": False,
            }
        ]
    },
    "snippets": {
        "snippets": [
            {
                "name": "footer",
                "value": "<p>Unsubscribe</p>",
                "updated_at": 1700000000,
            }
        ]
    },
    "subscription_topics": {
        "topics": [
            {
                "id": 1,
                "identifier": "topic_1",
                "name": "Product updates",
                "description": "Updates about new features",
                "subscribed_by_default": True,
            }
        ]
    },
    "transactional": {
        "messages": [
            {
                "id": 1,
                "name": "Password reset",
                "description": "Password reset email",
                "send_to_unsubscribed": True,
                "link_tracking": True,
                "open_tracking": True,
                "hide_message_body": False,
                "queue_drafts": False,
                "trigger_name": None,
                "created_at": 1700000000,
                "updated_at": 1700000000,
            }
        ]
    },
}


@pytest.mark.parametrize("schema_name", list(CIO_API_ENDPOINTS))
def test_list_endpoint_rows_reach_the_pipeline_with_their_keys(schema_name: str) -> None:
    payload = PAYLOADS[schema_name]
    driver = SourceDriver(CustomerIOSource(), CustomerIOSourceConfig(app_api_key="test-key", region="us"))

    result = driver.run(schema_name, always(ScriptedResponse(json=payload)))

    assert result.raised is None
    assert result.response is not None
    assert result.rows == payload[CIO_API_ENDPOINTS[schema_name].response_key]
    # The pipeline deduplicates and partitions on these columns, so each row must carry them.
    for row in result.rows:
        assert set(result.response.primary_keys or []) <= row.keys()
        assert set(result.response.partition_keys or []) <= row.keys()
