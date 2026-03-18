from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status


def _minimal_query_data() -> dict:
    return {
        "dateRange": {"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-01-02T00:00:00Z"},
        "filterGroup": {"type": "AND", "values": []},
        "severityLevels": [],
        "serviceNames": [],
    }


class TestLogsExportEndpoint(APIBaseTest):
    @patch("products.logs.backend.api.export_asset")
    def test_export_creates_asset_with_correct_context(self, mock_export_asset):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/logs/export/",
            data={
                "query": _minimal_query_data(),
                "columns": ["timestamp", "body"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["export_format"] == "text/csv"

        from posthog.models.exported_asset import ExportedAsset

        asset = ExportedAsset.objects.get(id=response.json()["id"])
        assert asset.export_context is not None
        assert asset.export_context["source"]["kind"] == "LogsQuery"
        assert asset.export_context["columns"] == ["timestamp", "body"]
        mock_export_asset.delay.assert_called_once_with(asset.id)

    @parameterized.expand(
        [
            (
                ["my-service"],
                {"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-01-07T00:00:00Z"},
                "logs-my-service-2024-01-01-to-2024-01-07",
            ),
            (
                ["service-a", "service-b", "service-c"],
                {"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-01-07T00:00:00Z"},
                "logs-3-services-2024-01-01-to-2024-01-07",
            ),
            (
                [],
                {"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-01-07T00:00:00Z"},
                "logs-all-services-2024-01-01-to-2024-01-07",
            ),
            (
                ["my-service"],
                {"date_from": "2024-01-01T00:00:00Z"},
                "logs-my-service-from-2024-01-01",
            ),
        ]
    )
    @patch("products.logs.backend.api.export_asset")
    def test_export_filename_includes_service_and_date_range(
        self, service_names, date_range, expected_filename, mock_export_asset
    ):
        query_data = _minimal_query_data()
        query_data["serviceNames"] = service_names
        query_data["dateRange"] = date_range

        response = self.client.post(
            f"/api/projects/{self.team.pk}/logs/export/",
            data={"query": query_data},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

        from posthog.models.exported_asset import ExportedAsset

        asset = ExportedAsset.objects.get(id=response.json()["id"])
        assert asset.export_context is not None
        assert asset.export_context["filename"] == expected_filename

    @patch("products.logs.backend.api.export_asset")
    def test_export_creates_asset_successfully(self, mock_export_asset):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/logs/export/",
            data={"query": _minimal_query_data()},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_export_rejects_missing_query(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/logs/export/",
            data={"format": "csv"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
