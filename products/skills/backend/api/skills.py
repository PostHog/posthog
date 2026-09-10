"""The skills API: the catalog endpoints, and the viewset that composes the rest.

Each group of endpoints lives in its own module as a mixin — versions, lifecycle, files, transfer,
marketplace, community — and this module wires them together with the DRF plumbing that has to sit
on the concrete viewset (renderers, throttles, scopes, serializer context).
"""

from collections.abc import Sequence
from typing import Any, cast

from django.db import IntegrityError
from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.throttling import BaseThrottle

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import AccessControlPermission, get_authenticator_scopes
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.ai_observability.backend.api.metrics import llma_track_latency

from ..models.skills import LLMSkill
from .skill_analytics import record_skill_event, skill_analytics_props
from .skill_catalog import list_queryset
from .skill_permissions import CommunityPublishFeatureFlagPermission, CommunityPublishOwnerPermission
from .skill_search import SkillSearchTimeout, search_skills
from .skill_serializers import (
    LLMSkillCreateSerializer,
    LLMSkillListQuerySerializer,
    LLMSkillListSerializer,
    LLMSkillSearchErrorSerializer,
    LLMSkillSearchQuerySerializer,
    LLMSkillSearchResponseSerializer,
    LLMSkillSerializer,
)
from .skill_services import get_active_skill_queryset, resolve_skill_owners_for_names
from .skill_throttles import (
    CommunityPublishBurstThrottle,
    CommunityPublishSustainedThrottle,
    SkillBundleBurstThrottle,
    SkillBundleSustainedThrottle,
    SkillSearchBurstThrottle,
    SkillSearchSustainedThrottle,
)
from .skill_view_community import SkillCommunityPublishMixin
from .skill_view_files import SkillFileActionsMixin
from .skill_view_lifecycle import SkillLifecycleActionsMixin
from .skill_view_marketplace import SkillMarketplaceActionsMixin
from .skill_view_transfer import ZIP_ACTIONS, SkillTransferActionsMixin, ZipRenderer
from .skill_view_versions import SkillVersionActionsMixin


class LLMSkillViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    SkillVersionActionsMixin,
    SkillLifecycleActionsMixin,
    SkillFileActionsMixin,
    SkillTransferActionsMixin,
    SkillMarketplaceActionsMixin,
    SkillCommunityPublishMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "llm_skill"
    queryset = LLMSkill.objects.all()
    serializer_class = LLMSkillSerializer
    permission_classes = [
        AccessControlPermission,
        CommunityPublishFeatureFlagPermission,
        CommunityPublishOwnerPermission,
    ]

    def safely_get_queryset(self, queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
        return get_active_skill_queryset(self.team)

    def get_renderers(self) -> list[BaseRenderer]:
        renderers = super().get_renderers()
        if self.action in ZIP_ACTIONS:
            return [*renderers, ZipRenderer()]
        return renderers

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "publish_to_community":
            return [CommunityPublishBurstThrottle(), CommunityPublishSustainedThrottle()]
        if self.action == "bundle":
            return [SkillBundleBurstThrottle(), SkillBundleSustainedThrottle()]
        if self.action == "search":
            return [SkillSearchBurstThrottle(), SkillSearchSustainedThrottle()]
        if self.action in ["update_by_name", "get_by_name", "resolve_by_name"]:
            return [BurstRateThrottle(), SustainedRateThrottle()]
        return super().get_throttles()

    # Differentiates read vs write scopes for GET/PATCH on the shared /name/<slug> URL
    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        super_method = getattr(super(), "dangerously_get_required_scopes", None)
        if callable(super_method):
            mixin_result = super_method(request, view)
            if mixin_result is not None:
                return mixin_result

        if view.action in ["get_by_name", "update_by_name"]:
            return ["llm_skill:write"] if request.method == "PATCH" else ["llm_skill:read"]
        # get_file and delete_file share a URL via @get_file.mapping.delete. We deliberately do
        # NOT set required_scopes on get_file's @action — see the note there. Resolve per-method:
        # GET (and HEAD, which DRF auto-routes to GET handlers) → read, DELETE → write.
        if view.action in ["get_file", "delete_file"]:
            if request.method == "DELETE":
                return ["llm_skill:write"]
            if request.method in ("GET", "HEAD"):
                return ["llm_skill:read"]
        # marketplace_command (GET, read state) and issue_marketplace_command (POST, mint/rotate the
        # credential) share a URL via @marketplace_command.mapping.post. Resolve per-method.
        if view.action in ["marketplace_command", "issue_marketplace_command"]:
            return ["llm_skill:write"] if request.method == "POST" else ["llm_skill:read"]
        return None

    def _is_scout_sandbox_caller(self) -> bool:
        """Whether the request is authenticated with a Signals scout sandbox token.

        The scout harness's sandbox token is the only issuer of `signal_scout_internal:*`
        scopes, so their presence identifies a scout run. Session auth and ordinary API
        keys never carry them.
        """
        scopes = get_authenticator_scopes(getattr(self.request, "successful_authenticator", None))
        return scopes is not None and any(scope.startswith("signal_scout_internal:") for scope in scopes)

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if self._is_scout_sandbox_caller():
            context["scout_sandbox_caller"] = True
        return context

    @extend_schema(
        parameters=[LLMSkillSearchQuerySerializer],
        responses={
            200: LLMSkillSearchResponseSerializer,
            503: OpenApiResponse(
                response=LLMSkillSearchErrorSerializer,
                description="The bounded skill search exceeded its database timeout.",
            ),
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="search",
        required_scopes=["llm_skill:read"],
        pagination_class=None,
    )
    @llma_track_latency("llma_skills_search")
    @monitor(feature=None, endpoint="llma_skills_search", method="GET")
    def search(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = cast(str, self._validated_query(LLMSkillSearchQuerySerializer, request)["query"])
        try:
            results = search_skills(self.team, self.user_access_control, query)
        except SkillSearchTimeout:
            return Response(
                {"detail": "Skill search timed out. Use a more specific query and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"count": len(results), "results": results})

    def get_serializer_class(self):
        if self.action == "list":
            return LLMSkillListSerializer
        if self.action == "create":
            return LLMSkillCreateSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        instance = cast(LLMSkill, serializer.save())

        props = skill_analytics_props(instance)
        record_skill_event(
            log_event="llma_skill_created",
            action="llma skill created",
            user=cast(User, self.request.user),
            team=self.team,
            request=self.request,
            props=props,
        )

    @extend_schema(parameters=[LLMSkillListQuerySerializer])
    @llma_track_latency("llma_skills_list")
    @monitor(feature=None, endpoint="llma_skills_list", method="GET")
    def list(self, request: Request, *args, **kwargs) -> Response:
        params = self._validated_query(LLMSkillListQuerySerializer, request)
        queryset = self.filter_queryset(
            list_queryset(
                team=self.team,
                user_access_control=self.user_access_control,
                params=params,
                query_params=request.query_params,
            )
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            context = self._list_context_with_owners(page)
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        skills = list(queryset)
        context = self._list_context_with_owners(skills)
        serializer = self.get_serializer(skills, many=True, context=context)
        data = serializer.data
        return Response({"count": len(data), "results": data})

    # `Sequence`, not `list[...]`: the viewset defines a `list` method that shadows the builtin in the
    # class body where this annotation is evaluated.
    def _list_context_with_owners(self, skills: Sequence[LLMSkill]) -> dict[str, Any]:
        """Serializer context carrying a name→owners map, so the list serializes owners in one query."""
        owners_by_skill_name = resolve_skill_owners_for_names(self.team, [skill.name for skill in skills])
        return {**self.get_serializer_context(), "owners_by_skill_name": owners_by_skill_name}

    # Explicit response schema: the request serializer (`LLMSkillCreateSerializer`) exposes `owners`
    # write-only as a UUID list, but the view returns `_serialize_skill` (`LLMSkillSerializer`) with
    # `owners` as `UserBasic[]`. Without this, drf-spectacular would infer the response from the
    # create serializer and the generated `llmSkillsCreate` / MCP `skill-create` types would drop
    # (or mistype) the returned owners.
    @extend_schema(request=LLMSkillCreateSerializer, responses={201: LLMSkillSerializer})
    @llma_track_latency("llma_skills_create")
    @monitor(feature=None, endpoint="llma_skills_create", method="POST")
    def create(self, request, *args, **kwargs):
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError as err:
            err_str = str(err)
            if any(
                constraint_name in err_str
                for constraint_name in ["unique_llm_skill_latest_per_team", "unique_llm_skill_version_per_team"]
            ):
                raise serializers.ValidationError({"name": "A skill with this name already exists."}, code="unique")
            if "unique_skill_file_path" in err_str:
                raise serializers.ValidationError({"files": "Duplicate file paths are not allowed."}, code="unique")
            raise
        return Response(self._serialize_skill(cast(LLMSkill, serializer.instance)), status=status.HTTP_201_CREATED)
