from unittest.mock import patch, MagicMock
import docker
import requests

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

    @patch('products.streamlit.backend.container_service.requests.get')
    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_check_container_health_healthy(self, mock_docker_from_env, mock_requests_get):
        """Test health check for healthy container"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        internal_url = "http://localhost:8501"
        
        is_healthy = service.check_container_health(container_id, internal_url)
        
        self.assertTrue(is_healthy)
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_requests_get.assert_called_once_with(f"{internal_url}/_stcore/health", timeout=10)

    @patch('products.streamlit.backend.container_service.requests.get')
    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_check_container_health_not_running(self, mock_docker_from_env, mock_requests_get):
        """Test health check for non-running container"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "stopped"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        internal_url = "http://localhost:8501"
        
        is_healthy = service.check_container_health(container_id, internal_url)
        
        self.assertFalse(is_healthy)
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_requests_get.assert_not_called()

    @patch('products.streamlit.backend.container_service.requests.get')
    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_check_container_health_http_error(self, mock_docker_from_env, mock_requests_get):
        """Test health check for container with HTTP error"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        # Mock HTTP error response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_requests_get.return_value = mock_response
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        internal_url = "http://localhost:8501"
        
        is_healthy = service.check_container_health(container_id, internal_url)
        
        self.assertFalse(is_healthy)
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_requests_get.assert_called_once_with(f"{internal_url}/_stcore/health", timeout=10)

    @patch('products.streamlit.backend.container_service.requests.get')
    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_check_container_health_request_exception(self, mock_docker_from_env, mock_requests_get):
        """Test health check for container with request exception"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        # Mock request exception
        mock_requests_get.side_effect = requests.exceptions.RequestException("Connection failed")
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        internal_url = "http://localhost:8501"
        
        is_healthy = service.check_container_health(container_id, internal_url)
        
        self.assertFalse(is_healthy)
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_requests_get.assert_called_once_with(f"{internal_url}/_stcore/health", timeout=10)

    @patch('products.streamlit.backend.container_service.docker.from_env')
    def test_get_container_logs(self, mock_docker_from_env):
        """Test getting container logs"""
        # Mock Docker client and container
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"Container log output"
        mock_client.containers.get.return_value = mock_container
        mock_docker_from_env.return_value = mock_client
        
        service = ContainerService()
        service.client = mock_client
        
        container_id = "container-123"
        logs = service.get_container_logs(container_id)
        
        self.assertEqual(logs, "Container log output")
        mock_client.containers.get.assert_called_once_with(container_id)
        mock_container.logs.assert_called_once_with(tail=100, timestamps=True)
