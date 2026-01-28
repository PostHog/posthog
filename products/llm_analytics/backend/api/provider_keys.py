from typing import cast

from django.db.models import QuerySet

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User

from ..llm.client import Client
from ..models.evaluation_config import EvaluationConfig
from ..models.provider_keys import LLMProvider, LLMProviderKey


def validate_provider_key(provider: str, api_key: str) -> tuple[str, str | None]:
    """Validate an API key for any supported provider using the unified client."""
    return Client.validate_key(provider, api_key)


class LLMProviderKeySerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False)
    api_key_masked = serializers.SerializerMethodField()
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

    def validate_api_key(self, value: str) -> str:
        provider = self.initial_data.get("provider", LLMProvider.OPENAI)

        if provider == LLMProvider.OPENAI:
            if not value.startswith(("sk-", "sk-proj-")):
                raise serializers.ValidationError(
                    "Invalid OpenAI API key format. Key should start with 'sk-' or 'sk-proj-'."
                )
        elif provider == LLMProvider.ANTHROPIC:
            if not value.startswith("sk-ant-"):
                raise serializers.ValidationError("Invalid Anthropic API key format. Key should start with 'sk-ant-'.")
        # Gemini keys have no standard prefix, so no format validation needed

        return value

    def validate(self, data):
        if self.instance is None and "api_key" not in data:
            raise serializers.ValidationError({"api_key": "API key is required when creating a new provider key."})
        return data

    def create(self, validated_data):
        api_key = validated_data.pop("api_key", None)
        set_as_active = validated_data.pop("set_as_active", False)
        team = self.context["get_team"]()
        validated_data["team"] = team
        validated_data["created_by"] = self.context["request"].user
        provider = validated_data.get("provider", LLMProvider.OPENAI)

        if api_key:
            state, error_message = validate_provider_key(provider, api_key)
            if state != LLMProviderKey.State.OK:
                raise serializers.ValidationError({"api_key": error_message or "Key validation failed"})
            validated_data["encrypted_config"] = {"api_key": api_key}
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

        if api_key:
            state, error_message = validate_provider_key(instance.provider, api_key)
            if state != LLMProviderKey.State.OK:
                raise serializers.ValidationError({"api_key": error_message or "Key validation failed"})
            instance.encrypted_config = {"api_key": api_key}
            instance.state = state
            instance.error_message = None

        return super().update(instance, validated_data)


class LLMProviderKeyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "llm_provider_key"
    permission_classes = [IsAuthenticated]
    serializer_class = LLMProviderKeySerializer
    queryset = LLMProviderKey.objects.all()

    def safely_get_queryset(self, queryset: QuerySet[LLMProviderKey]) -> QuerySet[LLMProviderKey]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer):
        instance = serializer.save()
        report_user_action(
            cast(User, self.request.user),
            "llma provider key created",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
            },
            self.team,
        )

    def perform_update(self, serializer):
        instance = serializer.save()

        changed_fields = []
        if "name" in serializer.validated_data:
            changed_fields.append("name")
        if "api_key" in serializer.validated_data:
            changed_fields.append("api_key")

        if changed_fields:
            report_user_action(
                cast(User, self.request.user),
                "llma provider key updated",
                {
                    "provider_key_id": str(instance.id),
                    "provider": instance.provider,
                    "changed_fields": changed_fields,
                },
                self.team,
            )

    def perform_destroy(self, instance):
        report_user_action(
            cast(User, self.request.user),
            "llma provider key deleted",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
            },
            self.team,
        )
        instance.delete()

    @action(detail=True, methods=["post"])
    @monitor(feature=None, endpoint="llma_provider_keys_validate", method="POST")
    def validate(self, request: Request, **_kwargs) -> Response:
        instance = self.get_object()
        api_key = instance.encrypted_config.get("api_key")

        if not api_key:
            return Response(
                {"detail": "No API key configured for this provider key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        state, error_message = validate_provider_key(instance.provider, api_key)
        instance.state = state
        instance.error_message = error_message
        instance.save(update_fields=["state", "error_message"])

        report_user_action(
            cast(User, request.user),
            "llma provider key validated",
            {
                "provider_key_id": str(instance.id),
                "provider": instance.provider,
                "state": instance.state,
            },
            self.team,
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @monitor(feature=None, endpoint="llma_provider_keys_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_provider_keys_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_provider_keys_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_provider_keys_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_provider_keys_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_provider_keys_destroy", method="DELETE")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


class LLMProviderKeyValidationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Validate LLM provider API keys without persisting them"""

    scope_object = "llm_provider_key"
    permission_classes = [IsAuthenticated]

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

        state, error_message = validate_provider_key(provider, api_key)
        return Response({"state": state, "error_message": error_message})
