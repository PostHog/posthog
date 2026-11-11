from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

from django.test.client import Client as HttpClient

from posthog.llm.system_one import ChoiceAnswer, JsonValue, Question, SystemOneResult
from posthog.llm.system_one_client import GatewaySystemOneClient

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    rank_incremental_fields,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def create_external_data_source_ok(client: HttpClient, team_id: int) -> int:
    """Create an external data source and return the id."""
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    ):
        response = client.post(
            f"/api/environments/{team_id}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {
                            "name": "Charge",
                            "should_sync": False,
                            "sync_type": "full_refresh",
                            "sync_time_of_day": "01:00:00",
                        },
                    ],
                },
            },
            content_type="application/json",
        )
    payload: dict[str, Any] = response.json()

    assert response.status_code == 201
    return payload["id"]


def open_orders_schema(name: str = "orders") -> SourceSchema:
    """A table whose column names leave the cursor open: the rules pick `created_at`, the model `c1`."""
    return SourceSchema(
        name=name,
        supports_incremental=True,
        supports_append=True,
        incremental_fields=rank_incremental_fields(
            [
                {"label": n, "type": t, "field": n, "field_type": t, "nullable": False}
                for n, t in [
                    ("created_at", IncrementalFieldType.Timestamp),
                    ("fecha_actualizacion", IncrementalFieldType.Timestamp),
                ]
            ]
        ),
    )


@contextmanager
def fake_decision_model(choice: str = "c1") -> Iterator[list[Mapping[str, Question]]]:
    """Turn the model gates on and answer every question with `choice`. Yields the questions asked."""
    calls: list[Mapping[str, Question]] = []

    async def adecide(_self: Any, *, state: JsonValue, questions: Mapping[str, Question]) -> SystemOneResult:
        calls.append(questions)
        answer = ChoiceAnswer(choice=choice, confidence=0.9, probabilities={choice: 0.9})
        return SystemOneResult(model="jeeves-0.1", answers=dict.fromkeys(questions, answer), input_tokens=1)

    gateway = GatewaySystemOneClient(
        url="https://gateway.example.com/v1/systemone", api_key="test-key", headers={}, model="m", timeout=1.0
    )
    recommender = "products.warehouse_sources.backend.logic.incremental_field_model"
    with (
        patch(f"{recommender}.system_one_configured", return_value=True),
        patch(f"{recommender}.feature_enabled_or_false", return_value=True),
        patch(f"{recommender}.build_system_one_client", return_value=gateway),
        patch.object(GatewaySystemOneClient, "adecide", new=adecide),
    ):
        yield calls
