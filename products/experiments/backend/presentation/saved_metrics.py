from typing import Any, Literal, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import filters, request, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.paging import Page, PageRequest
from posthog.permissions import is_service_auth

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.presentation.access_control import (
    AccessControlViewSetMixin,
    UserAccessControlSerializerMixin,
)
from products.experiments.backend.facade import saved_metrics as saved_metrics_facade
from products.experiments.backend.facade.contracts import (
    ListAccess,
    SavedMetric,
    SavedMetricListFilters,
    SavedMetricNotFound,
    SavedMetricWrite,
    SavedMetricWriteField,
)


def _saved_metric_access_ref(saved_metric: SavedMetric, team_id: int) -> ObjectAccessRef:
    # The request's team, so a project's environment checks the metric against its own access rules.
    return ObjectAccessRef(
        resource="experiment_saved_metric",
        id=str(saved_metric.id),
        team_id=team_id,
        created_by_id=saved_metric.created_by_id,
    )


def _list_access(
    user_access_control: UserAccessControl,
    resource: Literal["experiment", "experiment_saved_metric"],
    *,
    viewer_id: int,
    include_all_if_admin: bool = False,
) -> ListAccess | None:
    access = user_access_control.list_access_filter(resource, include_all_if_admin=include_all_if_admin)
    if access is None:
        return None
    return ListAccess(
        viewer_id=viewer_id,
        only_allowed=access.only_allowed,
        allowed_ids=access.allowed_ids,
        blocked_ids=access.blocked_ids,
    )


class ExperimentSavedMetricLinkedExperimentSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Experiment ID.")
    name = serializers.CharField(help_text="Experiment name.")
    is_running = serializers.BooleanField(help_text="True when the experiment is launched and not yet stopped.")


# drf-spectacular publishes the docstring of the first base class as the schema description, so a docstring
# here would change the published API.
class ExperimentSavedMetricSerializer(UserAccessControlSerializerMixin, serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Name of the shared metric. Must be unique within the project (case-insensitive).",
    )
    description = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Short description of what the metric measures.",
    )
    query = serializers.JSONField(
        help_text=(
            "ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: "
            "'mean' (set source to an EventsNode with an event name), "
            "'funnel' (set series to an array of EventsNode steps), "
            "'ratio' (set numerator and denominator EventsNode entries), "
            "'quantile' (set source to an EventsNode or ActionsNode with math_property, the numeric "
            "property to measure, and quantile, the level in [0.01, 0.99], for example 0.9 for p90), or "
            "'retention' (set start_event and completion_event). "
            "Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics."
        ),
    )
    created_by = UserBasicSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    tags = serializers.ListField(required=False)
    user_access_level = serializers.SerializerMethodField(
        method_name="get_saved_metric_access_level",
        read_only=True,
        help_text="The effective access level the user has for this object",
    )
    linked_experiments = serializers.SerializerMethodField(
        help_text="Experiments using this shared metric (soft-deleted experiments excluded). "
        "Populated only on single-metric retrieve; always an empty list in list responses."
    )

    class Meta:
        fields = [
            "id",
            "name",
            "description",
            "query",
            "created_by",
            "created_at",
            "updated_at",
            "tags",
            "user_access_level",
            "linked_experiments",
        ]

    def get_fields(self) -> dict[str, serializers.Field]:
        # A plain serializer ignores Meta and puts base-class fields such as `user_access_level` first.
        # The published schema uses the order of Meta.fields.
        fields = super().get_fields()
        return {name: fields[name] for name in self.Meta.fields}

    def get_saved_metric_access_level(self, saved_metric: SavedMetric) -> str | None:
        if self.user_access_control is None:
            return None
        return self.get_user_access_level(_saved_metric_access_ref(saved_metric, team_id=self.context["get_team"]().id))

    @extend_schema_field(ExperimentSavedMetricLinkedExperimentSerializer(many=True))
    def get_linked_experiments(self, saved_metric: SavedMetric) -> list[dict]:
        # Retrieve-only: the list endpoint serves paginated pages (and the metric modal eagerly
        # loads all of them), so resolving links there would add a query per metric.
        view = self.context.get("view")
        if view is None or getattr(view, "action", None) != "retrieve":
            return []
        # Experiments carry object-level access controls; drop the ones this user cannot view
        user_access_control = self.user_access_control
        access = (
            _list_access(user_access_control, "experiment", viewer_id=self.context["request"].user.id)
            if user_access_control
            else None
        )
        experiments = saved_metrics_facade.list_linked_experiments(
            team_id=saved_metric.team_id, saved_metric_id=saved_metric.id, access=access
        )
        return [
            {"id": experiment.id, "name": experiment.name, "is_running": experiment.is_running}
            for experiment in experiments
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # The mixin's field-level access check reads the model fields of `self.instance`, which is a contract
        # here, so it would raise. No field of the shared metric model declares a field-level access rule.
        return attrs

    def validate_name(self, value: str) -> str:
        instance = cast(SavedMetric | None, self.instance)
        colliding_id = saved_metrics_facade.find_saved_metric_id_by_name(
            team_id=self.context["get_team"]().id,
            name=value,
            exclude_saved_metric_id=instance.id if instance else None,
        )
        if colliding_id is not None:
            raise serializers.ValidationError("A shared metric with this name already exists.")
        return value

    def to_write(self) -> SavedMetricWrite:
        data = self.validated_data
        return SavedMetricWrite(
            fields_set=frozenset(cast(SavedMetricWriteField, name) for name in data),
            name=data.get("name"),
            description=data.get("description"),
            query=data.get("query"),
            tags=tuple(data.get("tags") or ()),
        )


@extend_schema(extensions={"x-swagger-tag": "experiment_saved_metrics", "x-product": "experiments"})
class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "experiment_saved_metric"
    serializer_class = ExperimentSavedMetricSerializer
    pagination_class = FacadeLimitOffsetPagination
    path_parameters = {
        "pk": PathParameter(type=int, description="A unique integer value identifying this experiment saved metric."),
    }

    def read_object(self) -> SavedMetric | None:
        return saved_metrics_facade.get_saved_metric(team=self.team, saved_metric_id=self.kwargs["pk"])

    def object_access_ref(self, record: SavedMetric) -> ObjectAccessRef:
        return _saved_metric_access_ref(record, team_id=self.team.id)

    def _list_access(self) -> ListAccess | None:
        """The access control narrowing a queryset list gets from TeamAndOrgViewSetMixin, with the same gates."""
        if is_service_auth(self.request):
            return None
        return _list_access(
            self.user_access_control,
            "experiment_saved_metric",
            viewer_id=cast(User, self.request.user).id,
            include_all_if_admin=self.request.GET.get("admin_include_all") == "true",
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="event",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter to shared metrics whose query references this event name. Matches events "
                "used directly in metric queries as well as events behind any actions those metrics reference. "
                "Use this for reuse discovery (find a metric by what it measures); distinct from 'search', "
                "which matches the metric's own name/description/tags.",
            ),
            OpenApiParameter(name="search", type=OpenApiTypes.STR, required=False, description="A search term."),
        ],
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        list_filters = SavedMetricListFilters(
            # DRF's SearchFilter splits the terms, so `search` keeps the syntax of the other search endpoints.
            search_terms=tuple(filters.SearchFilter().get_search_terms(request)),
            event=request.query_params.get("event") or None,
        )
        access = self._list_access()

        def fetch(page: PageRequest) -> Page[SavedMetric]:
            return saved_metrics_facade.list_saved_metrics(
                team=self.team, filters=list_filters, access=access, page=page
            )

        return facade_page_response(self, fetch)

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ExperimentSavedMetricSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        saved_metric = saved_metrics_facade.create_saved_metric(
            team=self.team, user=cast(User, request.user), write=serializer.to_write()
        )
        return Response(self.get_serializer(saved_metric).data, status=status.HTTP_201_CREATED)

    def update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=False)

    def partial_update(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: request.Request, *, partial: bool) -> Response:
        saved_metric = self.get_object()
        serializer = ExperimentSavedMetricSerializer(
            saved_metric, data=request.data, partial=partial, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        try:
            saved_metric = saved_metrics_facade.update_saved_metric(
                team=self.team,
                user=cast(User, request.user),
                saved_metric_id=saved_metric.id,
                write=serializer.to_write(),
            )
        except SavedMetricNotFound:
            raise NotFound()
        return Response(self.get_serializer(saved_metric).data)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        saved_metric = self.get_object()
        try:
            saved_metrics_facade.delete_saved_metric(
                team=self.team, user=cast(User, request.user), saved_metric_id=saved_metric.id
            )
        except SavedMetricNotFound:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
