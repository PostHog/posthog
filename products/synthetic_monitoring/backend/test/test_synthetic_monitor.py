from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.synthetic_monitoring.backend.models import SyntheticMonitor


class TestSyntheticMonitorAPI(APIBaseTest):
    def test_create_monitor(self):
        """Test creating a basic synthetic monitor"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "API Health Check",
                "url": "https://api.example.com/health",
                "frequency_minutes": 5,
                "regions": ["us-east-1"],
                "method": "GET",
                "expected_status_code": 200,
                "timeout_seconds": 30,
                "enabled": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "API Health Check"
        assert data["url"] == "https://api.example.com/health"
        assert data["frequency_minutes"] == 5
        assert data["regions"] == ["us-east-1"]
        assert data["method"] == "GET"
        assert data["expected_status_code"] == 200
        assert data["timeout_seconds"] == 30
        assert data["enabled"] is True
        assert data["created_by"]["id"] == self.user.id
        assert SyntheticMonitor.objects.filter(id=data["id"]).exists()

    def test_create_monitor_with_custom_headers(self):
        """Test creating a monitor with custom headers"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Authenticated API Check",
                "url": "https://api.example.com/protected",
                "frequency_minutes": 15,
                "regions": ["us-east-1", "eu-west-1"],
                "method": "GET",
                "headers": {"Authorization": "Bearer token123"},
                "expected_status_code": 200,
                "timeout_seconds": 60,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["headers"] == {"Authorization": "Bearer token123"}
        assert data["regions"] == ["us-east-1", "eu-west-1"]

    def test_create_monitor_with_post_body(self):
        """Test creating a monitor with POST method and body"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "POST API Check",
                "url": "https://api.example.com/webhook",
                "frequency_minutes": 30,
                "regions": ["us-east-1"],
                "method": "POST",
                "body": '{"test": "data"}',
                "expected_status_code": 201,
                "timeout_seconds": 45,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["method"] == "POST"
        assert data["body"] == '{"test": "data"}'
        assert data["expected_status_code"] == 201

    def test_create_monitor_invalid_url(self):
        """Test that invalid URLs are rejected"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Invalid URL",
                "url": "not-a-url",
                "frequency_minutes": 5,
                "regions": ["us-east-1"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Enter a valid URL" in str(response.json())

    def test_create_monitor_invalid_method(self):
        """Test that invalid HTTP methods are rejected"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Invalid Method",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": ["us-east-1"],
                "method": "INVALID",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is not a valid choice" in str(response.json())

    def test_create_monitor_invalid_regions(self):
        """Test that invalid regions are rejected"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Invalid Region",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": ["invalid-region"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid regions" in str(response.json())

    def test_create_monitor_empty_regions(self):
        """Test that empty regions list is not allowed"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Empty Regions",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": [],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "This field cannot be blank" in str(response.json())

    def test_list_monitors(self):
        """Test listing monitors"""
        # Create a few monitors
        monitor1 = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Monitor 1",
            url="https://api.example.com/1",
            frequency_minutes=5,
            regions=["us-east-1"],
            created_by=self.user,
        )
        monitor2 = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Monitor 2",
            url="https://api.example.com/2",
            frequency_minutes=15,
            regions=["eu-west-1"],
            enabled=False,
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 2
        monitor_ids = [m["id"] for m in data["results"]]
        assert str(monitor1.id) in monitor_ids
        assert str(monitor2.id) in monitor_ids

    def test_list_monitors_filter_by_enabled(self):
        """Test filtering monitors by enabled status"""
        SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Enabled Monitor",
            url="https://api.example.com/enabled",
            frequency_minutes=5,
            regions=["us-east-1"],
            enabled=True,
            created_by=self.user,
        )
        SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Disabled Monitor",
            url="https://api.example.com/disabled",
            frequency_minutes=5,
            regions=["us-east-1"],
            enabled=False,
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/?enabled=true")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "Enabled Monitor"
        assert data["results"][0]["enabled"] is True

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/?enabled=false")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "Disabled Monitor"
        assert data["results"][0]["enabled"] is False

    def test_list_monitors_search(self):
        """Test searching monitors by name or URL"""
        SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="API Health Check",
            url="https://api.example.com/health",
            frequency_minutes=5,
            regions=["us-east-1"],
            created_by=self.user,
        )
        SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Database Check",
            url="https://db.example.com/status",
            frequency_minutes=15,
            regions=["us-east-1"],
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/?search=API")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "API Health Check"

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/?search=health")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 1
        assert "health" in data["results"][0]["url"].lower()

    def test_get_monitor(self):
        """Test retrieving a single monitor"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Test Monitor",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1", "eu-west-1"],
            method="POST",
            headers={"Authorization": "Bearer token"},
            body='{"key": "value"}',
            expected_status_code=201,
            timeout_seconds=45,
            enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(monitor.id)
        assert data["name"] == "Test Monitor"
        assert data["regions"] == ["us-east-1", "eu-west-1"]
        assert data["method"] == "POST"
        assert data["headers"] == {"Authorization": "Bearer token"}
        assert data["body"] == '{"key": "value"}'
        assert data["expected_status_code"] == 201
        assert data["timeout_seconds"] == 45
        assert data["enabled"] is True

    def test_update_monitor(self):
        """Test updating a monitor"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Original Name",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            enabled=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={
                "name": "Updated Name",
                "frequency_minutes": 15,
                "regions": ["us-east-1", "eu-west-1"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["frequency_minutes"] == 15
        assert data["regions"] == ["us-east-1", "eu-west-1"]

        monitor.refresh_from_db()
        assert monitor.name == "Updated Name"
        assert monitor.frequency_minutes == 15
        assert monitor.regions == ["us-east-1", "eu-west-1"]

    def test_update_monitor_enable_disable(self):
        """Test enabling and disabling a monitor"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Test Monitor",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            enabled=True,
            created_by=self.user,
        )

        # Disable
        response = self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] is False

        monitor.refresh_from_db()
        assert monitor.enabled is False

        # Enable
        response = self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"enabled": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] is True

        monitor.refresh_from_db()
        assert monitor.enabled is True

    @patch("products.synthetic_monitoring.backend.api.report_user_action")
    def test_delete_monitor(self, mock_report):
        """Test deleting a monitor"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="To Delete",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            created_by=self.user,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SyntheticMonitor.objects.filter(id=monitor.id).exists()

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][1] == "synthetic monitor deleted"
        assert call_args[0][2]["monitor_id"] == str(monitor.id)
        assert call_args[0][2]["monitor_name"] == "To Delete"

    def test_create_monitor_team_isolation(self):
        """Test that monitors are isolated by team"""
        # Create monitor for team 1
        monitor1 = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Team 1 Monitor",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            created_by=self.user,
        )

        # Create another team
        team2 = self.team.organization.teams.create(name="Team 2")

        # Try to access monitor from team 1 using team 2's context
        response = self.client.get(f"/api/projects/{team2.id}/synthetic_monitors/{monitor1.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_monitor_all_valid_regions(self):
        """Test creating monitors with all valid regions"""
        valid_regions = ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-northeast-1"]

        for region in valid_regions:
            response = self.client.post(
                f"/api/projects/{self.team.id}/synthetic_monitors/",
                data={
                    "name": f"Monitor {region}",
                    "url": "https://api.example.com",
                    "frequency_minutes": 5,
                    "regions": [region],
                },
                format="json",
            )
            assert response.status_code == status.HTTP_201_CREATED, f"Failed for region {region}: {response.json()}"
            assert response.json()["regions"] == [region]

    def test_create_monitor_multiple_regions(self):
        """Test creating a monitor with multiple regions"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Multi-Region Monitor",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": ["us-east-1", "us-west-2", "eu-west-1"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert len(data["regions"]) == 3
        assert "us-east-1" in data["regions"]
        assert "us-west-2" in data["regions"]
        assert "eu-west-1" in data["regions"]

    def test_create_monitor_all_frequency_options(self):
        """Test creating monitors with all valid frequency options"""
        frequencies = [1, 5, 15, 30, 60]

        for freq in frequencies:
            response = self.client.post(
                f"/api/projects/{self.team.id}/synthetic_monitors/",
                data={
                    "name": f"Monitor {freq}min",
                    "url": "https://api.example.com",
                    "frequency_minutes": freq,
                    "regions": ["us-east-1"],
                },
                format="json",
            )
            assert response.status_code == status.HTTP_201_CREATED, f"Failed for frequency {freq}: {response.json()}"
            assert response.json()["frequency_minutes"] == freq

    def test_create_monitor_all_http_methods(self):
        """Test creating monitors with all valid HTTP methods"""
        methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]

        for method in methods:
            response = self.client.post(
                f"/api/projects/{self.team.id}/synthetic_monitors/",
                data={
                    "name": f"Monitor {method}",
                    "url": "https://api.example.com",
                    "frequency_minutes": 5,
                    "regions": ["us-east-1"],
                    "method": method,
                },
                format="json",
            )
            assert response.status_code == status.HTTP_201_CREATED, f"Failed for method {method}: {response.json()}"
            assert response.json()["method"] == method

    def test_create_monitor_default_values(self):
        """Test that default values are set correctly"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Default Values Test",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": ["us-east-1"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["method"] == "GET"
        assert data["expected_status_code"] == 200
        assert data["timeout_seconds"] == 30
        assert data["enabled"] is True

    @patch("products.synthetic_monitoring.backend.api.report_user_action")
    def test_create_monitor_reports_user_action(self, mock_report):
        """Test that creating a monitor reports user action"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/synthetic_monitors/",
            data={
                "name": "Test Monitor",
                "url": "https://api.example.com",
                "frequency_minutes": 5,
                "regions": ["us-east-1"],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][1] == "synthetic monitor created"
        assert "monitor_id" in call_args[0][2]
        assert call_args[0][2]["frequency_minutes"] == 5

    @patch("products.synthetic_monitoring.backend.api.report_user_action")
    def test_update_monitor_reports_user_action(self, mock_report):
        """Test that updating a monitor reports user action"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Original",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            enabled=True,
            created_by=self.user,
        )

        # Update enabled status
        self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"enabled": False},
            format="json",
        )

        mock_report.assert_called()
        call_args = mock_report.call_args
        assert call_args[0][1] == "synthetic monitor paused"
        assert call_args[0][2]["monitor_id"] == str(monitor.id)

        # Re-enable
        self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"enabled": True},
            format="json",
        )

        call_args = mock_report.call_args
        assert call_args[0][1] == "synthetic monitor resumed"

    def test_update_monitor_invalid_data(self):
        """Test that invalid data in update is rejected"""
        monitor = SyntheticMonitor.objects.create(
            team_id=self.team.id,
            name="Test",
            url="https://api.example.com",
            frequency_minutes=5,
            regions=["us-east-1"],
            created_by=self.user,
        )

        # Invalid URL
        response = self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"url": "not-a-url"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Invalid region
        response = self.client.patch(
            f"/api/projects/{self.team.id}/synthetic_monitors/{monitor.id}/",
            data={"regions": ["invalid-region"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
