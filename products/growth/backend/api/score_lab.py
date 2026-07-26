"""Staff-only DRF API for the enrichment "score lab": list labels, list a label's prompt
config versions, dry-run a draft config against recent archived orgs, save a new immutable
version, and flip which version is active.

Shaped around config version + input rows + verdict rows, not around enrichment orgs, so the
same contract can host a future team-scoped customer-facing product without a rewrite. Reuses
the classification runner in products.growth.backend.enrichment.lab - the same module the
admin lab UI (products/growth/backend/admin.py) is built on - so the two surfaces can never
drift on how a verdict is computed.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.http.response import HttpResponseBase

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import renderers, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.streaming import streaming_response
from posthog.api.utils import ErrorResponseSerializer
from posthog.helpers.impersonation import is_impersonated
from posthog.llm.gateway_client import get_llm_client
from posthog.permissions import IsStaffUser

from products.growth.backend.enrichment.input_query import InputQueryError, parse_input_query, run_input_query
from products.growth.backend.enrichment.lab import (
    DEFAULT_SAMPLE_SIZE,
    GATEWAY_MODEL_CHOICES,
    LABEL_SLUG_RE,
    MAX_SAMPLE_SIZE,
    RunClassifyFn,
    classify_fetch_for_run,
    classify_row_for_run,
    format_run_row,
    list_gateway_models,
    stream_run_classifications,
)
from products.growth.backend.enrichment.labels import (
    OUTPUT_FIELD_KEY_RE,
    OUTPUT_FIELD_TYPES,
    RESERVED_OUTPUT_FIELD_KEYS,
    UNKNOWN,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
    verdict_field_key,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig

logger = structlog.get_logger(__name__)


_OUTPUT_FIELDS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Output key, e.g. ai_pilled. Must match ^[a-z][a-z0-9_]*$, be unique, and not "
                "be 'meta' or 'inputs' (reserved for provenance).",
            },
            "type": {
                "type": "string",
                "enum": list(OUTPUT_FIELD_TYPES),
                "description": "Value type the LLM must return for this key.",
            },
            "description": {
                "type": "string",
                "description": "Shown to the LLM to describe what this key means. Optional.",
            },
        },
        "required": ["key", "type"],
    },
}


@extend_schema_field(_OUTPUT_FIELDS_SCHEMA)
class OutputFieldsField(serializers.JSONField):
    pass


def _validate_output_fields(value: Any) -> list[dict[str, str]]:
    """Shared by RunRequestSerializer and SaveRequestSerializer - a plain function (not a mixin
    validate_output_fields) so both can call it with the same error shape from validate()."""
    if not value:
        return []
    if not isinstance(value, list):
        raise serializers.ValidationError("output_fields must be a list of {key, type, description} objects.")
    seen_keys: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise serializers.ValidationError("Each output field must be an object with key/type/description.")
        key = item.get("key")
        field_type = item.get("type")
        if not isinstance(key, str) or not OUTPUT_FIELD_KEY_RE.match(key):
            raise serializers.ValidationError(
                f"{key!r} is not a valid output field key (lowercase, starts with a letter, "
                "letters/digits/underscore only)."
            )
        if key in RESERVED_OUTPUT_FIELD_KEYS:
            raise serializers.ValidationError(f"{key!r} is a reserved key and cannot be used as an output field.")
        if key in seen_keys:
            raise serializers.ValidationError(f"Duplicate output field key {key!r}.")
        if field_type not in OUTPUT_FIELD_TYPES:
            raise serializers.ValidationError(
                f"{field_type!r} is not a valid output field type (must be one of {', '.join(OUTPUT_FIELD_TYPES)})."
            )
        seen_keys.add(key)
        cleaned.append({"key": key, "type": field_type, "description": str(item.get("description") or "")})
    return cleaned


def _validate_input_query(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parse_input_query(value)
    except InputQueryError as e:
        raise serializers.ValidationError(str(e))
    return value


def _valid_models_for_label(label: str) -> set[str]:
    """A model is acceptable on run/save if it's curated, gateway-listed right now, or already
    persisted on some version of this label (a legacy model the gateway later dropped must stay
    runnable for whichever version already used it)."""
    persisted = set(EnrichmentPromptConfig.objects.filter(name=label).values_list("model", flat=True))
    return persisted | set(GATEWAY_MODEL_CHOICES) | set(list_gateway_models())


class LabelSummarySerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label name computed by one or more prompt config versions.")
    version_count = serializers.IntegerField(help_text="Number of prompt config versions saved for this label.")
    active_version = serializers.CharField(
        allow_null=True, help_text="Version string the batch runner currently computes for this label, or null."
    )


@extend_schema_serializer(many=False)
class LabelListResponseSerializer(serializers.Serializer):
    results = LabelSummarySerializer(many=True, help_text="Distinct labels, alphabetical.")


class GatewayModelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Gateway model id, usable as `model` on run/save.")


@extend_schema_serializer(many=False)
class GatewayModelListResponseSerializer(serializers.Serializer):
    results = GatewayModelSerializer(
        many=True,
        help_text="Models the gateway currently lists (cached for 5 minutes), or the curated "
        "fallback list if the gateway is unreachable.",
    )


class ConfigVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Prompt config row id.")
    name = serializers.CharField(help_text="Label this config computes, e.g. ai_pilled.")
    version = serializers.CharField(help_text="Human-readable classifier version, e.g. ai-pilled-clay-v1.")
    prompt_text = serializers.CharField(
        help_text="System prompt; {email} is replaced with the signup email domain at runtime."
    )
    model = serializers.CharField(help_text="Gateway model id this version was authored against.")
    input_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. "
        "Ignored when input_query is set.",
    )
    input_query = serializers.CharField(
        allow_null=True,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. Null when "
        "input_fields is used instead. Each result row becomes one classification input; a 'company' or "
        "'domain' column (if present) is used for display, and every column is passed to the prompt as the "
        "Company data JSON keyed by column name.",
    )
    output_fields = OutputFieldsField(
        help_text="Configurable output schema: list of {key, type, description}. type is 'boolean', 'number', "
        "or 'string'. Empty (the default) means the legacy output shape "
        "({<name>: boolean, confidence: number 0-1, reasoning: string})."
    )
    is_active = serializers.BooleanField(help_text="Whether the batch runner currently computes this version.")
    created_by_email = serializers.SerializerMethodField(
        help_text="Email of the staff user who created this version, or null for system-seeded rows."
    )
    created_at = serializers.DateTimeField(help_text="When this version was created.")
    has_results = serializers.SerializerMethodField(
        help_text="Whether any EnrichmentLabelResult rows reference this version. Once true the version is "
        "frozen - prompt_text, model, input_fields, input_query, and output_fields can never change "
        "(FROZEN_FIELDS immutability)."
    )

    @extend_schema_field(serializers.EmailField(allow_null=True))
    def get_created_by_email(self, obj: EnrichmentPromptConfig) -> str | None:
        return obj.created_by.email if obj.created_by_id else None

    @extend_schema_field(serializers.BooleanField())
    def get_has_results(self, obj: EnrichmentPromptConfig) -> bool:
        return obj.version in self.context.get("versions_with_results", set())


@extend_schema_serializer(many=False)
class ConfigListResponseSerializer(serializers.Serializer):
    results = ConfigVersionSerializer(many=True, help_text="Versions for the requested label, newest first.")


class ConfigsQuerySerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label name to list prompt config versions for.")


class RunRequestSerializer(serializers.Serializer):
    label = serializers.CharField(
        max_length=128,
        help_text="Label this config computes, e.g. ai_pilled. Need not already exist - run classifies "
        "against an in-memory config only and persists nothing.",
    )
    prompt_text = serializers.CharField(
        help_text="System prompt; {email} is replaced with the signup email domain at runtime."
    )
    model = serializers.CharField(
        max_length=128,
        help_text="Gateway model to classify with, routed through the LLM gateway. Must be a curated model "
        "(see GET /models/), a model the gateway currently lists, or one already persisted on this label.",
    )
    input_fields = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. "
        "Ignored when input_query is set.",
    )
    input_query = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. When set, rows "
        "are built from this query (capped at `sample` rows) instead of recently archived orgs; 'contains' is "
        "ignored. Parsed and validated on submit but never executed until /run/ actually runs.",
    )
    output_fields = OutputFieldsField(
        required=False,
        default=list,  # type: ignore[arg-type]  # drf-stubs types JSONField.default as Mapping-only
        help_text="Configurable output schema: list of {key, type, description}. type is 'boolean', 'number', "
        "or 'string'. Empty (the default) means the legacy output shape "
        "({<label>: boolean, confidence: number 0-1, reasoning: string}). Keys must match ^[a-z][a-z0-9_]*$, "
        "be unique, and not be 'meta' or 'inputs'.",
    )
    sample = serializers.IntegerField(
        required=False,
        default=DEFAULT_SAMPLE_SIZE,
        min_value=1,
        max_value=MAX_SAMPLE_SIZE,
        help_text=f"Number of rows to classify (1-{MAX_SAMPLE_SIZE}): recent archived orgs, or HogQL query rows "
        "when input_query is set. Each sampled row costs one LLM call, so keep this bounded during iteration.",
    )
    contains = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Optional case-insensitive substring filter on the archived company or organization name. "
        "Ignored when input_query is set.",
    )

    def validate_input_query(self, value: str | None) -> str | None:
        return _validate_input_query(value)

    def validate_output_fields(self, value: Any) -> list[dict[str, str]]:
        return _validate_output_fields(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        model = attrs["model"]
        if model not in _valid_models_for_label(attrs["label"]):
            raise serializers.ValidationError({"model": f"{model!r} is not a valid gateway model."})
        return attrs


class SaveRequestSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=128, help_text="Label this config computes, e.g. ai_pilled.")
    version = serializers.CharField(
        max_length=128,
        help_text="Human-readable classifier version, e.g. ai-pilled-clay-v2. Must be unique per label.",
    )
    prompt_text = serializers.CharField(
        help_text="System prompt; {email} is replaced with the signup email domain at runtime."
    )
    model = serializers.CharField(
        max_length=128,
        help_text="Gateway model to classify with, routed through the LLM gateway. Must be a curated model "
        "(see GET /models/), a model the gateway currently lists, or one already persisted on this label.",
    )
    input_fields = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Dotted paths into the archived Harmonic payload fed to the prompt, e.g. funding.fundingStage. "
        "Ignored when input_query is set.",
    )
    input_query = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="HogQL SELECT defining classifier input rows, an alternative to input_fields. Parsed and "
        "validated on save but never executed - execution only happens on /run/.",
    )
    output_fields = OutputFieldsField(
        required=False,
        default=list,  # type: ignore[arg-type]  # drf-stubs types JSONField.default as Mapping-only
        help_text="Configurable output schema: list of {key, type, description}. type is 'boolean', 'number', "
        "or 'string'. Empty (the default) means the legacy output shape "
        "({<label>: boolean, confidence: number 0-1, reasoning: string}). Keys must match ^[a-z][a-z0-9_]*$, "
        "be unique, and not be 'meta' or 'inputs'.",
    )

    def validate_input_query(self, value: str | None) -> str | None:
        return _validate_input_query(value)

    def validate_output_fields(self, value: Any) -> list[dict[str, str]]:
        return _validate_output_fields(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        label = attrs["label"]
        version = attrs["version"]
        # This endpoint only ever creates rows (FROZEN_FIELDS immutability - see
        # EnrichmentPromptConfig docstring): an existing (label, version) pair is always
        # rejected, never updated in place.
        if EnrichmentPromptConfig.objects.filter(name=label, version=version).exists():
            raise serializers.ValidationError({"version": f"Version {version!r} already exists for {label!r}."})
        is_new_label = not EnrichmentPromptConfig.objects.filter(name=label).exists()
        if is_new_label and not LABEL_SLUG_RE.match(label):
            raise serializers.ValidationError(
                {
                    "label": f"{label!r} is not a valid label slug (lowercase, starts with a letter, "
                    "letters/digits/underscore only)."
                }
            )
        model = attrs["model"]
        if model not in _valid_models_for_label(label):
            raise serializers.ValidationError({"model": f"{model!r} is not a valid gateway model."})
        return attrs


class ActivateRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Prompt config id to activate for its label.")


class NDJSONRenderer(renderers.BaseRenderer):
    """Content-negotiation stand-in for the streamed run endpoint: the stream is built by
    the view itself, so render() only ever sees error payloads from exception handling."""

    media_type = "application/x-ndjson"
    format = "ndjson"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        return json.dumps(data).encode()


class ScoreLabViewSet(viewsets.ViewSet):
    renderer_classes = [renderers.JSONRenderer, NDJSONRenderer]
    """
    Staff-only, unscoped API for the enrichment score lab: browse labels and their prompt
    config versions, dry-run a draft config against recently archived orgs, save a new
    immutable version, and flip which version is active.

    Supersedes the admin lab UI's read paths; run/save/activate share the same underlying
    machinery (products.growth.backend.enrichment.lab) as the admin dry-run action so both
    surfaces compute identical verdicts.

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
        summary="Stream classifier verdicts for an unsaved draft config against recent archived orgs or a "
        "HogQL input query.",
        description="One JSON object per line: a verdict row as each LLM call completes, then a final "
        "{summary: {classified, unknown, errors}} line. A legacy config (no output_fields) emits "
        "{company, domain, verdict, confidence, reasoning} rows; a configurable output schema (output_fields "
        "set) emits {company, domain, outputs: {<key>: value, ...}} rows instead. When input_query is set, "
        "rows are built from that HogQL query (capped at `sample`) instead of recently archived orgs. "
        "Persists nothing - spends real LLM money, so sample is capped at "
        f"{MAX_SAMPLE_SIZE}.",
    )
    @action(methods=["POST"], detail=False)
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

        # All ORM/ClickHouse work happens here on the request thread; workers only make LLM
        # calls - see stream_run_classifications.
        items: list[Any]
        classify_one: RunClassifyFn
        if data["input_query"]:
            items = run_input_query(data["input_query"], data["sample"])
            classify_one = classify_row_for_run
            input_source = "query"
        else:
            candidates = recent_latest_fetches_qs()
            contains = data["contains"].strip()
            if contains:
                candidates = candidates.filter(
                    Q(payload__name__icontains=contains) | Q(organization__name__icontains=contains)
                )
            fetches = list(candidates.select_related("organization")[: data["sample"]])
            items = [(fetch, signup_domain_for_organization(fetch.organization)) for fetch in fetches]
            classify_one = classify_fetch_for_run
            input_source = "archived_fetch"

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

        # No ORM work happens inside the stream (items are prefetched above), so the
        # request-thread connections can be released before streaming starts.
        async def _stream() -> AsyncIterator[bytes]:
            classified = unknown = errors = 0
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
            summary = {"summary": {"classified": classified, "unknown": unknown, "errors": errors}}
            yield (json.dumps(summary) + "\n").encode()

        return streaming_response(_stream(), content_type="application/x-ndjson")

    @validated_request(
        request_serializer=SaveRequestSerializer,
        responses={201: OpenApiResponse(response=ConfigVersionSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def save(self, request: request.Request, **kwargs: Any) -> response.Response:
        data = request.validated_data
        # IsAuthenticated + IsStaffUser guarantee a real User here.
        config = EnrichmentPromptConfig.objects.create(
            name=data["label"],
            version=data["version"],
            prompt_text=data["prompt_text"],
            model=data["model"],
            input_fields=data["input_fields"],
            input_query=data["input_query"],
            output_fields=data["output_fields"],
            is_active=False,
            created_by=request.user,
        )

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
        config = EnrichmentPromptConfig.objects.filter(pk=config_id).first()
        if config is None:
            raise NotFound(f"Config {config_id} not found.")

        # Deactivate first, then activate: the partial unique constraint
        # growth_prompt_config_one_active only ever sees at most one active row per label.
        with transaction.atomic():
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
