"""Staff-only DRF API for the enrichment "score lab": list labels, list a label's prompt
config versions, dry-run a draft config against recent archived orgs, save a new immutable
version, rename a label, and flip which version is active.

Shaped around config version + input rows + verdict rows, not around enrichment orgs, so the
same contract can host a future team-scoped customer-facing product without a rewrite. Reuses
the classification runner in products.growth.backend.enrichment.lab - the same module the batch
runner is built on - so a dry run and a shadow run can never drift on how a verdict is computed.

Serializers live in score_lab_serializers.py.
"""

import re
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http.response import HttpResponseBase

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import renderers, request, response, serializers, status, viewsets
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

from products.growth.backend.api.score_lab_serializers import (
    ActivateRequestSerializer,
    ConfigListResponseSerializer,
    ConfigsQuerySerializer,
    ConfigVersionSerializer,
    GatewayModelListResponseSerializer,
    InputFieldListResponseSerializer,
    LabelListResponseSerializer,
    RenameRequestSerializer,
    RunRequestSerializer,
    SaveRequestSerializer,
)
from products.growth.backend.enrichment.input_query import InputQueryError, run_input_query
from products.growth.backend.enrichment.lab import (
    HARMONIC_INPUT_FIELDS,
    MAX_SAMPLE_SIZE,
    RunClassifyFn,
    classify_fetch_for_run,
    classify_row_for_run,
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
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig

logger = structlog.get_logger(__name__)

# (items, how to classify one of them, source name for logging). The archived-fetch source
# yields (fetch, signup_domain) pairs, the HogQL source yields plain result rows.
RunInputs = tuple[list[Any], RunClassifyFn, str]

# Server-assigned version identity. Legacy hand-written versions (ai-pilled-clay-v1) don't match
# and are simply skipped when picking the next one.
_VERSION_SUFFIX_RE = re.compile(r"v(\d+)")


def _next_version(label: str) -> str:
    """The label's next `v<n>`, from the highest suffix already used rather than a row count.

    Counting recycles a version string after any row is removed, which would silently
    reattribute every verdict stamped with it to a prompt that never produced it. Must be called
    inside a transaction: the row lock is what stops two concurrent saves picking the same n.
    """
    existing = EnrichmentPromptConfig.objects.select_for_update().filter(name=label)
    highest = max(
        (int(match.group(1)) for config in existing if (match := _VERSION_SUFFIX_RE.fullmatch(config.version))),
        default=0,
    )
    return f"v{highest + 1}"


def _build_run_inputs(data: dict[str, Any]) -> RunInputs:
    """All the ORM/ClickHouse work a run needs, done up front on the request thread: workers
    only make LLM calls (see stream_run_classifications), so no query runs mid-stream."""
    if data["input_query"]:
        return run_input_query(data["input_query"], data["sample"]), classify_row_for_run, "query"

    candidates = recent_latest_fetches_qs()
    contains = data["contains"].strip()
    if contains:
        candidates = candidates.filter(Q(payload__name__icontains=contains) | Q(organization__name__icontains=contains))
    fetches = list(candidates.select_related("organization")[: data["sample"]])
    items = [(fetch, signup_domain_for_organization(fetch.organization)) for fetch in fetches]
    return items, classify_fetch_for_run, "archived_fetch"


class NDJSONRenderer(renderers.BaseRenderer):
    """Content-negotiation stand-in for the streamed run endpoint: the stream is built by
    the view itself, so render() only ever sees error payloads from exception handling."""

    media_type = "application/x-ndjson"
    format = "ndjson"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        return json.dumps(data).encode()


class ScoreLabRunThrottle(UserRateThrottle):
    """The global throttles are PersonalApiKeyRateThrottle subclasses, which pass straight through
    for a session-authenticated request with no personal API key - so this endpoint would otherwise
    have no limit at all. Each allowed call can cost up to MAX_SAMPLE_SIZE LLM completions."""

    scope = "score_lab_run"
    rate = "20/hour"


class ScoreLabViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
    config versions, dry-run a draft config against recently archived orgs, save a new
    immutable version, and flip which version is active.

    Backs the in-product score lab scene; run/save/activate share the classifier machinery
    in products.growth.backend.enrichment.lab with the batch runner, so a dry run and a
    shadow run compute identical verdicts.

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

    @validated_request(responses={200: OpenApiResponse(response=InputFieldListResponseSerializer)})
    @action(methods=["GET"], detail=False, url_path="input_fields")
    def input_fields(self, request: request.Request, **kwargs: Any) -> response.Response:
        return response.Response(InputFieldListResponseSerializer({"results": HARMONIC_INPUT_FIELDS}).data)

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
        summary="Stream classifier verdicts for an unsaved draft config against recent archived orgs or a "
        "HogQL input query.",
        description="One JSON object per line: a {company, domain, outputs: {<key>: value, ...}} row as each "
        "LLM call completes, keyed by the submitted output_fields, then a final "
        "{summary: {classified, unknown, errors}} line. A run that fails partway ends with "
        "{error, aborted: true} instead of a summary. When input_query is set, rows are built from that "
        "HogQL query (capped at `sample`) instead of recently archived orgs. Persists nothing - spends real "
        f"LLM money, so sample is capped at {MAX_SAMPLE_SIZE} and the endpoint is rate limited.",
    )
    @action(
        methods=["POST"],
        detail=False,
        throttle_classes=[ScoreLabRunThrottle],
        renderer_classes=[SafeJSONRenderer, NDJSONRenderer],
    )
    def run(self, request: request.Request, **kwargs: Any) -> HttpResponseBase:
        serializer = RunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Unsaved on purpose: the run classifies against whatever the caller submitted, nothing
        # is persisted, and "lab-draft" never collides with a real saved version string.
        draft_config = EnrichmentPromptConfig(
            name=data["label"],
            version="lab-draft",
            prompt_text=data["prompt_text"],
            model=data["model"],
            input_fields=data["input_fields"],
            input_query=data["input_query"],
            output_fields=data["output_fields"],
        )

        try:
            items, classify_one, input_source = _build_run_inputs(data)
        except InputQueryError as e:
            # A query can parse at save time and still fail to execute (unresolved placeholder,
            # unknown column). That's bad input from the query box, not a server fault.
            raise serializers.ValidationError({"input_query": str(e)})
        client = get_llm_client(product="growth")

        logger.info(
            "growth_score_lab_run",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            label=data["label"],
            model=data["model"],
            input_source=input_source,
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
                async for company, domain, output, error in stream_run_classifications(
                    draft_config, items, classify_one, client
                ):
                    if error is not None:
                        errors += 1
                    elif verdict_key is not None and output is not None and output.get(verdict_key) == UNKNOWN:
                        unknown += 1
                    else:
                        classified += 1
                    row = format_run_row(draft_config, company, domain, output, error)
                    yield (json.dumps(row) + "\n").encode()
            except Exception as e:
                # The response is already 200 with rows sent, so the only way to tell the client
                # apart from a completed run is a terminal line it can look for.
                capture_exception(e, {"label": label})
                yield (json.dumps({"error": f"{type(e).__name__}: run failed", "aborted": True}) + "\n").encode()
                return
            logger.info(
                "growth_score_lab_run_complete",
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
        try:
            # IsAuthenticated + IsStaffUser guarantee a real User here.
            with transaction.atomic():
                config = EnrichmentPromptConfig.objects.create(
                    name=data["label"],
                    version=_next_version(data["label"]),
                    prompt_text=data["prompt_text"],
                    model=data["model"],
                    input_fields=data["input_fields"],
                    input_query=data["input_query"],
                    output_fields=data["output_fields"],
                    is_active=False,
                    created_by=cast(User, request.user),
                )
        except IntegrityError:
            # A brand-new label has no rows for _next_version to lock, so two concurrent first
            # saves can both pick v1. Retrying is the caller's move; this must not be a 500.
            raise Conflict("Another save for this label landed first. Try again.")

        logger.info(
            "growth_score_lab_save",
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
            "growth_score_lab_activate",
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

    @validated_request(
        request_serializer=RenameRequestSerializer,
        responses={
            200: OpenApiResponse(response=ConfigVersionSerializer),
            404: OpenApiResponse(response=ErrorResponseSerializer, description="Config not found."),
        },
    )
    @action(methods=["POST"], detail=False)
    def rename(self, request: request.Request, **kwargs: Any) -> response.Response:
        """Rename a label. Purely cosmetic: the classifier's output contract is output_fields,
        so no stored verdict changes meaning and no config's content_hash moves."""
        data = request.validated_data
        config = EnrichmentPromptConfig.objects.filter(pk=data["config_id"]).first()
        if config is None:
            raise NotFound(f"Config {data['config_id']} not found.")

        new_label = data["label"]
        old_label = config.name
        with transaction.atomic():
            # A label is shared by all of its versions, and the batch runner looks work up by
            # label name, so every sibling moves too or the label silently splits in two.
            EnrichmentPromptConfig.objects.filter(name=old_label).update(name=new_label)
            EnrichmentLabelResult.objects.filter(label_name=old_label).update(label_name=new_label)

        config.refresh_from_db()
        logger.info(
            "growth_score_lab_rename",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            label=config.name,
        )
        has_results = EnrichmentLabelResult.objects.filter(
            label_name=config.name, prompt_version=config.version
        ).exists()
        serializer = ConfigVersionSerializer(
            config, context={"versions_with_results": {config.version} if has_results else set()}
        )
        return response.Response(serializer.data)
