from typing import cast

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User

from ..models.evaluation_config import EvaluationConfig
from ..models.provider_keys import LLMProviderKey
from .provider_keys import LLMProviderKeySerializer


class EvaluationConfigSerializer(serializers.ModelSerializer):
    trial_evals_remaining = serializers.IntegerField(read_only=True)
    active_provider_key = LLMProviderKeySerializer(read_only=True)

    class Meta:
        model = EvaluationConfig
        fields = [
            "trial_eval_limit",
            "trial_evals_used",
            "trial_evals_remaining",
            "active_provider_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "trial_evals_used",
            "trial_evals_remaining",
            "active_provider_key",
            "created_at",
            "updated_at",
        ]


class EvaluationConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-level evaluation configuration"""

    scope_object = "llm_provider_key"
    permission_classes = [IsAuthenticated]

    def list(self, request: Request, **kwargs) -> Response:
        """Get the evaluation config for this team"""
        config, _ = EvaluationConfig.objects.get_or_create(team_id=self.team_id)
        serializer = EvaluationConfigSerializer(config)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def set_active_key(self, request: Request, **kwargs) -> Response:
        """Set the active provider key for evaluations"""
        key_id = request.data.get("key_id")

        if not key_id:
            return Response(
                {"detail": "key_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            key = LLMProviderKey.objects.get(id=key_id, team_id=self.team_id)
        except LLMProviderKey.DoesNotExist:
            return Response(
                {"detail": "Key not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if key.state != LLMProviderKey.State.OK:
            return Response(
                {"detail": f"Cannot activate key with state '{key.state}'. Please validate the key first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config, _ = EvaluationConfig.objects.get_or_create(team_id=self.team_id)
        old_key = config.active_provider_key
        config.active_provider_key = key
        config.save(update_fields=["active_provider_key", "updated_at"])

        report_user_action(
            cast(User, request.user),
            "llma evaluation config active key set",
            {
                "key_id": str(key.id),
                "old_key_id": str(old_key.id) if old_key else None,
            },
            self.team,
        )

        serializer = EvaluationConfigSerializer(config)
        return Response(serializer.data)
