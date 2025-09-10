import docker
import structlog
import socket
from typing import Optional
from django.conf import settings

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
            
            logger.info("Successfully deployed Streamlit container", 
                       app_id=app_id, container_id=container.id, port=port)
            
            return container.id, port, internal_url, public_url
            
        except Exception as e:
            logger.error("Failed to deploy Streamlit container", 
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
