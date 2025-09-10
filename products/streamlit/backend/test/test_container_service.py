from unittest.mock import patch, MagicMock
import docker

from posthog.test.base import BaseTest
from products.streamlit.backend.container_service import ContainerService


class ContainerServiceTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.container_service = ContainerService()

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_deploy_default_app(self, mock_docker_from_env):
        """Test deploying a default Streamlit app"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "container-123"
        mock_client.containers.run.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        # Create a new container service instance to use the mocked client
        service = ContainerService()
        service.client = mock_client
        
        app_id = "test-app-id"
        app_name = "Test App"
        
        container_id = service.deploy_default_app(app_id, app_name)
        
        self.assertEqual(container_id, "container-123")
        
        # Verify the container was created with correct parameters
        mock_client.containers.run.assert_called_once()
        call_args = mock_client.containers.run.call_args
        
        self.assertEqual(call_args[1]["image"], "python:3.11-slim")
        self.assertEqual(call_args[1]["name"], f"streamlit-app-{app_id}")
        self.assertEqual(call_args[1]["detach"], True)
        self.assertIn("POSTHOG_APP_ID", call_args[1]["environment"])
        self.assertEqual(call_args[1]["environment"]["POSTHOG_APP_ID"], app_id)
        self.assertEqual(call_args[1]["environment"]["POSTHOG_APP_NAME"], app_name)

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_stop_and_remove_container(self, mock_docker_from_env):
        """Test stopping and removing a container"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        service.stop_and_remove_container(container_id)
        
        # Verify the container was stopped and removed
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_stop_and_remove_container_not_found(self, mock_docker_from_env):
        """Test handling container not found error"""
        # Mock Docker client to raise NotFound exception
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "nonexistent-container"
        
        # Should not raise an exception
        service.stop_and_remove_container(container_id)
        
        # Verify the container was queried
        mock_client.containers.get.assert_called_once_with(container_id)

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_get_container_status(self, mock_docker_from_env):
        """Test getting container status"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        status = service.get_container_status(container_id)
        
        self.assertEqual(status, "running")
        mock_client.containers.get.assert_called_once_with(container_id)

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_get_container_status_not_found(self, mock_docker_from_env):
        """Test getting status for non-existent container"""
        # Mock Docker client to raise NotFound exception
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "nonexistent-container"
        status = service.get_container_status(container_id)
        
        self.assertIsNone(status)

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_restart_container(self, mock_docker_from_env):
        """Test restarting a container"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        service.restart_container(container_id)
        
        # Verify the container was restarted
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_container.restart.assert_called_once()
