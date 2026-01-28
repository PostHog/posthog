"""API endpoint for triggering trace clustering workflows."""

import time
import asyncio
from typing import cast

from django.conf import settings

import structlog
import posthoganalytics
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    DEFAULT_HDBSCAN_MIN_SAMPLES,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_CLUSTER_SIZE_FRACTION,
    DEFAULT_UMAP_N_COMPONENTS,
    MIN_CLUSTER_SIZE_FRACTION_MAX,
    MIN_CLUSTER_SIZE_FRACTION_MIN,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringWorkflowInputs

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)


class ClusteringRunRequestSerializer(serializers.Serializer):
    """Serializer for clustering workflow request parameters."""

    # Basic workflow parameters
    lookback_days = serializers.IntegerField(
        required=False,
        default=DEFAULT_LOOKBACK_DAYS,
        min_value=1,
        max_value=90,
        help_text="Number of days to look back for traces",
    )
    max_samples = serializers.IntegerField(
        required=False,
        default=DEFAULT_MAX_SAMPLES,
        min_value=20,
        max_value=10000,
        help_text="Maximum number of traces to sample for clustering",
    )

    # Embedding preprocessing
    embedding_normalization = serializers.ChoiceField(
        required=False,
        default="none",
        choices=["none", "l2"],
        help_text="Embedding normalization method: 'none' (raw embeddings) or 'l2' (L2 normalize before clustering)",
    )

    # Dimensionality reduction parameters
    dimensionality_reduction_method = serializers.ChoiceField(
        required=False,
        default="umap",
        choices=["none", "umap", "pca"],
        help_text="Dimensionality reduction method: 'none' (cluster on raw), 'umap', or 'pca'",
    )
    dimensionality_reduction_ndims = serializers.IntegerField(
        required=False,
        default=DEFAULT_UMAP_N_COMPONENTS,
        min_value=2,
        max_value=500,
        help_text="Target dimensions for dimensionality reduction (ignored if method is 'none')",
    )

    # Clustering method
    clustering_method = serializers.ChoiceField(
        required=False,
        default="hdbscan",
        choices=["hdbscan", "kmeans"],
        help_text="Clustering algorithm: 'hdbscan' (density-based, auto-determines k) or 'kmeans' (centroid-based)",
    )

    # HDBSCAN parameters (used when clustering_method='hdbscan')
    min_cluster_size_fraction = serializers.FloatField(
        required=False,
        default=DEFAULT_MIN_CLUSTER_SIZE_FRACTION,
        min_value=MIN_CLUSTER_SIZE_FRACTION_MIN,
        max_value=MIN_CLUSTER_SIZE_FRACTION_MAX,
        help_text="Minimum cluster size as fraction of total samples (e.g., 0.05 = 5%)",
    )
    hdbscan_min_samples = serializers.IntegerField(
        required=False,
        default=DEFAULT_HDBSCAN_MIN_SAMPLES,
        min_value=1,
        max_value=100,
        help_text="HDBSCAN min_samples parameter (higher = more conservative clustering)",
    )

    # K-means parameters (used when clustering_method='kmeans')
    kmeans_min_k = serializers.IntegerField(
        required=False,
        default=2,
        min_value=2,
        max_value=50,
        help_text="Minimum number of clusters to try for k-means",
    )
    kmeans_max_k = serializers.IntegerField(
        required=False,
        default=20,
        min_value=2,
        max_value=100,
        help_text="Maximum number of clusters to try for k-means",
    )

    # Experiment tracking
    run_label = serializers.CharField(
        required=False,
        default="",
        max_length=50,
        allow_blank=True,
        help_text="Optional label/tag for the clustering run (used as suffix in run_id for tracking experiments)",
    )

    # Visualization parameters
    visualization_method = serializers.ChoiceField(
        required=False,
        default="umap",
        choices=["umap", "pca", "tsne"],
        help_text="Method for 2D scatter plot visualization: 'umap', 'pca', or 'tsne'",
    )

    # Trace filters
    trace_filters = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Property filters to scope which traces are included in clustering (PostHog standard format)",
    )


class LLMAnalyticsClusteringRunViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """ViewSet for triggering and managing clustering workflow runs."""

    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]
    serializer_class = ClusteringRunRequestSerializer

    @llma_track_latency("llma_clustering_create")
    @monitor(feature=None, endpoint="llma_clustering_create", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        """
        Trigger a new clustering workflow run.

        This endpoint validates the request parameters and starts a Temporal workflow
        to perform trace clustering with the specified configuration.
        """
        # Check feature flag
        distinct_id = getattr(request.user, "distinct_id", None)
        if not distinct_id or not posthoganalytics.feature_enabled(
            "llm-analytics-clustering-admin",
            distinct_id,
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
        ):
            return Response(
                {"detail": "This feature is not available."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ClusteringRunRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        # Extract validated parameters
        lookback_days = serializer.validated_data["lookback_days"]
        max_samples = serializer.validated_data["max_samples"]
        embedding_normalization = serializer.validated_data["embedding_normalization"]
        dimensionality_reduction_method = serializer.validated_data["dimensionality_reduction_method"]
        dimensionality_reduction_ndims = serializer.validated_data["dimensionality_reduction_ndims"]
        run_label = serializer.validated_data["run_label"]
        clustering_method = serializer.validated_data["clustering_method"]
        visualization_method = serializer.validated_data["visualization_method"]
        trace_filters = serializer.validated_data["trace_filters"]

        # Build method-specific params dict
        clustering_method_params: dict = {}
        if clustering_method == "hdbscan":
            clustering_method_params = {
                "min_cluster_size_fraction": serializer.validated_data["min_cluster_size_fraction"],
                "min_samples": serializer.validated_data["hdbscan_min_samples"],
            }
        elif clustering_method == "kmeans":
            clustering_method_params = {
                "min_k": serializer.validated_data["kmeans_min_k"],
                "max_k": serializer.validated_data["kmeans_max_k"],
            }

        # Build workflow inputs
        inputs = ClusteringWorkflowInputs(
            team_id=self.team_id,
            lookback_days=lookback_days,
            max_samples=max_samples,
            embedding_normalization=embedding_normalization,
            dimensionality_reduction_method=dimensionality_reduction_method,
            dimensionality_reduction_ndims=dimensionality_reduction_ndims,
            run_label=run_label,
            clustering_method=clustering_method,
            clustering_method_params=clustering_method_params,
            visualization_method=visualization_method,
            trace_filters=trace_filters,
        )

        # Generate unique workflow ID (follows naming convention from trace_clustering constants)
        workflow_id = f"llma-trace-clustering-manual-{self.team_id}-{int(time.time() * 1000)}"

        # Start Temporal workflow
        try:
            logger.info(
                "Attempting to start clustering workflow",
                workflow_id=workflow_id,
                team_id=self.team_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            )
            client = sync_connect()
            logger.info("Connected to Temporal client")
            asyncio.run(
                client.start_workflow(
                    WORKFLOW_NAME,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            )
            logger.info("Workflow started successfully", workflow_id=workflow_id)

            logger.info(
                "Started clustering workflow",
                workflow_id=workflow_id,
                team_id=self.team_id,
                lookback_days=lookback_days,
                max_samples=max_samples,
                embedding_normalization=embedding_normalization,
                dimensionality_reduction_method=dimensionality_reduction_method,
                dimensionality_reduction_ndims=dimensionality_reduction_ndims,
                run_label=run_label,
                clustering_method=clustering_method,
                clustering_method_params=clustering_method_params,
                trace_filters_count=len(trace_filters),
            )

            # Track workflow triggered
            report_user_action(
                cast(User, request.user),
                "llma clustering workflow triggered",
                {
                    "workflow_id": workflow_id,
                    "lookback_days": lookback_days,
                    "max_samples": max_samples,
                    "embedding_normalization": embedding_normalization,
                    "dimensionality_reduction_method": dimensionality_reduction_method,
                    "dimensionality_reduction_ndims": dimensionality_reduction_ndims,
                    "run_label": run_label,
                    "clustering_method": clustering_method,
                    "clustering_method_params": clustering_method_params,
                    "trace_filters_count": len(trace_filters),
                    "trigger_type": "manual",
                },
                self.team,
            )

            return Response(
                {
                    "workflow_id": workflow_id,
                    "status": "started",
                    "parameters": {
                        "team_id": self.team_id,
                        "lookback_days": lookback_days,
                        "max_samples": max_samples,
                        "embedding_normalization": embedding_normalization,
                        "dimensionality_reduction_method": dimensionality_reduction_method,
                        "dimensionality_reduction_ndims": dimensionality_reduction_ndims,
                        "clustering_method": clustering_method,
                        "clustering_method_params": clustering_method_params,
                        "run_label": run_label,
                        "trace_filters": trace_filters,
                    },
                },
                status=202,
            )

        except Exception as e:
            logger.exception(
                "Failed to start clustering workflow",
                team_id=self.team_id,
                error=str(e),
            )
            return Response({"error": "Failed to start clustering workflow"}, status=500)
