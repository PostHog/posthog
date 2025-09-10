from django.test import TestCase
from posthog.models import Team, User
from posthog.test.base import BaseTest

from products.streamlit.backend.models import StreamlitApp


class StreamlitAppModelTest(BaseTest):
    def test_create_streamlit_app(self):
        """Test creating a Streamlit app"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            description="A test Streamlit app",
            created_by=self.user,
        )
        
        self.assertEqual(app.name, "Test App")
        self.assertEqual(app.description, "A test Streamlit app")
        self.assertEqual(app.team, self.team)
        self.assertEqual(app.created_by, self.user)
        self.assertEqual(app.container_status, StreamlitApp.ContainerStatus.PENDING)
        self.assertIsNotNone(app.id)
        self.assertIsNotNone(app.created_at)
        self.assertIsNotNone(app.updated_at)

    def test_streamlit_app_str_representation(self):
        """Test string representation of StreamlitApp"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            created_by=self.user,
        )
        
        self.assertEqual(str(app), "Test App")

    def test_container_status_choices(self):
        """Test container status choices"""
        app = StreamlitApp.objects.create(
            team=self.team,
            name="Test App",
            created_by=self.user,
        )
        
        # Test default status
        self.assertEqual(app.container_status, StreamlitApp.ContainerStatus.PENDING)
        
        # Test updating status
        app.container_status = StreamlitApp.ContainerStatus.RUNNING
        app.save()
        
        app.refresh_from_db()
        self.assertEqual(app.container_status, StreamlitApp.ContainerStatus.RUNNING)

    def test_team_isolation(self):
        """Test that apps are isolated by team"""
        # Create another team and user
        other_team = Team.objects.create(
            organization=self.organization,
            name="Other Team",
        )
        other_user = User.objects.create_user(
            email="other@example.com",
            first_name="Other User",
            password="testpass123",
        )
        
        # Create apps for different teams
        app1 = StreamlitApp.objects.create(
            team=self.team,
            name="App 1",
            created_by=self.user,
        )
        app2 = StreamlitApp.objects.create(
            team=other_team,
            name="App 2",
            created_by=other_user,
        )
        
        # Test that apps are isolated
        self.assertNotEqual(app1.team, app2.team)
        self.assertEqual(StreamlitApp.objects.filter(team=self.team).count(), 1)
        self.assertEqual(StreamlitApp.objects.filter(team=other_team).count(), 1)
