"""The setup context action, the project facts that decide how to configure a new experiment."""

import logging
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.helpers.impersonation import get_original_user_from_session
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric
from products.experiments.backend.presentation.serializers.setup_context import (
    ExperimentSetupContextInputSerializer,
    ExperimentSetupContextResponseSerializer,
)
from products.experiments.backend.setup_context import (
    EXPERIMENT_SETUP_CONTEXT_FLAG,
    SetupContextInputs,
    build_setup_context,
)

logger = logging.getLogger(__name__)


class ExperimentSetupContextMixin(TeamAndOrgViewSetMixin):
    @validated_request(
        request_serializer=ExperimentSetupContextInputSerializer,
        responses={200: OpenApiResponse(response=ExperimentSetupContextResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="setup_context",
        # The response carries saved-metric definitions and reuse counts, which the saved-metric
        # API gates behind its own scope. Object-level filtering does not check token scopes.
        # It also counts arbitrary events across the project, which /query/ gates behind query:read.
        required_scopes=["experiment:read", "experiment_saved_metric:read", "query:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def setup_context(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Facts about this project that decide how to configure a new experiment.

        Returns the team's experiment defaults, which SDKs call feature flags, traffic on a target
        surface, the baseline of a candidate metric, how recent experiments were set up, and the
        most reused shared metrics. Each section has its own status, so a slow or failed read
        leaves the others valid. POST because the inputs describe a plan rather than a resource;
        the endpoint only reads.
        """
        if not self._setup_context_enabled():
            raise NotFound()

        data = request.validated_data
        # detail=False actions skip the automatic list-action ACL filtering, so filter here: the
        # response names experiments and shared metrics, which must respect object-level access.
        experiments = self.user_access_control.filter_queryset_by_access_level(
            Experiment.objects.filter(team_id=self.team.pk)
        )
        saved_metrics = self.user_access_control.filter_queryset_by_access_level(
            ExperimentSavedMetric.objects.filter(team_id=self.team.pk), resource="experiment_saved_metric"
        )
        context = build_setup_context(
            team=self.team,
            inputs=SetupContextInputs(
                target_event=data.get("target_event") or None,
                target_url_contains=data.get("target_url_contains") or None,
                target_properties=tuple(data.get("target_properties") or ()),
                metric_event=data.get("metric_event") or None,
                metric_properties=tuple(data.get("metric_properties") or ()),
                previous_experiments_limit=data["previous_experiments_limit"],
                shared_metrics_limit=data["shared_metrics_limit"],
            ),
            experiments=experiments,
            saved_metrics=saved_metrics,
        )
        return Response(ExperimentSetupContextResponseSerializer(context).data)

    def _setup_context_enabled(self) -> bool:
        # In a loginas impersonation session request.user is the customer. The flag is evaluated for the staff
        # user, so support can read a customer's setup context without the flag being on for that customer.
        # OAuth impersonation (MCP) has no session, so it keeps the customer's flag, which also gates the tool.
        flag_user = get_original_user_from_session(self.request) if is_impersonated_session(self.request) else None
        try:
            return posthog_feature_flag_enabled(
                EXPERIMENT_SETUP_CONTEXT_FLAG,
                str((flag_user or cast(User, self.request.user)).distinct_id),
                organization_id=self.organization_id,
                team_id=self.team.id,
            )
        except Exception:
            logger.warning("Failed to evaluate the experiment setup context flag", exc_info=True)
            return False
