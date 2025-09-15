import structlog
from celery import shared_task
from django.db import transaction

from .container_service import ContainerService
from .models import StreamlitApp

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def check_streamlit_container_health(app_id: str) -> None:
    """
    Check the health of a specific Streamlit container and update its status.
    
    Args:
        app_id: UUID of the StreamlitApp to check
    """
    try:
        with transaction.atomic():
            app = StreamlitApp.objects.select_for_update().get(id=app_id)
            
            if not app.container_id:
                logger.warning("No container ID for app", app_id=app_id)
                return
            
            container_service = ContainerService()
            
            # Get current container status from Docker
            docker_status = container_service.get_container_status(app.container_id)
            
            if docker_status is None:
                # Container doesn't exist anymore - try to recreate it
                logger.info("Container not found, attempting to recreate", 
                           app_id=app_id, container_id=app.container_id)
                
                # Check if we can recreate the container
                if not container_service.can_recreate_container(app):
                    logger.warning("Cannot recreate container - missing required data", 
                                 app_id=app_id, app_type=app.app_type)
                    app.container_status = StreamlitApp.ContainerStatus.FAILED
                    app.save(update_fields=['container_status'])
                    return
                
                try:
                    # Clear the old container ID and recreate
                    app.container_id = ""
                    app.container_status = StreamlitApp.ContainerStatus.PENDING
                    app.save(update_fields=['container_id', 'container_status'])
                    
                    # Recreate the container
                    if app.app_type == "custom" and app.entrypoint_file:
                        # Custom app with uploaded files
                        container_id, port, internal_url, public_url = container_service.deploy_custom_app(
                            str(app.id), app.name, app.entrypoint_file, app.requirements_file
                        )
                    else:
                        # Default app
                        container_id, port, internal_url, public_url = container_service.deploy_default_app(
                            str(app.id), app.name
                        )
                    
                    # Update with new container info
                    app.container_id = container_id
                    app.port = port
                    app.internal_url = internal_url
                    app.public_url = public_url
                    app.container_status = StreamlitApp.ContainerStatus.RUNNING
                    app.save(update_fields=['container_id', 'port', 'internal_url', 'public_url', 'container_status'])
                    
                    logger.info("Successfully recreated container", 
                               app_id=app_id, new_container_id=container_id)
                    
                except Exception as e:
                    logger.error("Failed to recreate container", 
                                app_id=app_id, error=str(e))
                    app.container_status = StreamlitApp.ContainerStatus.FAILED
                    app.save(update_fields=['container_status'])
                return
            
            # Check if container is actually healthy
            is_healthy = container_service.check_container_health(
                app.container_id, 
                app.internal_url
            )
            
            # Determine the correct status
            if docker_status == 'running' and is_healthy:
                new_status = StreamlitApp.ContainerStatus.RUNNING
            elif docker_status == 'running' and not is_healthy:
                new_status = StreamlitApp.ContainerStatus.FAILED
            elif docker_status == 'exited':
                new_status = StreamlitApp.ContainerStatus.STOPPED
            else:
                new_status = StreamlitApp.ContainerStatus.FAILED
            
            # Update status if it changed
            if app.container_status != new_status:
                logger.info("Container status changed", 
                           app_id=app_id, 
                           container_id=app.container_id,
                           old_status=app.container_status,
                           new_status=new_status,
                           docker_status=docker_status,
                           is_healthy=is_healthy)
                
                app.container_status = new_status
                app.save(update_fields=['container_status'])
            else:
                logger.debug("Container status unchanged", 
                           app_id=app_id, 
                           container_id=app.container_id,
                           status=app.container_status)
                
    except StreamlitApp.DoesNotExist:
        logger.warning("StreamlitApp not found", app_id=app_id)
    except Exception as e:
        logger.error("Failed to check container health", 
                    app_id=app_id, error=str(e))


@shared_task(ignore_result=True)
def check_all_streamlit_containers_health() -> None:
    """
    Check the health of all Streamlit containers.
    This task should be run periodically to ensure all containers are healthy.
    """
    try:
        # Get all apps with containers
        apps = StreamlitApp.objects.filter(
            container_id__isnull=False
        ).exclude(
            container_id=''
        ).values_list('id', flat=True)
        
        logger.info("Starting health check for all Streamlit containers", 
                   count=len(apps))
        
        # Check each app's health
        for app_id in apps:
            check_streamlit_container_health.delay(str(app_id))
            
        logger.info("Queued health checks for all Streamlit containers", 
                   count=len(apps))
        
    except Exception as e:
        logger.error("Failed to queue health checks for all containers", error=str(e))


@shared_task(ignore_result=True)
def restart_streamlit_container(app_id: str) -> None:
    """
    Restart a Streamlit container and update its status.
    
    Args:
        app_id: UUID of the StreamlitApp to restart
    """
    try:
        with transaction.atomic():
            app = StreamlitApp.objects.select_for_update().get(id=app_id)
            
            if not app.container_id:
                logger.warning("No container ID for app", app_id=app_id)
                return
            
            container_service = ContainerService()
            
            # Check if container exists
            docker_status = container_service.get_container_status(app.container_id)
            if docker_status is None:
                logger.info("Container not found during restart, attempting to recreate", 
                           app_id=app_id, container_id=app.container_id)
                
                # Check if we can recreate the container
                if not container_service.can_recreate_container(app):
                    logger.warning("Cannot recreate container during restart - missing required data", 
                                 app_id=app_id, app_type=app.app_type)
                    app.container_status = StreamlitApp.ContainerStatus.FAILED
                    app.save(update_fields=['container_status'])
                    return
                
                try:
                    # Clear the old container ID and recreate
                    app.container_id = ""
                    app.container_status = StreamlitApp.ContainerStatus.PENDING
                    app.save(update_fields=['container_id', 'container_status'])
                    
                    # Recreate the container
                    if app.app_type == "custom" and app.entrypoint_file:
                        # Custom app with uploaded files
                        container_id, port, internal_url, public_url = container_service.deploy_custom_app(
                            str(app.id), app.name, app.entrypoint_file, app.requirements_file
                        )
                    else:
                        # Default app
                        container_id, port, internal_url, public_url = container_service.deploy_default_app(
                            str(app.id), app.name
                        )
                    
                    # Update with new container info
                    app.container_id = container_id
                    app.port = port
                    app.internal_url = internal_url
                    app.public_url = public_url
                    app.container_status = StreamlitApp.ContainerStatus.RUNNING
                    app.save(update_fields=['container_id', 'port', 'internal_url', 'public_url', 'container_status'])
                    
                    logger.info("Successfully recreated container during restart", 
                               app_id=app_id, new_container_id=container_id)
                    return
                    
                except Exception as e:
                    logger.error("Failed to recreate container during restart", 
                                app_id=app_id, error=str(e))
                    app.container_status = StreamlitApp.ContainerStatus.FAILED
                    app.save(update_fields=['container_status'])
                    return
            
            # Restart the container
            container_service.restart_container(app.container_id)
            
            # Update status to running
            app.container_status = StreamlitApp.ContainerStatus.RUNNING
            app.save(update_fields=['container_status'])
            
            logger.info("Successfully restarted Streamlit container", 
                       app_id=app_id, container_id=app.container_id)
            
    except StreamlitApp.DoesNotExist:
        logger.warning("StreamlitApp not found", app_id=app_id)
    except Exception as e:
        logger.error("Failed to restart container", 
                    app_id=app_id, error=str(e))
        
        # Mark as failed if restart failed
        try:
            with transaction.atomic():
                app = StreamlitApp.objects.select_for_update().get(id=app_id)
                app.container_status = StreamlitApp.ContainerStatus.FAILED
                app.save(update_fields=['container_status'])
        except StreamlitApp.DoesNotExist:
            pass
