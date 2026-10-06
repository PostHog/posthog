from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status


class TestBackfillStatusApi(APIBaseTest):
    @parameterized.expand([("flag on for this project", True), ("flag off", False)])
    def test_backfill_status_reports_the_project_group_flag(self, _name: str, flag_on: bool) -> None:
        def feature_enabled(key: str, distinct_id: str, groups: dict[str, str], **kwargs: object) -> bool:
            return key == "logs-backfill-enabled" and groups == {"project": str(self.team.id)} and flag_on

        with patch("posthog.ph_client.posthoganalytics.feature_enabled", side_effect=feature_enabled):
            response = self.client.get(f"/api/projects/{self.team.id}/logs/backfill_status")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"enabled": flag_on}
