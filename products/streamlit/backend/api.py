from typing import Any

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.models.utils import uuid7

from .container_service import ContainerService
from .models import StreamlitApp

logger = structlog.get_logger(__name__)


class StreamlitAppSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = StreamlitApp
        fields = [
            "id",
            "name",
            "description",
            "container_id",
            "container_status",
            "port",
            "internal_url",
            "public_url",
            "last_accessed",
            "entrypoint_file",
            "requirements_file",
            "app_type",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "container_id", "container_status", "port", "internal_url", 
            "public_url", "last_accessed", "created_by", "created_at", "updated_at"
        ]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by_id"] = self.context["request"].user.id

        # Create the app instance first
        app = super().create(validated_data)

        # Deploy the container asynchronously
        try:
            container_service = ContainerService()
            
            # Determine app type and deploy accordingly
            if app.app_type == "custom" and app.entrypoint_file:
                # Custom app with uploaded files
                container_id, port, internal_url, public_url = container_service.deploy_custom_app(
                    app.id, app.name, app.entrypoint_file, app.requirements_file
                )
            else:
                # Default app
                container_id, port, internal_url, public_url = container_service.deploy_default_app(
                    app.id, app.name
                )
            
            app.container_id = container_id
            app.port = port
            app.internal_url = internal_url
            app.public_url = public_url
            app.container_status = StreamlitApp.ContainerStatus.RUNNING
            app.save(update_fields=["container_id", "port", "internal_url", "public_url", "container_status"])
        except Exception as e:
            logger.error("Failed to deploy container", app_id=str(app.id), error=str(e))
            app.container_status = StreamlitApp.ContainerStatus.FAILED
            app.save(update_fields=["container_status"])

        return app


class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "streamlit_app"
    queryset = StreamlitApp.objects.select_related("created_by").all()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        return StreamlitAppSerializer

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        
        # Stop and remove the container if it exists
        if instance.container_id:
            try:
                container_service = ContainerService()
                container_service.stop_and_remove_container(instance.container_id)
            except Exception as e:
                logger.error("Failed to stop container", container_id=instance.container_id, error=str(e))

        return super().destroy(request, *args, **kwargs)
