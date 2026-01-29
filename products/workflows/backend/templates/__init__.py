import json
from pathlib import Path
from typing import Optional

import structlog
from rest_framework import serializers

logger = structlog.get_logger(__name__)

# List of all template JSON files - update this when adding new templates
TEMPLATE_FILES = [
    "announce_a_new_feature_template.json",
    "onboarding_started_but_not_completed_template.json",
    "trial_started_upgrade_nudge_template.json",
    "welcome_email_sequence_template.json",
]

_TEMPLATE_CACHE: Optional[list[dict]] = None


class SimpleHogFlowTemplateActionSerializer(serializers.Serializer):
    """
    Simplified action serializer for validating templates without requiring context.
    Used only for loading templates from code files.
    """

    id = serializers.CharField()
    name = serializers.CharField(max_length=400)
    description = serializers.CharField(allow_blank=True, default="", required=False)
    on_error = serializers.ChoiceField(
        choices=["continue", "abort", "complete", "branch"], required=False, allow_null=True
    )
    created_at = serializers.IntegerField(required=False)
    updated_at = serializers.IntegerField(required=False)
    filters = serializers.JSONField(required=False, default=None, allow_null=True)
    type = serializers.CharField(max_length=100)
    config = serializers.JSONField()
    output_variable = serializers.JSONField(required=False, allow_null=True)

    def validate(self, data):
        # Basic validation without context
        if data.get("type") == "trigger":
            config = data.get("config", {})
            trigger_type = config.get("type")
            if trigger_type not in ["webhook", "manual", "tracking_pixel", "schedule", "event"]:
                raise serializers.ValidationError({"config": f"Invalid trigger type: {trigger_type}"})

        # Validate that conditions don't have both 'conditions' and 'condition'
        config = data.get("config", {})
        if config.get("conditions") and config.get("condition"):
            raise serializers.ValidationError({"config": "Cannot specify both 'conditions' and 'condition' fields"})

        return data


class SimpleHogFlowTemplateSerializer(serializers.Serializer):
    """
    Simplified serializer for validating templates without requiring Django context.
    Used only for loading templates from code files.
    """

    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, required=False)
    image_url = serializers.URLField(allow_blank=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False, allow_null=True)
    scope = serializers.CharField()
    created_at = serializers.DateTimeField(required=False)
    created_by = serializers.JSONField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False)
    trigger = serializers.JSONField(required=False)
    trigger_masking = serializers.JSONField(required=False, allow_null=True)
    conversion = serializers.JSONField(required=False, allow_null=True)
    exit_condition = serializers.JSONField(required=False, allow_null=True)
    edges = serializers.JSONField(required=False, allow_null=True)
    actions = SimpleHogFlowTemplateActionSerializer(many=True, required=True)
    abort_action = serializers.JSONField(required=False, allow_null=True)
    variables = serializers.JSONField(required=False, allow_null=True)

    def validate(self, data):
        # Name must not be empty
        name = data.get("name", "")
        if not name.strip():
            raise serializers.ValidationError({"name": "Name cannot be empty"})

        # Scope must be global for code-stored templates
        if data.get("scope") != "global":
            raise serializers.ValidationError(
                {"scope": f"Code-stored templates must have scope='global', got '{data.get('scope')}'"}
            )

        # Must have actions
        actions = data.get("actions", [])
        if not actions:
            raise serializers.ValidationError({"actions": "Template must have at least one action"})

        # Exactly one trigger action required
        trigger_actions = [action for action in actions if action.get("type") == "trigger"]
        if len(trigger_actions) != 1:
            raise serializers.ValidationError(
                {"actions": f"Exactly one trigger action is required, found {len(trigger_actions)}"}
            )

        return data


def load_global_templates() -> list[dict]:
    """
    Load all global workflow templates from JSON files.
    Returns a list of template dictionaries.
    Templates are cached after first load for performance.
    """
    global _TEMPLATE_CACHE

    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    templates = []
    templates_dir = Path(__file__).parent

    for template_file in TEMPLATE_FILES:
        template_path = templates_dir / template_file
        try:
            if not template_path.exists():
                logger.warning(f"Template file not found: {template_file}")
                continue

            with open(template_path, encoding="utf-8") as f:
                data = json.load(f)

            # Validate the template using the simplified serializer
            try:
                serializer = SimpleHogFlowTemplateSerializer(data=data)
                if serializer.is_valid():
                    templates.append({**data, "tags": data.get("tags") or []})
                else:
                    logger.error(f"Template validation failed for {template_file}", errors=serializer.errors)
            except Exception:
                logger.exception(f"Failed to validate template from {template_file}")
        except json.JSONDecodeError:
            logger.exception(f"Failed to parse JSON from {template_file}")
        except Exception as e:
            logger.warning(f"Failed to load template from {template_file}", error=str(e))

    _TEMPLATE_CACHE = templates
    return templates


def get_global_template_by_id(template_id: str) -> Optional[dict]:
    templates = load_global_templates()
    for template in templates:
        if template.get("id") == template_id:
            return template
    return None


def clear_template_cache() -> None:
    global _TEMPLATE_CACHE
    _TEMPLATE_CACHE = None
