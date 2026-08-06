from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.hogql.errors import QueryError


class TestUtmAuditApi(APIBaseTest):
    def test_utm_audit_returns_400_with_message_on_hogql_error(self) -> None:
        with patch(
            "products.marketing_analytics.backend.api.run_utm_audit",
            side_effect=QueryError("Field not found: campaign_id"),
        ):
            response = self.client.get(f"/api/environments/{self.team.pk}/marketing_analytics/utm_audit")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Field not found: campaign_id"

    def test_utm_audit_returns_500_on_unexpected_error(self) -> None:
        with patch(
            "products.marketing_analytics.backend.api.run_utm_audit",
            side_effect=ValueError("boom"),
        ):
            response = self.client.get(f"/api/environments/{self.team.pk}/marketing_analytics/utm_audit")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
