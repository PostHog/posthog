import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import TeamMemberStrictManagementPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from ..llm.client import Client
from ..llm.providers.azure_openai import (
    DEFAULT_API_VERSION,
    DISALLOWED_ENDPOINT_MESSAGE,
    error_field_for_validation_message,
    is_allowed_azure_endpoint,
)
from ..models.evaluation_config import EvaluationConfig
from ..models.evaluations import Evaluation
from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from .metrics import llma_track_latency
from .proxy import models_cache_key

logger = logging.getLogger(__name__)


def validate_provider_key(provider: str, api_key: str, **kwargs) -> tuple[str, str | None]:
    """Validate an API key for any supported provider using the unified client."""
    try:
        return Client.validate_key(provider, api_key, **kwargs)
    except Exception:
        logger.exception(f"Provider key validation failed for provider '{provider}'")
        return (LLMProviderKey.State.ERROR, "Validation failed, please try again")


def _validation_error_field(provider: str, error_message: str | None) -> str:
    """Pick the serializer field to attach a validation error to.

    Defaults to `api_key` — most providers only validate the key itself. Azure OpenAI may fail
    because of endpoint issues (unreachable, wrong domain, 404), in which case the error is
    attributed to `azure_endpoint` so the UI can highlight the right input.
    """
    if provider == LLMProvider.AZURE_OPENAI:
        return error_field_for_validation_message(error_message) or "api_key"
    return "api_key"


class LLMProviderKeySerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False)
    api_key_masked = serializers.SerializerMethodField()
    azure_endpoint = serializers.URLField(write_only=True, required=False, help_text="Azure OpenAI endpoint URL")
    api_version = serializers.CharField(
        write_only=True, required=False, max_length=20, help_text="Azure OpenAI API version"
    )
    azure_endpoint_display = serializers.SerializerMethodField(help_text="Azure endpoint (read-only, for display)")
    api_version_display = serializers.SerializerMethodField(help_text="Azure API version (read-only, for display)")
    set_as_active = serializers.BooleanField(write_only=True, required=False, default=False)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = LLMProviderKey
        fields = [
            "id",
            "provider",
            "name",
            "state",
            "error_message",
            "api_key",
            "api_key_masked",
            "azure_endpoint",
            "api_version",
            "azure_endpoint_display",
            "api_version_display",
            "set_as_active",
            "created_at",
            "created_by",
            "last_used_at",
        ]
        read_only_fields = ["id", "state", "error_message", "created_at", "created_by", "last_used_at"]

    def get_api_key_masked(self, obj: LLMProviderKey) -> str:
        key = obj.encrypted_config.get("api_key", "")
        if len(key) > 8:
            return f"{key[:4]}...{key[-4:]}"
        return "****"

    def get_azure_endpoint_display(self, obj: LLMProviderKey) -> str | None:
        if obj.provider != LLMProvider.AZURE_OPENAI:
            return None
        return obj.encrypted_config.get("azure_endpoint")

    def get_api_version_display(self, obj: LLMProviderKey) -> str | None:
        if obj.provider != LLMProvider.AZURE_OPENAI:
            return None
        return obj.encrypted_config.get("api_version")

    def validate_api_key(self, value: str) -> str:
        provider = self.initial_data.get("provider", self.instance.provider if self.instance else LLMProvider.OPENAI)

        if provider == LLMProvider.OPENAI:
            if not value.startswith(("sk-", "sk-proj-")):
                raise serializers.ValidationError(
                    "Invalid OpenAI API key format. Key should start with 'sk-' or 'sk-proj-'."
                )
        elif provider == LLMProvider.ANTHROPIC:
            if not value.startswith("sk-ant-"):
                raise serializers.ValidationError("Invalid Anthropic API key format. Key should start with 'sk-ant-'.")
        # Azure, Gemini, OpenRouter, and Fireworks keys have no standard prefix, so no format validation needed

        return value

    def validate(self, data):
        if self.instance is None and "api_key" not in data:
            raise serializers.ValidationError({"api_key": "API key is required when creating a new provider key."})

        provider = data.get("provider", getattr(self.instance, "provider", None))
        if provider == LLMProvider.AZURE_OPENAI:
            has_endpoint = bool(data.get("azure_endpoint"))
            has_existing_endpoint = self.instance and self.instance.encrypted_config.get("azure_endpoint")
            if not has_endpoint and not has_existing_endpoint:
                raise serializers.ValidationError({"azure_endpoint": "Azure endpoint is required for Azure OpenAI."})

            # If an endpoint is being supplied (create or update), enforce the Azure-domain allowlist
            # here so the error is attributed to the azure_endpoint field rather than api_key.
            if has_endpoint and not is_allowed_azure_endpoint(data["azure_endpoint"]):
                raise serializers.ValidationError({"azure_endpoint": f"{DISALLOWED_ENDPOINT_MESSAGE}."})

        return data

    def _pop_azure_kwargs(self, validated_data: dict) -> dict:
        """Pop Azure-specific write-only fields out of ``validated_data`` and return them as kwargs.

        Mutates the input dict by removing ``azure_endpoint`` and ``api_version`` so that
        ``super().create()`` / ``super().update()`` don't try to set them on the model.
        """
        kwargs: dict = {}
        azure_endpoint = validated_data.pop("azure_endpoint", None)
        api_version = validated_data.pop("api_version", None)
        if azure_endpoint:
            kwargs["azure_endpoint"] = azure_endpoint
        if api_version:
            kwargs["api_version"] = api_version
        return kwargs

    def _normalize_azure_config(self, provider: str, azure_kwargs: dict) -> dict:
        """Persist the default api_version when an Azure endpoint is set without one.

        Keeps the stored config self-describing: the read path falls back to DEFAULT_API_VERSION
        when api_version is missing, which would retroactively change what a key points at
        if the default is ever bumped.
        """
        if (
            provider == LLMProvider.AZURE_OPENAI
            and azure_kwargs.get("azure_endpoint")
            and not azure_kwargs.get("api_version")
        ):
            return {**azure_kwargs, "api_version": DEFAULT_API_VERSION}
        return azure_kwargs

    def create(self, validated_data):
        api_key = validated_data.pop("api_key", None)
        set_as_active = validated_data.pop("set_as_active", False)
        azure_kwargs = self._pop_azure_kwargs(validated_data)
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = self.context["request"].user
        provider = validated_data.get("provider", LLMProvider.OPENAI)

        azure_kwargs = self._normalize_azure_config(provider, azure_kwargs)

        if api_key:
            state, error_message = validate_provider_key(provider, api_key, **azure_kwargs)
            if state != LLMProviderKey.State.OK:
                error_field = _validation_error_field(provider, error_message)
                raise serializers.ValidationError({error_field: error_message or "Key validation failed"})
            validated_data["encrypted_config"] = {"api_key": api_key, **azure_kwargs}
            validated_data["state"] = state
            validated_data["error_message"] = None

        instance = super().create(validated_data)

        if set_as_active and instance.state == LLMProviderKey.State.OK:
            config, _ = EvaluationConfig.objects.get_or_create(team=team)
            config.active_provider_key = instance
            config.save(update_fields=["active_provider_key", "updated_at"])

        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop("api_key", None)
        azure_kwargs = self._normalize_azure_config(instance.provider, self._pop_azure_kwargs(validated_data))

        if api_key:
            # Fall back to existing config for Azure fields not provided in the update.
            extra_kwargs = {**instance.provider_extra_kwargs(), **azure_kwargs}

            state, error_message = validate_provider_key(instance.provider, api_key, **extra_kwargs)
            if state != LLMProviderKey.State.OK:
                error_field = _validation_error_field(instance.provider, error_message)
                raise serializers.ValidationError({error_field: error_message or "Key validation failed"})
            encrypted_config: dict = {"api_key": api_key}
            if instance.provider == LLMProvider.AZURE_OPENAI:
                encrypted_config["azure_endpoint"] = extra_kwargs.get("azure_endpoint", "")
                encrypted_config["api_version"] = extra_kwargs.get("api_version", "")
            instance.encrypted_config = encrypted_config
            instance.state = state
            instance.error_message = None
        elif azure_kwargs and instance.provider == LLMProvider.AZURE_OPENAI:
            # Update Azure config fields without changing the API key. Endpoint or version
            # changes can invalidate the existing key (different Azure resource, different
            # SKU), so reset state to UNKNOWN — user must re-validate explicitly.
            config = dict(instance.encrypted_config)
            if "azure_endpoint" in azure_kwargs:
                config["azure_endpoint"] = azure_kwargs["azure_endpoint"]
            if "api_version" in azure_kwargs:
                config["api_version"] = azure_kwargs["api_version"]
            instance.encrypted_config = config
            instance.state = LLMProviderKey.State.UNKNOWN
            instance.error_message = None

        return super().update(instance, validated_data)


class LLMProviderKeyViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_provider_key"
    permission_classes = [TeamMemberStrictManagementPermission]
    serializer_class = LLMProviderKeySerializer
    queryset = LLMProviderKey.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[LLMProviderKey]) -> QuerySet[LLMProviderKey]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer):
        instance = serializer.save()
        report_user_action(
            self.request.user,
            "llma provider key created",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
            },
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.save()

        # Deployments are a property of the resource (azure_endpoint), not the key, so any
        # config change can shift the available model list. Drop the cached list so the next
        # picker request fetches fresh from the provider instead of serving stale entries.
        cache.delete(models_cache_key(instance.id))

        changed_fields = []
        if "name" in serializer.validated_data:
            changed_fields.append("name")
        if "api_key" in serializer.validated_data:
            changed_fields.append("api_key")

        if changed_fields:
            report_user_action(
                self.request.user,
                "llma provider key updated",
                {
                    "provider_key_id": str(instance.id),
                    "provider": instance.provider,
                    "changed_fields": changed_fields,
                },
                team=self.team,
                request=self.request,
            )

    def perform_destroy(self, instance):
        report_user_action(
            self.request.user,
            "llma provider key deleted",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
            },
            team=self.team,
            request=self.request,
        )
        instance.delete()

    @action(detail=True, methods=["post"])
    @llma_track_latency("llma_provider_keys_validate")
    @monitor(feature=None, endpoint="llma_provider_keys_validate", method="POST")
    def validate(self, request: Request, **_kwargs) -> Response:
        instance = self.get_object()
        api_key = instance.encrypted_config.get("api_key")

        if not api_key:
            return Response(
                {"detail": "No API key configured for this provider key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        state, error_message = validate_provider_key(instance.provider, api_key, **instance.provider_extra_kwargs())
        instance.state = state
        instance.error_message = error_message
        instance.save(update_fields=["state", "error_message"])

        report_user_action(
            request.user,
            "llma provider key validated",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
                "state": instance.state,
            },
            team=self.team,
            request=self.request,
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @llma_track_latency("llma_provider_keys_list")
    @monitor(feature=None, endpoint="llma_provider_keys_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @llma_track_latency("llma_provider_keys_retrieve")
    @monitor(feature=None, endpoint="llma_provider_keys_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @llma_track_latency("llma_provider_keys_create")
    @monitor(feature=None, endpoint="llma_provider_keys_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @llma_track_latency("llma_provider_keys_update")
    @monitor(feature=None, endpoint="llma_provider_keys_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @llma_track_latency("llma_provider_keys_partial_update")
    @monitor(feature=None, endpoint="llma_provider_keys_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    @llma_track_latency("llma_provider_keys_dependent_configs")
    @monitor(feature=None, endpoint="llma_provider_keys_dependent_configs", method="GET")
    def dependent_configs(self, request: Request, **_kwargs) -> Response:
        """Get evaluations using this key and alternative keys for replacement."""
        instance = self.get_object()

        model_configs = LLMModelConfiguration.objects.filter(provider_key=instance).prefetch_related("evaluations")

        evaluations = []
        for config in model_configs:
            for evaluation in config.evaluations.filter(deleted=False):
                evaluations.append(
                    {
                        "id": str(evaluation.id),
                        "name": evaluation.name,
                        "model_configuration_id": str(config.id),
                    }
                )

        alternative_keys = LLMProviderKey.objects.filter(
            team_id=self.team_id,
            provider=instance.provider,
            state=LLMProviderKey.State.OK,
        ).exclude(id=instance.id)

        return Response(
            {
                "evaluations": evaluations,
                "alternative_keys": [
                    {"id": str(key.id), "name": key.name, "provider": key.provider} for key in alternative_keys
                ],
            }
        )

    @action(detail=False, methods=["get"])
    @llma_track_latency("llma_provider_keys_trial_evaluations")
    @monitor(feature=None, endpoint="llma_provider_keys_trial_evaluations", method="GET")
    def trial_evaluations(self, request: Request, **_kwargs) -> Response:
        """List enabled evaluations currently using trial credits for a given provider."""
        provider = request.query_params.get("provider")
        if not provider:
            return Response({"detail": "provider query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
        if provider not in [choice[0] for choice in LLMProvider.choices]:
            return Response({"detail": f"Unsupported provider: {provider}"}, status=status.HTTP_400_BAD_REQUEST)

        # Evaluations on trial: model_configuration has matching provider but no pinned key
        trial_filter = Q(
            model_configuration__provider=provider,
            model_configuration__provider_key__isnull=True,
        )
        # Legacy evaluations (no model_configuration) default to OpenAI
        if provider == "openai":
            trial_filter |= Q(model_configuration__isnull=True)

        trial_evals = Evaluation.objects.filter(trial_filter, team_id=self.team_id, deleted=False).values(
            "id", "name", "enabled"
        )[:50]

        return Response({"evaluations": list(trial_evals)})

    @action(detail=True, methods=["post"])
    @llma_track_latency("llma_provider_keys_assign")
    @monitor(feature=None, endpoint="llma_provider_keys_assign", method="POST")
    def assign(self, request: Request, **_kwargs) -> Response:
        """Assign this key to evaluations and optionally re-enable them."""
        instance = self.get_object()
        evaluation_ids = request.data.get("evaluation_ids", [])
        enable = request.data.get("enable", False)

        if not evaluation_ids:
            return Response({"detail": "evaluation_ids is required"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Update model configurations to use this key
            configs_updated = LLMModelConfiguration.objects.filter(
                evaluations__id__in=evaluation_ids,
                evaluations__team_id=self.team_id,
                evaluations__deleted=False,
                provider=instance.provider,
            ).update(provider_key=instance)

            # Handle legacy evaluations (no model_configuration) — these are always
            # OpenAI, so only create a config if the key matches.
            if instance.provider == "openai":
                legacy_evals = Evaluation.objects.filter(
                    id__in=evaluation_ids,
                    team_id=self.team_id,
                    model_configuration__isnull=True,
                    deleted=False,
                )
                for eval_obj in legacy_evals:
                    mc = LLMModelConfiguration.objects.create(
                        team_id=self.team_id,
                        provider="openai",
                        model="gpt-5-mini",
                        provider_key=instance,
                    )
                    eval_obj.model_configuration = mc
                    eval_obj.save(update_fields=["model_configuration"])
                    configs_updated += 1

            # A key assignment resolves any `provider_key_deleted` / `model_not_allowed` error on the
            # dependent evals — the cause no longer applies once they're attached to a live key. Clear
            # the error-reason marker regardless of whether the caller also asked to re-enable.
            # `.update()` bypasses the model's invariant coercion in save(), so write the full trio.
            Evaluation.objects.filter(
                id__in=evaluation_ids,
                team_id=self.team_id,
                deleted=False,
                status="error",
            ).update(enabled=False, status="paused", status_reason=None)

            evals_enabled = 0
            if enable:
                # Re-enabling via key assignment: transition paused-or-just-cleared evals to ACTIVE.
                evals_enabled = Evaluation.objects.filter(
                    id__in=evaluation_ids,
                    team_id=self.team_id,
                    deleted=False,
                    enabled=False,
                ).update(enabled=True, status="active", status_reason=None)

        report_user_action(
            request.user,
            "llma provider key assigned to evaluations",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
                "evaluation_ids": [str(eid) for eid in evaluation_ids],
                "configs_updated": configs_updated,
                "evals_enabled": evals_enabled,
            },
            team=self.team,
            request=self.request,
        )

        return Response({"configs_updated": configs_updated, "evals_enabled": evals_enabled})

    @llma_track_latency("llma_provider_keys_destroy")
    @monitor(feature=None, endpoint="llma_provider_keys_destroy", method="DELETE")
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        replacement_key_id = request.query_params.get("replacement_key_id")

        if replacement_key_id:
            try:
                replacement_key = LLMProviderKey.objects.get(id=replacement_key_id, team_id=self.team_id)
            except LLMProviderKey.DoesNotExist:
                return Response({"detail": "Replacement key not found"}, status=status.HTTP_400_BAD_REQUEST)

            if replacement_key.provider != instance.provider:
                return Response(
                    {"detail": "Replacement key must be from the same provider"}, status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                LLMModelConfiguration.objects.filter(provider_key=instance, team_id=self.team_id).update(
                    provider_key=replacement_key
                )
                return super().destroy(request, *args, **kwargs)
        else:
            model_config_ids = list(
                LLMModelConfiguration.objects.filter(provider_key=instance, team_id=self.team_id).values_list(
                    "id", flat=True
                )
            )
            with transaction.atomic():
                # Deleting the key leaves dependent evals unrunnable. Only promote currently-active
                # evals to the error state — user-paused evals should stay paused (the user's intent
                # is preserved), and already-errored evals don't need their existing reason overwritten.
                Evaluation.objects.filter(
                    model_configuration_id__in=model_config_ids,
                    team_id=self.team_id,
                    deleted=False,
                    status="active",
                ).update(enabled=False, status="error", status_reason="provider_key_deleted")
                return super().destroy(request, *args, **kwargs)


class LLMProviderKeyValidationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Validate LLM provider API keys without persisting them"""

    scope_object = "llm_provider_key"
    serializer_class = _FallbackSerializer
    permission_classes = [TeamMemberStrictManagementPermission]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @llma_track_latency("llma_provider_key_validations_create")
    @monitor(feature=None, endpoint="llma_provider_key_validations_create", method="POST")
    def create(self, request: Request, **_kwargs) -> Response:
        api_key = request.data.get("api_key")
        provider = request.data.get("provider", LLMProvider.OPENAI)

        if not api_key:
            return Response(
                {"detail": "API key is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if provider not in [choice[0] for choice in LLMProvider.choices]:
            return Response(
                {"detail": f"Invalid provider. Must be one of: {', '.join([c[0] for c in LLMProvider.choices])}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra_kwargs = {}
        if provider == LLMProvider.AZURE_OPENAI:
            azure_endpoint = request.data.get("azure_endpoint")
            api_version = request.data.get("api_version")
            if azure_endpoint:
                extra_kwargs["azure_endpoint"] = azure_endpoint
            if api_version:
                extra_kwargs["api_version"] = api_version

        state, error_message = validate_provider_key(provider, api_key, **extra_kwargs)
        error_field = (
            error_field_for_validation_message(error_message) if provider == LLMProvider.AZURE_OPENAI else None
        )
        return Response({"state": state, "error_message": error_message, "error_field": error_field})
