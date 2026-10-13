from drf_spectacular.utils import OpenApiResponse
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import PathsV2AnchorType, PathsV2Item, PathsV2Query

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.product_analytics.backend.facade.queries import (
    anchored_segment_to_funnels_query,
    edge_to_funnels_query,
    item_label,
    resolve_step_sources,
    step_source_for_event,
)

# Matches the PathsV2Filter maxSteps upper bound: a displayed segment can never be longer.
_MAX_SEGMENT_ITEMS = 20


class PathsV2SegmentItemSerializer(serializers.Serializer):
    event = serializers.CharField(
        help_text="Event of the step source this path item belongs to.",
    )
    label = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text=(
            "Label value from the source's naming property, after path cleaning. "
            "Null or omitted for sources without a naming property; an empty string means "
            "the property was missing on the event."
        ),
    )


class PathsV2SegmentToFunnelRequestSerializer(serializers.Serializer):
    query = serializers.JSONField(
        help_text=(
            "The PathsV2Query the segment is displayed under (JSON object with kind `PathsV2Query`). "
            "Step sources, path cleaning, excluded items, date range, and the gap or conversion "
            "window are read from it, so the emitted funnel counts exactly what the chart shows."
        ),
    )
    # min_length/max_length are ListSerializer kwargs many=True forwards at runtime
    # (LIST_SERIALIZER_KWARGS); the DRF stubs don't know them.
    items = PathsV2SegmentItemSerializer(  # type: ignore[call-arg]
        many=True,
        min_length=2,
        max_length=_MAX_SEGMENT_ITEMS,
        help_text=(
            "The segment's path items in displayed order. In open mode exactly two items - a "
            "single edge, source then target. In anchored mode the concrete chain as shown, "
            "starting at the anchor."
        ),
    )


class PathsV2SegmentToFunnelResponseSerializer(serializers.Serializer):
    funnels_query = serializers.JSONField(
        help_text=(
            "The FunnelsQuery (JSON object with kind `FunnelsQuery`) that reproduces the "
            "segment's displayed unique-actor count exactly. Wrap it in an InsightVizNode to "
            "open it as a funnel insight."
        ),
    )


class PathsV2ViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "insight"
    scope_object_read_actions = ["segment_to_funnel"]
    scope_object_write_actions: list[str] = []

    @validated_request(
        request_serializer=PathsV2SegmentToFunnelRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=PathsV2SegmentToFunnelResponseSerializer,
                description="The funnel that reproduces the segment's displayed count exactly.",
            ),
            400: OpenApiResponse(
                description=(
                    "The query is not a valid PathsV2Query, or the segment has no exact funnel "
                    "equivalent (an other-row endpoint, a multi-hop open-mode segment, or an "
                    "anchored segment that does not start at the anchor)."
                ),
            ),
        },
        summary="Convert a journey segment to a funnel",
        description=(
            "Converts a displayed journeys segment into the funnel query that reproduces its "
            "unique-actor count exactly. In open mode only a single edge converts (a two-step "
            "funnel with the inactivity gap as conversion window); in anchored mode any "
            "anchor-rooted chain converts (window W). The funnel is returned as JSON and is not "
            "executed or persisted here."
        ),
    )
    @action(methods=["POST"], detail=False, required_scopes=["insight:read"])
    def segment_to_funnel(self, request: ValidatedRequest, **kwargs) -> Response:
        try:
            query = PathsV2Query.model_validate(request.validated_data["query"])
        except PydanticValidationError as error:
            raise ValidationError({"query": f"Not a valid PathsV2Query: {error}"})

        items = [PathsV2Item(event=item["event"], label=item["label"]) for item in request.validated_data["items"]]
        anchor = query.pathsV2Filter.anchor if query.pathsV2Filter else None

        try:
            if anchor is None:
                if len(items) != 2:
                    raise ValidationError(
                        {"items": "In open mode only a single edge has an exact funnel; send exactly two items."}
                    )
                funnels_query = edge_to_funnels_query(query, self.team, items[0], items[1])
            else:
                if not self._starts_at_anchor(query, items[0], anchor.item):
                    raise ValidationError(
                        {"items": "An anchored segment has an exact funnel only when it starts at the anchor."}
                    )
                # End-anchored chains are displayed anchor-first, i.e. backward in time;
                # the funnel wants forward-time order.
                ordered = list(reversed(items)) if anchor.type == PathsV2AnchorType.END else items
                funnels_query = anchored_segment_to_funnels_query(query, self.team, list(ordered))
        except ValueError as error:
            raise ValidationError({"items": str(error)})

        return Response({"funnels_query": funnels_query.model_dump(exclude_none=True)})

    @staticmethod
    def _starts_at_anchor(query: PathsV2Query, first: PathsV2Item, anchor_item: PathsV2Item) -> bool:
        """Compare `(event, label)` identities the way the converter does — `item_label` normalizes
        a missing label to "" for sources without a naming property — so the guard cannot diverge
        from the converter over a null-vs-empty label."""
        if first.event != anchor_item.event:
            return False
        source = step_source_for_event(resolve_step_sources(query), anchor_item.event)
        return item_label(first, source) == item_label(anchor_item, source)
