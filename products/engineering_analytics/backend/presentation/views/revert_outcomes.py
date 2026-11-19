from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.presentation.serializers.revert_outcomes import RevertOutcomesSerializer
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_FROM,
    _DATE_TO,
    _REPO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
)


class RevertOutcomeActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["revert_outcomes"]

    @extend_schema(
        operation_id="engineering_analytics_revert_outcomes",
        parameters=[_DATE_FROM, _DATE_TO, _SOURCE_ID, _REPO],
        responses={
            200: RevertOutcomesSerializer,
            400: OpenApiResponse(description="Invalid date_from, date_to, or source_id."),
        },
        description=(
            "How many pull requests merged in the window were later reverted, split by how each was authored "
            "and by who approved it, with the list of reverted pull requests. A revert is linked to the pull "
            "request it undid through the 'Reverts #N' line in the revert's description, so a revert without "
            "that line is not counted. Pull requests that are themselves reverts are left out of every count."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def revert_outcomes(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_revert_outcomes(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date_from, date_to, or source_id")
        return Response(RevertOutcomesSerializer(instance=result).data)
