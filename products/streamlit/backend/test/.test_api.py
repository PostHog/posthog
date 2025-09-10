from unittest.mock import patch, MagicMock
from rest_framework import status
from rest_framework.test import APIClient

from posthog.test.base import BaseTest
from products.streamlit.backend.models import StreamlitApp


class StreamlitAppAPITest(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.user)

    def test_create_streamlit_app(self):
        """Test creating a Streamlit app via API"""
        with patch('products.streamlit.backend.api.ContainerService') as mock_service:
            mock_container_service = MagicMock()
            mock_container_service.deploy_default_app.return_value = "container-123"
            mock_service.return_value = mock_container_service
            
            data = {
                "name": "Test App",
                "description": "A test Streamlit app",
            }
            
            response = self.client.post(
                f"/api/projects/{self.team.project_id}/streamlit_apps/",
                data,
                format="json",
            )
            
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["name"], "Test App")
            self.assertEqual(response.data["description"], "A test Streamlit app")
            self.assertEqual(response.data["container_id"], "container-123")
            self.assertEqual(response.data["container_status"], "running")
            self.assertEqual(response.data["created_by"]["id"], self.user.id)
            
            # Verify the app was created in the database
            app = StreamlitApp.objects.get(id=response.data["id"])
            self.assertEqual(app.name, "Test App")
            self.assertEqual(app.team, self.team)
            self.assertEqual(app.created_by, self.user)

    def test_list_streamlit_apps(self):
        """Test listing Streamlit apps"""
        # Create some test apps
        app1 = StreamlitApp.objects.create(
            team=self.team,
            name="App 1",
            created_by=self.user,
        )
        app2 = StreamlitApp.objects.create(
            team=self.team,
            name="App 2",
            created_by=self.user,
        )
        
        response = self.client.get(f"/api/projects/{self.team.project_id}/streamlit_apps/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        
        app_names = [app["name"] for app in response.data["results"]]
        self.assertIn("App 1", app_names)
        self.assertIn("App 2", app_names)

    def test_get_streamlit_app(self):
        """Test retrieving a specific Streamlit app"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            description="A test app",
            created_by=self.user,
        )
        
        response = self.client.get(f"/api/projects/{self.team.project_id}/streamlit_apps/{app.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test App")
        self.assertEqual(response.data["description"], "A test app")
        self.assertEqual(response.data["id"], str(app.id))

    def test_update_streamlit_app(self):
        """Test updating a Streamlit app"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Original Name",
            description="Original description",
            created_by=self.user,
        )
        
        data = {
            "name": "Updated Name",
            "description": "Updated description",
        }
        
        response = self.client.patch(
            f"/api/projects/{self.team.project_id}/streamlit_apps/{app.id}/",
            data,
            format="json",
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Name")
        self.assertEqual(response.data["description"], "Updated description")
        
        # Verify the app was updated in the database
        app.refresh_from_db()
        self.assertEqual(app.name, "Updated Name")
        self.assertEqual(app.description, "Updated description")

    def test_delete_streamlit_app(self):
        """Test deleting a Streamlit app"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            created_by=self.user,
            container_id="container-123",
        )
        
        with patch('products.streamlit.backend.api.ContainerService') as mock_service:
            mock_container_service = MagicMock()
            mock_service.return_value = mock_container_service
            
            response = self.client.delete(f"/api/projects/{self.team.project_id}/streamlit_apps/{app.id}/")
            
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            
            # Verify the app was deleted from the database
            self.assertFalse(StreamlitApp.objects.filter(id=app.id).exists())
            
            # Verify container service was called to stop and remove container
            mock_container_service.stop_and_remove_container.assert_called_once_with("container-123")

    def test_team_isolation(self):
        """Test that users can only see apps for their team"""
        # Create another team and user
        other_team = self.organization.teams.create(name="Other Team")
        other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.organization.members.create(
            user=other_user,
            level=1,
        )
        
        # Create apps for different teams
        app1 = StreamlitApp.objects.create(
            team=self.team,
            name="My App",
            created_by=self.user,
        )
        app2 = StreamlitApp.objects.create(
            team=other_team,
            name="Other App",
            created_by=other_user,
        )
        
        # Test that user can only see their team's apps
        response = self.client.get(f"/api/projects/{self.team.project_id}/streamlit_apps/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "My App")
