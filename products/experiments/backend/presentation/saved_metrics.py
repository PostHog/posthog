"""ViewSet for saved metrics presentation layer."""

from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.experiments.backend.models.experiment import ExperimentSavedMetric

from ee.api.rbac.access_control import AccessControlViewSetMixin

from .saved_metric_serializers import ExperimentSavedMetricSerializer


@extend_schema(tags=["experiments"], extensions={"x-swagger-tag": "experiment_saved_metrics"})
class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for experiment saved metrics.

    All operations route through the facade layer instead of calling service directly.
    """

    scope_object = "experiment_saved_metric"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").all()
    serializer_class = ExperimentSavedMetricSerializer

    def safely_get_queryset(self, queryset):
        """Override to apply ordering."""
        from django.db.models.functions import Lower

        # For now, still use queryset directly
        # In future PR, could use facade.list_saved_metrics
        return queryset.order_by(Lower("name"))

    def perform_destroy(self, instance: ExperimentSavedMetric) -> None:
        """Delete saved metric via facade."""
        from products.experiments.backend.facade import delete_saved_metric

        delete_saved_metric(
            team=self.team,
            user=cast(User, self.request.user),
            saved_metric=instance,
        )
