"""Staff-only DRF API for the enrichment "AI enrichment": list labels, list a label's prompt
config versions, and flip which version is active.

Shaped around config version + input rows + verdict rows, not around enrichment orgs, so the
same contract can host a future team-scoped customer-facing product without a rewrite.

Serializers live in ai_enrichment_serializers.py.
"""

from typing import Any

from django.db import transaction
from django.db.models import Count

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.utils import ErrorResponseSerializer
from posthog.helpers.impersonation import is_impersonated
from posthog.permissions import IsStaffUser

from products.growth.backend.api.ai_enrichment_serializers import (
    ActivateRequestSerializer,
    ConfigListResponseSerializer,
    ConfigsQuerySerializer,
    ConfigVersionSerializer,
    LabelListResponseSerializer,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig

logger = structlog.get_logger(__name__)


class AIEnrichmentViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped API for the enrichment AI enrichment: browse labels and their prompt
    config versions, and flip which version is active.

    Registered on the root router so it is not team-nested - prompt configs are instance-global,
    not scoped to any team or org.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    @validated_request(responses={200: OpenApiResponse(response=LabelListResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def labels(self, request: request.Request, **kwargs: Any) -> response.Response:
        counts = EnrichmentPromptConfig.objects.values("name").annotate(version_count=Count("id")).order_by("name")
        active_version_by_label = dict(
            EnrichmentPromptConfig.objects.filter(is_active=True).values_list("name", "version")
        )
        results = [
            {
                "label": row["name"],
                "version_count": row["version_count"],
                "active_version": active_version_by_label.get(row["name"]),
            }
            for row in counts
        ]
        return response.Response(LabelListResponseSerializer({"results": results}).data)

    @validated_request(
        query_serializer=ConfigsQuerySerializer,
        responses={200: OpenApiResponse(response=ConfigListResponseSerializer)},
    )
    @action(methods=["GET"], detail=False)
    def configs(self, request: request.Request, **kwargs: Any) -> response.Response:
        label = request.validated_query_data["label"]
        versions = list(
            EnrichmentPromptConfig.objects.filter(name=label).select_related("created_by").order_by("-created_at")
        )
        versions_with_results = set(
            EnrichmentLabelResult.objects.filter(
                label_name=label, prompt_version__in=[version.version for version in versions]
            )
            .values_list("prompt_version", flat=True)
            .distinct()
        )
        # Pass raw model instances through the outer wrapper so its nested `results =
        # ConfigVersionSerializer(many=True)` field does the serialization exactly once - the
        # SerializerMethodFields below read model attributes (e.g. obj.version) and would break
        # on a second pass over already-serialized dicts.
        serializer = ConfigListResponseSerializer(
            {"results": versions}, context={"versions_with_results": versions_with_results}
        )
        return response.Response(serializer.data)

    @validated_request(
        request_serializer=ActivateRequestSerializer,
        responses={
            200: OpenApiResponse(response=ConfigVersionSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer, description="Config not found."),
        },
    )
    @action(methods=["POST"], detail=False)
    def activate(self, request: request.Request, **kwargs: Any) -> response.Response:
        config_id = request.validated_data["config_id"]
        # The label is read under the row lock, not before it: a rename committing between the
        # read and the transaction would target the deactivation at the retired name, match no
        # siblings, and leave two rows active under the new one - which the partial unique
        # constraint growth_prompt_config_one_active then rejects as a 500.
        with transaction.atomic():
            config = EnrichmentPromptConfig.objects.select_for_update().filter(pk=config_id).first()
            if config is None:
                raise NotFound(f"Config {config_id} not found.")
            # Deactivate first, then activate, so the constraint only ever sees at most one
            # active row per label.
            EnrichmentPromptConfig.objects.filter(name=config.name, is_active=True).exclude(pk=config.pk).update(
                is_active=False
            )
            config.is_active = True
            config.save(update_fields=["is_active"])

        logger.info(
            "growth_ai_enrichment_activate",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            label=config.name,
            version=config.version,
        )

        has_results = EnrichmentLabelResult.objects.filter(
            label_name=config.name, prompt_version=config.version
        ).exists()
        serializer = ConfigVersionSerializer(
            config, context={"versions_with_results": {config.version} if has_results else set()}
        )
        return response.Response(serializer.data)
