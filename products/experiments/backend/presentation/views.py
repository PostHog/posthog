"""
Presentation views for experiments product.

This module provides HTTP endpoints using the new products architecture
with facade DTOs and presentation serializers.
"""

from typing import Literal

from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.experiments.backend.facade import create_experiment
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.serializers import ExperimentCreateSerializer


class ExperimentViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for experiment operations using new products architecture.

    This is a new implementation alongside the existing EnterpriseExperimentsViewSet.
    It uses the facade layer and presentation serializers to handle both old and
    new request formats.
    """

    scope_object: Literal["experiment"] = "experiment"
    queryset = Experiment.objects.all()

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "create":
            return ExperimentCreateSerializer
        return ExperimentCreateSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        Create a new experiment using the facade API.

        Supports both:
        - Old format: parameters.feature_flag_variants
        - New format: feature_flag_filters

        Returns:
            201 Created with experiment data
            400 Bad Request if validation fails
        """
        serializer = self.get_serializer(data=request.data, context={"get_team": lambda: self.team})

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Convert to facade DTO
        input_dto = serializer.to_facade_dto()

        # Call facade API
        try:
            experiment_dto = create_experiment(team=self.team, user=request.user, input_dto=input_dto)
        except Exception:
            # Let Django's exception handling deal with this
            # (will be caught by DRF's exception handler)
            raise

        # Convert DTO to response format
        # For now, return a simple dict matching the Experiment model structure
        # In the future, we can create a response serializer
        experiment = Experiment.objects.get(id=experiment_dto.id)
        response_data = {
            "id": experiment.id,
            "name": experiment.name,
            "description": experiment.description,
            "feature_flag_key": experiment.feature_flag.key,
            "feature_flag": experiment.feature_flag.id,
            "start_date": experiment.start_date,
            "end_date": experiment.end_date,
            "created_at": experiment.created_at,
            "updated_at": experiment.updated_at,
        }

        return Response(response_data, status=status.HTTP_201_CREATED)
