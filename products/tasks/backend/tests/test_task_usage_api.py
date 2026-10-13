import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from products.tasks.backend.logic.services.task_usage import (
    TASK_USAGE_INTERNAL_PATH,
    TASK_USAGE_SIGNATURE_HEADER,
    TASK_USAGE_TIMESTAMP_HEADER,
    sign_task_usage_request,
)
from products.tasks.backend.presentation.views.task_usage_api import InternalTaskUsageViewSet

CROSS_REGION_SECRET = "test-cross-region-secret"


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


class TestInternalTaskUsageAuthentication(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        overrides = override_settings(PERSONAL_SPEND_CROSS_REGION_SECRET=CROSS_REGION_SECRET)
        overrides.enable()
        self.addCleanup(overrides.disable)
        # No session, so the endpoint stands on the signature alone.
        self.client.logout()
        token_cost = patch(
            "products.tasks.backend.presentation.views.task_usage_api.get_local_task_token_cost",
            return_value=Decimal("1.25"),
        )
        self.get_token_cost = token_cost.start()
        self.addCleanup(token_cost.stop)
        self.body = json.dumps(
            {
                "team_id": self.team.id,
                "task_id": str(UUID("00000000-0000-0000-0000-000000000001")),
                "task_created_at": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
            }
        ).encode()

    def _post(self, headers: dict[str, str]):
        return self.client.post(
            TASK_USAGE_INTERNAL_PATH,
            data=self.body,
            content_type="application/json",
            headers=headers,
        )

    def _signed_headers(self, *, secret: str = CROSS_REGION_SECRET, timestamp: int | None = None) -> dict[str, str]:
        signed = sign_task_usage_request(self.body, secret, timestamp=timestamp)
        return {
            TASK_USAGE_SIGNATURE_HEADER: signed.signature,
            TASK_USAGE_TIMESTAMP_HEADER: signed.timestamp,
        }

    @parameterized.expand(
        [
            ("wrong_secret", "a-different-secret", 0, None),
            ("stale_timestamp", CROSS_REGION_SECRET, -3600, None),
            # WSGI decodes header bytes as latin-1, so a junk byte reaches the adapter as a
            # str holding a non-ASCII code point. That shape used to raise out of
            # compare_digest and turn an unauthenticated request into a 500.
            ("non_ascii_signature", CROSS_REGION_SECRET, 0, "sha256=\xe9"),
        ]
    )
    def test_rejects_a_request_the_signature_does_not_vouch_for(
        self, _name: str, secret: str, timestamp_offset: int, signature_override: str | None
    ) -> None:
        headers = self._signed_headers(secret=secret, timestamp=int(time.time()) + timestamp_offset)
        if signature_override is not None:
            headers[TASK_USAGE_SIGNATURE_HEADER] = signature_override

        response = self._post(headers)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        self.get_token_cost.assert_not_called()

    def test_signed_request_authenticates_and_returns_the_token_cost(self) -> None:
        response = self._post(self._signed_headers())

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"token_cost_usd": 1.25}
        self.get_token_cost.assert_called_once_with(
            team_id=self.team.id,
            task_id=UUID("00000000-0000-0000-0000-000000000001"),
            task_created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
