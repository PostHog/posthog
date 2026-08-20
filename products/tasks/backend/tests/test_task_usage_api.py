from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from products.tasks.backend.presentation.views.task_usage_api import InternalTaskUsageViewSet


class TestInternalTaskUsageViewSet(SimpleTestCase):
    @patch(
        "products.tasks.backend.presentation.views.task_usage_api.get_local_task_token_cost",
        return_value=Decimal("1.25"),
    )
    def test_create_returns_token_cost(self, get_token_cost) -> None:
        request = Request(
            APIRequestFactory().post(
                "/",
                {
                    "team_id": 42,
                    "task_id": str(UUID("00000000-0000-0000-0000-000000000001")),
                    "task_created_at": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
                },
                format="json",
            ),
            parsers=[JSONParser()],
        )

        response = InternalTaskUsageViewSet().create(request)

        assert response.status_code == 200
        assert response.data == {"token_cost_usd": 1.25}
        get_token_cost.assert_called_once_with(
            team_id=42,
            task_id=UUID("00000000-0000-0000-0000-000000000001"),
            task_created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
