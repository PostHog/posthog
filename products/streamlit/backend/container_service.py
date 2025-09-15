import docker
import structlog
import socket
import os
import tempfile
import requests
from typing import Optional
from django.conf import settings
from django.core.files.base import ContentFile

logger = structlog.get_logger(__name__)


class ContainerService:
    """
    Service class to handle Docker operations for Streamlit apps.
    """
    
    def __init__(self):
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error("Failed to initialize Docker client", error=str(e))
            raise

    def _get_available_port(self) -> int:
        """Get an available port for the container"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    def deploy_custom_app(self, app_id: str, app_name: str, entrypoint_file, requirements_file=None) -> tuple[str, int, str, str]:
        """
        Deploy a custom Streamlit container with uploaded files.
        
        Args:
            app_id: Unique identifier for the app
            app_name: Display name for the app
            entrypoint_file: Django FileField with the main Python file
            requirements_file: Django FileField with requirements.txt (optional)
            
        Returns:
            Tuple of (container_id, port, internal_url, public_url)
        """
        try:
            # Get an available port
            port = self._get_available_port()
            
            # Create a temporary directory for the app files
            with tempfile.TemporaryDirectory() as temp_dir:
                # Write the entrypoint file
                entrypoint_path = os.path.join(temp_dir, "app.py")
                with open(entrypoint_path, 'w') as f:
                    # Reset file pointer and read as text
                    entrypoint_file.seek(0)
                    f.write(entrypoint_file.read().decode('utf-8'))
                
                # Write requirements file if provided
                requirements_path = os.path.join(temp_dir, "requirements.txt")
                if requirements_file:
                    with open(requirements_path, 'w') as f:
                        # Reset file pointer and read as text
                        requirements_file.seek(0)
                        f.write(requirements_file.read().decode('utf-8'))
                else:
                    # Default requirements
                    with open(requirements_path, 'w') as f:
                        f.write("streamlit\n")
                
                # Create Dockerfile
                dockerfile_content = f'''
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app file
COPY app.py .

# Expose port
EXPOSE 8501

# Run the app
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
'''
                
                dockerfile_path = os.path.join(temp_dir, "Dockerfile")
                with open(dockerfile_path, 'w') as f:
                    f.write(dockerfile_content)
                
                # Build the Docker image
                image_name = f"streamlit-app-{app_id}"
                logger.info("Building Docker image", app_id=app_id, image_name=image_name)
                
                image, build_logs = self.client.images.build(
                    path=temp_dir,
                    tag=image_name,
                    rm=True
                )
                
                # Create container with the built image
                container = self.client.containers.run(
                    image=image_name,
                    detach=True,
                    name=f"streamlit-app-{app_id}",
                    environment={
                        "POSTHOG_APP_ID": app_id,
                        "POSTHOG_APP_NAME": app_name,
                    },
                    ports={"8501/tcp": port},  # Map to our assigned port
                    remove=False,  # Don't auto-remove on stop
                )
            
            # Generate URLs
            internal_url = f"http://localhost:{port}"
            public_url = f"/streamlit/{app_id}/"
            
            logger.info("Successfully deployed Streamlit container", 
                       app_id=app_id, container_id=container.id, port=port)
            
            return container.id, port, internal_url, public_url
            
        except Exception as e:
            logger.error("Failed to deploy custom Streamlit container", 
                        app_id=app_id, error=str(e))
            raise

    def deploy_default_app(self, app_id: str, app_name: str) -> tuple[str, int, str, str]:
        """
        Deploy a default "Hello World" Streamlit container.
        
        Args:
            app_id: Unique identifier for the app
            app_name: Display name for the app
            
        Returns:
            Tuple of (container_id, port, internal_url, public_url)
        """
        try:
            # Get an available port
            port = self._get_available_port()
            
            # Create a simple Streamlit app script
            streamlit_script = f'''
import streamlit as st

st.title("{app_name}")
st.write("Hello from PostHog Streamlit App!")
st.write(f"App ID: {app_id}")

# Add some basic PostHog integration placeholder
st.sidebar.title("PostHog Integration")
st.sidebar.write("This app will have access to PostHog data in future stages.")

# Add some interactive elements
if st.button("Click me!"):
    st.balloons()
    
st.slider("Pick a number", 0, 100, 50)
'''
            
            # Create container with Streamlit
            container = self.client.containers.run(
                image="python:3.11-slim",
                command=[
                    "sh", "-c", 
                    "pip install streamlit && echo '" + streamlit_script.replace("'", "'\"'\"'") + "' > app.py && streamlit run app.py --server.port=8501 --server.address=0.0.0.0"
                ],
                detach=True,
                name=f"streamlit-app-{app_id}",
                environment={
                    "POSTHOG_APP_ID": app_id,
                    "POSTHOG_APP_NAME": app_name,
                },
                ports={"8501/tcp": port},  # Map to our assigned port
                remove=False,  # Don't auto-remove on stop
            )
            
            # Generate URLs
            internal_url = f"http://localhost:{port}"
            public_url = f"/streamlit/{app_id}/"
            
            logger.info("Successfully deployed default Streamlit container", 
                       app_id=app_id, container_id=container.id, port=port)
            
            return container.id, port, internal_url, public_url
            
        except Exception as e:
            logger.error("Failed to deploy default Streamlit container", 
                        app_id=app_id, error=str(e))
            raise

    def stop_and_remove_container(self, container_id: str) -> None:
        """
        Stop and remove a container.
        
        Args:
            container_id: ID of the container to stop and remove
        """
        try:
            container = self.client.containers.get(container_id)
            container.stop()
            container.remove()
            
            logger.info("Successfully stopped and removed container", 
                       container_id=container_id)
                       
        except docker.errors.NotFound:
            logger.warning("Container not found", container_id=container_id)
        except Exception as e:
            logger.error("Failed to stop and remove container", 
                        container_id=container_id, error=str(e))
            raise

    def get_container_status(self, container_id: str) -> Optional[str]:
        """
        Get the status of a container.
        
        Args:
            container_id: ID of the container
            
        Returns:
            Container status or None if not found
        """
        try:
            container = self.client.containers.get(container_id)
            return container.status
        except docker.errors.NotFound:
            return None
        except Exception as e:
            logger.error("Failed to get container status", 
                        container_id=container_id, error=str(e))
            return None

    def restart_container(self, container_id: str) -> None:
        """
        Restart a container.
        
        Args:
            container_id: ID of the container to restart
        """
        try:
            container = self.client.containers.get(container_id)
            container.restart()
            
            logger.info("Successfully restarted container", 
                       container_id=container_id)
                       
        except docker.errors.NotFound:
            logger.warning("Container not found", container_id=container_id)
        except Exception as e:
            logger.error("Failed to restart container", 
                        container_id=container_id, error=str(e))
            raise

    def check_container_health(self, container_id: str, internal_url: str) -> bool:
        """
        Check if a container is healthy by making a request to it.
        
        Args:
            container_id: ID of the container
            internal_url: Internal URL to check
            
        Returns:
            True if container is healthy, False otherwise
        """
        try:
            # First check if container is running
            container = self.client.containers.get(container_id)
            if container.status != 'running':
                logger.warning("Container is not running", 
                             container_id=container_id, status=container.status)
                return False
            
            # Make a health check request
            health_url = f"{internal_url}/_stcore/health"
            response = requests.get(health_url, timeout=10)
            
            if response.status_code == 200:
                logger.debug("Container health check passed", 
                           container_id=container_id)
                return True
            else:
                logger.warning("Container health check failed", 
                             container_id=container_id, status_code=response.status_code)
                return False
                
        except requests.exceptions.RequestException as e:
            logger.warning("Container health check request failed", 
                         container_id=container_id, error=str(e))
            return False
        except docker.errors.NotFound:
            logger.warning("Container not found during health check", 
                         container_id=container_id)
            return False
        except Exception as e:
            logger.error("Unexpected error during health check", 
                        container_id=container_id, error=str(e))
            return False

    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """
        Get container logs for debugging.
        
        Args:
            container_id: ID of the container
            tail: Number of lines to return from the end
            
        Returns:
            Container logs as string
        """
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
            return logs
        except docker.errors.NotFound:
            logger.warning("Container not found", container_id=container_id)
            return "Container not found"
        except Exception as e:
            logger.error("Failed to get container logs", 
                        container_id=container_id, error=str(e))
            return f"Error getting logs: {str(e)}"

    def can_recreate_container(self, app) -> bool:
        """
        Check if a container can be recreated based on app data.
        
        Args:
            app: StreamlitApp instance
            
        Returns:
            True if container can be recreated, False otherwise
        """
        try:
            # Check if we have the necessary data to recreate
            if app.app_type == "custom":
                # For custom apps, we need the entrypoint file
                return bool(app.entrypoint_file)
            else:
                # For default apps, we can always recreate
                return True
        except Exception as e:
            logger.error("Failed to check if container can be recreated", 
                        app_id=str(app.id), error=str(e))
            return False
