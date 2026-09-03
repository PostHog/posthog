"""Staff-only DRF API for the enrichment "AI enrichment": list labels, list a label's prompt
config versions, create a new immutable version, test-run a draft config against recent
archived orgs, and flip which version is active.

Shaped around config version + input rows + verdict rows, not around enrichment orgs, so the
same contract can host a future team-scoped customer-facing product without a rewrite. save/run
reuse the classification runner in products.growth.backend.enrichment.lab - the same module the
batch runner is built on - so a test run and a shadow run can never drift on how a verdict is
computed.

Serializers live in ai_enrichment_serializers.py.
"""

import re
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http.response import HttpResponseBase

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import renderers, request, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.streaming import streaming_response
from posthog.api.utils import ErrorResponseSerializer
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.llm.gateway_client import get_llm_client
from posthog.models import User
from posthog.permissions import IsStaffUser
from posthog.renderers import SafeJSONRenderer

from products.growth.backend.api.ai_enrichment_serializers import (
    ActivateRequestSerializer,
    ConfigListResponseSerializer,
    ConfigsQuerySerializer,
    ConfigVersionSerializer,
    GatewayModelListResponseSerializer,
    LabelListResponseSerializer,
    RunRequestSerializer,
    SaveRequestSerializer,
)
from products.growth.backend.enrichment.lab import (
    DRAFT_VERSION_SENTINEL,
    MAX_SAMPLE_SIZE,
    format_run_row,
    list_gateway_models,
    stream_run_classifications,
)
from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
    verdict_field_key,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

logger = structlog.get_logger(__name__)

# Server-assigned version identity. Matched anywhere in the string (not anchored), so a legacy
# hand-written version like "ai-pilled-clay-v1" still contributes its 1 - only a label with no
# v<n> pattern in any version at all falls back to the row count.
_VERSION_SUFFIX_RE = re.compile(r"v(\d+)")


def _next_version(label: str) -> str:
    """The label's next `v<n>`, from the highest `v<digits>` occurring anywhere in any existing
    version string for this label, plus one - not a row count, and not an anchored match.

    Counting recycles a version string after any row is removed, which would silently
    reattribute every verdict stamped with it to a prompt that never produced it. Falls back to
    one past the row count only when nothing on record has a v<n> pattern at all, since there's
    no numeric precedent to bump. Must be called inside a transaction: the row lock is what stops
    two concurrent saves picking the same n.
    """
    existing = list(EnrichmentPromptConfig.objects.select_for_update().filter(name=label))
    matches = [match for config in existing for match in _VERSION_SUFFIX_RE.finditer(config.version)]
    if matches:
        return f"v{max(int(match.group(1)) for match in matches) + 1}"
    return f"v{len(existing) + 1}"


def _build_run_inputs(sample: int) -> list[tuple[OrganizationEnrichmentFetch, str | None]]:
    """All the ORM work a run needs, done up front on the request thread: workers only make LLM
    calls (see stream_run_classifications), so no query runs mid-stream. Only orgs with AI
    processing consent are eligible - the same gate the batch runner and dry-run command apply
    per row (enrichment_label_batch.py, enrichment_label_dry_run.py via ai_processing_approved).
    This is a coarse first pass, not the last word: `=True` also excludes the nullable column's
    unset (NULL) state, matching ai_processing_approved's "only an explicit True approves", but a
    run can still stream for seconds to minutes, long enough for consent to be revoked after this
    filter runs - classify_fetch_for_run (enrichment/lab.py) rechecks per row immediately before
    each classification for that reason.
    """
    fetches = list(
        recent_latest_fetches_qs()
        .filter(organization__is_ai_data_processing_approved=True)
        .select_related("organization")[:sample]
    )
    return [(fetch, signup_domain_for_organization(fetch.organization)) for fetch in fetches]


class NDJSONRenderer(renderers.BaseRenderer):
    """Content-negotiation stand-in for the streamed run endpoint: the stream is built by
    the view itself, so render() only ever sees error payloads from exception handling.

    Declared on the `run` @action only (never renderer_classes on the whole viewset) - putting it
    viewset-wide previously broke drf-spectacular codegen for every other endpoint on this
    viewset.
    """

    media_type = "application/x-ndjson"
    format = "ndjson"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        return json.dumps(data).encode()


class AIEnrichmentRunThrottle(UserRateThrottle):
    """The global throttles are PersonalApiKeyRateThrottle subclasses, which pass straight through
    for a session-authenticated request with no personal API key - so this endpoint would otherwise
    have no limit at all. Each allowed call can cost up to MAX_SAMPLE_SIZE LLM completions."""

    scope = "ai_enrichment_run"
    rate = "10/min"


class AIEnrichmentViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped API for the enrichment AI enrichment: browse labels and their prompt
    config versions, test-run a draft config against recently archived orgs, save a new
    immutable version, and flip which version is active.

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

    @validated_request(responses={200: OpenApiResponse(response=GatewayModelListResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def models(self, request: request.Request, **kwargs: Any) -> response.Response:
        results = [{"id": model_id} for model_id in list_gateway_models()]
        return response.Response(GatewayModelListResponseSerializer({"results": results}).data)

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

    @extend_schema(
        request=RunRequestSerializer,
        responses={(200, "application/x-ndjson"): OpenApiTypes.STR},
        summary="Stream classifier verdicts for an unsaved draft config against recently archived orgs.",
        description="One JSON object per line: a {company, domain, inputs, outputs: {<key>: value, ...}, meta} row "
        "as each LLM call completes, keyed by the submitted output_fields, then a final "
        "{summary: {classified, unknown, errors}} line. A run that fails partway ends with "
        "{error, aborted: true} instead of a summary. Persists nothing - spends real LLM money, so sample is "
        f"capped at {MAX_SAMPLE_SIZE} and the endpoint is rate limited.",
    )
    @action(
        methods=["POST"],
        detail=False,
        throttle_classes=[AIEnrichmentRunThrottle],
        renderer_classes=[SafeJSONRenderer, NDJSONRenderer],
    )
    def run(self, request: request.Request, **kwargs: Any) -> HttpResponseBase:
        serializer = RunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Unsaved on purpose: the run classifies against whatever the caller submitted, nothing
        # is persisted, and DRAFT_VERSION_SENTINEL never collides with a real saved version
        # string - SaveRequestSerializer separately rejects it as a caller-supplied version.
        draft_config = EnrichmentPromptConfig(
            name=data["label"],
            version=DRAFT_VERSION_SENTINEL,
            prompt_text=data["prompt_text"],
            model=data["model"],
            input_fields=data["input_fields"],
            output_fields=data["output_fields"],
        )

        items = _build_run_inputs(data["sample"])
        # tenacity in labels.py already owns retries (classify_payload's _call_and_parse,
        # stop_after_attempt(3)); the SDK's own internal retries underneath would multiply that
        # budget several-fold per fetch and actively worsen a 429 the tenacity layer is already
        # backing off from.
        client = get_llm_client(product="growth").with_options(max_retries=0)

        logger.info(
            "growth_ai_enrichment_run",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            label=data["label"],
            model=data["model"],
            sample_requested=data["sample"],
            sample_matched=len(items),
        )

        verdict_key = verdict_field_key(draft_config)
        label = data["label"]

        # No ORM work happens inside the stream (items are prefetched above), so the
        # request-thread connections can be released before streaming starts.
        async def _stream() -> AsyncIterator[bytes]:
            classified = unknown = errors = 0
            try:
                async for company, domain, output, error, inputs in stream_run_classifications(
                    draft_config, items, client
                ):
                    if error is not None:
                        errors += 1
                    elif verdict_key is not None and output is not None and output.get(verdict_key) == UNKNOWN:
                        unknown += 1
                    else:
                        classified += 1
                    row = format_run_row(draft_config, company, domain, output, error, inputs)
                    yield (json.dumps(row) + "\n").encode()
            except Exception as e:
                # The response is already 200 with rows sent, so the only way to tell the client
                # apart from a completed run is a terminal line it can look for.
                capture_exception(e, {"label": label, "path": "ai_enrichment.run"})
                yield (json.dumps({"error": f"{type(e).__name__}: run failed", "aborted": True}) + "\n").encode()
                return
            logger.info(
                "growth_ai_enrichment_run_complete",
                label=label,
                model=draft_config.model,
                classified=classified,
                unknown=unknown,
                errors=errors,
            )
            summary = {"summary": {"classified": classified, "unknown": unknown, "errors": errors}}
            yield (json.dumps(summary) + "\n").encode()

        return streaming_response(_stream(), content_type="application/x-ndjson")

    @validated_request(
        request_serializer=SaveRequestSerializer,
        responses={
            201: OpenApiResponse(response=ConfigVersionSerializer),
            409: OpenApiResponse(
                response=ErrorResponseSerializer, description="A concurrent save took this version. Retry."
            ),
        },
    )
    @action(methods=["POST"], detail=False)
    def save(self, request: request.Request, **kwargs: Any) -> response.Response:
        data = request.validated_data
        label = data["label"]
        requested_version = data.get("version", "").strip()
        try:
            # IsAuthenticated + IsStaffUser guarantee a real User here.
            with transaction.atomic():
                # Only the server-suggestion path needs the row lock (it reads sibling versions
                # to pick the next one) - a caller-supplied version relies on the unique
                # constraint alone and needs no lock.
                version = requested_version or _next_version(label)
                config = EnrichmentPromptConfig.objects.create(
                    name=label,
                    version=version,
                    prompt_text=data["prompt_text"],
                    model=data["model"],
                    input_fields=data["input_fields"],
                    output_fields=data["output_fields"],
                    is_active=False,
                    created_by=cast(User, request.user),
                )
        except IntegrityError:
            # A brand-new label has no rows for _next_version to lock, so two concurrent first
            # saves can both pick v1; a caller-supplied version can just as easily collide.
            # Retrying is the caller's move; this must not be a 500.
            raise Conflict("A version with this name already exists for this label. Try a different one.")

        logger.info(
            "growth_ai_enrichment_save",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            label=config.name,
            version=config.version,
        )

        serializer = ConfigVersionSerializer(config, context={"versions_with_results": set()})
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

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
