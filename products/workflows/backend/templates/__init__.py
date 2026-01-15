"""
Workflow template loader for global templates stored in code.
"""

import json
from pathlib import Path
from typing import Optional

import structlog
from rest_framework import serializers

logger = structlog.get_logger(__name__)

# Cache for loaded templates
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
    Load all global workflow templates from Python files in this directory.
    Returns a list of template dictionaries.
    Templates are cached after first load for performance.
    """
    global _TEMPLATE_CACHE

    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE

    templates = []
    templates_dir = Path(__file__).parent

    # Find all .template.py files
    for template_file in templates_dir.glob("*.template.py"):
        if template_file.name == "__init__.py":
            continue

        try:
            # Read and execute the file to get the template dict
            namespace = {}
            code = template_file.read_text()
            exec(code, namespace)

            # Get the template dict
            if "template" in namespace:
                template_dict = namespace["template"]
                # The 'data' field is a JSON string that needs to be parsed
                data_str = template_dict["data"]
                data = json.loads(data_str) if isinstance(data_str, str) else data_str

                # Validate the template using the simplified serializer
                try:
                    serializer = SimpleHogFlowTemplateSerializer(data=data)
                    if serializer.is_valid():
                        templates.append(data)
                    else:
                        logger.error(f"Template validation failed for {template_file.name}", errors=serializer.errors)
                except Exception:
                    logger.exception(f"Failed to validate template from {template_file.name}")
        except Exception as e:
            # Log but don't fail if one template has issues
            logger.warning(f"Failed to load template from {template_file.name}", error=str(e))

    # Cache the templates
    _TEMPLATE_CACHE = templates
    return templates


def get_global_template_by_id(template_id: str) -> Optional[dict]:
    """
    Get a specific global template by ID.
    Returns None if not found.
    """
    templates = load_global_templates()
    for template in templates:
        if template.get("id") == template_id:
            return template
    return None


def clear_template_cache() -> None:
    """
    Clear the template cache. Useful for development and testing.
    """
    global _TEMPLATE_CACHE
    _TEMPLATE_CACHE = None
