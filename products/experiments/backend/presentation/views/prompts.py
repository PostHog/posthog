"""Actions for experiments that compare versions of an LLM prompt."""

import json
from typing import Any

from django.utils.text import slugify

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.llm_metric_templates import build_template, list_templates
from products.experiments.backend.presentation.serializers.experiment_crud import ExperimentSerializer
from products.experiments.backend.presentation.serializers.prompts import CreateFromPromptInputSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _build_prompt_variants(versions: list[int]) -> list[dict[str, Any]]:
    """Build N feature flag variants from an ordered list of prompt versions.

    First variant is keyed "control", matching the codebase's baseline convention (the
    baseline defaults to 'control' when present). For the standard 2-variant case the
    second is keyed "test", matching the rest of the codebase's defaults. For N >= 3 the
    trailing variants are keyed "test-1", "test-2", … so each key stays unique.
    The human-readable prompt version goes in the variant name so chart legends stay readable.
    Splits are integers summing to 100; the last variant absorbs any remainder.
    """
    n = len(versions)
    base = 100 // n
    splits = [base] * n
    splits[-1] += 100 - base * n
    variants: list[dict[str, Any]] = []
    for i, (version, split) in enumerate(zip(versions, splits)):
        if i == 0:
            key = "control"
        elif n == 2:
            key = "test"
        else:
            key = f"test-{i}"
        variants.append({"key": key, "name": f"v{version}", "rollout_percentage": split})
    return variants


def _slugify_feature_flag_key(name: str, *, team_id: int) -> str:
    """Slugify a feature flag name, adding a numeric suffix if the slug already exists for this team."""
    base = slugify(name)[:200] or "experiment"
    candidate = base
    suffix = 2
    while FeatureFlag.objects.filter(team_id=team_id, key=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


class ExperimentPromptsMixin(TeamAndOrgViewSetMixin):
    @extend_schema(
        request=CreateFromPromptInputSerializer,
        responses=ExperimentSerializer,
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="create_from_prompt",
        # Endpoint reads an LLMPrompt's name + versions to validate input, so the caller
        # needs prompt-read scope in addition to experiment-write. Without llm_prompt:read,
        # a token with experiment:write alone could enumerate existing prompts by guessing
        # names.
        required_scopes=["experiment:write", "llm_prompt:read"],
    )
    def create_from_prompt(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Create an experiment that compares N versions of an LLM prompt using a metric template.

        The user picks 2+ versions of an existing LLMPrompt and 1+ metric templates
        (cost / latency / eval_pass_rate). The endpoint builds the matching variants
        (control + test-N, each named after its prompt version) and attaches one
        metric per selected template, each scoped to the prompt's $ai_prompt_name.
        Resulting experiment is in draft state.
        """
        # Scope checks alone don't cover resource-level access controls: this action runs on the
        # experiment viewset, so AccessControlPermission only verifies experiment access. Check
        # prompt access explicitly before validation queries LLMPrompt and leaks which names exist.
        if not self.user_access_control.check_access_level_for_resource("llm_prompt", required_level="viewer"):
            raise PermissionDenied("Creating an experiment from a prompt requires LLM analytics access.")

        serializer = CreateFromPromptInputSerializer(data=request.data, context={"team": self.team})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        prompt_name: str = data["prompt_name"]
        versions: list[int] = data["versions"]
        templates: list[str] = data["templates"]
        versions_label = ", ".join(f"v{v}" for v in versions)
        templates_label = ", ".join(templates)
        name = data.get("name") or f"{prompt_name}: {versions_label} ({templates_label})"
        feature_flag_key = data.get("feature_flag_key") or _slugify_feature_flag_key(name, team_id=self.team.id)

        metrics: list[dict[str, Any]] = []
        for template in templates:
            metric_dict = build_template(template, prompt_name).model_dump(exclude_none=True)
            metric_dict.setdefault("kind", "ExperimentMetric")
            metrics.append(metric_dict)

        variants = _build_prompt_variants(versions)
        # Encode (prompt_name, prompt_version) as a JSON payload per variant so the SDK can
        # read it via flags.get_flag_payload(...) instead of hard-coding a variant→version map.
        feature_flag_payloads = {
            variant["key"]: json.dumps({"prompt_name": prompt_name, "prompt_version": version})
            for variant, version in zip(variants, versions)
        }

        service = ExperimentService(team=self.team, user=request.user)
        experiment = service.create_experiment(
            name=name,
            feature_flag_key=feature_flag_key,
            description=data.get("description", ""),
            parameters={
                "prompt_metadata": {
                    "name": prompt_name,
                    "templates": templates,
                    "versions": versions,
                },
            },
            feature_flag_config={
                "filters": {
                    "multivariate": {"variants": variants},
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": feature_flag_payloads,
                },
            },
            metrics=metrics,
            serializer_context=self.get_serializer_context(),
            allow_unknown_events=True,
        )

        return Response(
            ExperimentSerializer(experiment, context=self.get_serializer_context()).data,
            status=201,
        )

    @extend_schema(
        request=None,
        responses={
            200: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["key", "label", "description"],
                },
            }
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="prompt_templates",
        required_scopes=["experiment:read"],
    )
    def prompt_templates(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the LLM metric templates that can be passed to `create_from_prompt`."""
        return Response(list_templates())
