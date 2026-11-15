import json
from typing import Any

from rest_framework import serializers

from products.cdp.backend.presentation.hog_functions import generate_template_bytecode
from products.workflows.backend.facade.workflows import SUPPORTED_ACTION_TYPES, TRIGGER_TYPES

# Caps both the variable definitions on a workflow and the variable values a single run passes,
# so the two share one number instead of drifting. The runtime also checks dynamically set
# variables against this same limit; each cap here front-runs that check with a clearer error.
HOG_FLOW_VARIABLES_MAX_BYTES = 5120


class HogFlowVariableSerializer(serializers.ListSerializer):
    child = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="Variable: {key, type: string|number|boolean, default}.",
    )

    def validate(self, attrs):
        # Make sure the keys are unique
        keys = [item.get("key") for item in attrs]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Variable keys must be unique")

        # Make sure entire variables definition is less than 5KB
        # This is just a check for massive keys / default values, we also have a check for dynamically
        # set variables during execution
        total_size = sum(len(json.dumps(item)) for item in attrs)
        if total_size > HOG_FLOW_VARIABLES_MAX_BYTES:
            raise serializers.ValidationError("Total size of variables definition must be less than 5KB")

        return super().validate(attrs)


class HogFlowMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(
        required=False,
        min_value=60,
        max_value=60 * 60 * 24 * 365 * 3,
        allow_null=True,
        help_text="Seconds (60 to ~94M / 3y) to suppress repeat firings of the same hash.",
    )
    threshold = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.",
    )
    hash = serializers.CharField(
        required=True,
        help_text="HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl.",
    )
    bytecode = serializers.JSONField(required=False, allow_null=True, help_text="Auto-compiled from hash. Do not set.")

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


class HogFlowActionTypeField(serializers.ChoiceField):
    """A closed set of action types, rejected at write time rather than at run time.

    A type with no worker handler can never execute: it saves fine, then every run that reaches it
    dies with "Action type 'x' not supported", and unless the step sets on_error: continue everything
    downstream silently never happens. Keeping `choices` populated also means drf-spectacular emits
    the enum, so generated clients and MCP tools advertise the valid values instead of callers
    guessing them.

    ChoiceField's own invalid_choice message is run through str.format, which can't carry the JSON
    example below (its braces would be read as format placeholders), so the message is raised here.
    """

    def to_internal_value(self, data: Any) -> str:
        # isinstance before the membership test: self.choices is a dict, so `data in self.choices`
        # raises TypeError on an unhashable JSON object/array, which escapes DRF's validation stack
        # (it only catches ValidationError) and 500s the endpoint.
        if isinstance(data, str) and data in self.choices:
            return super().to_internal_value(data)
        raise serializers.ValidationError(
            f"Unsupported action type {self._describe(data)}. "
            f"Valid types are: {', '.join(SUPPORTED_ACTION_TYPES)}. "
            "Steps that act on PostHog data don't get a type of their own - they are type 'function' "
            f"with a template_id.{self._hint(data)}"
        )

    @staticmethod
    def _hint(data: Any) -> str:
        # The types actually seen in stored workflows cluster into a few mistakes, so point at the
        # step the caller was reaching for rather than repeating one example to everyone.
        if not isinstance(data, str):
            return ""
        lowered = data.lower()
        if lowered in TRIGGER_TYPES:
            hint = (
                f" '{data}' is a trigger type, not an action type: the trigger is a single action of "
                "type 'trigger' and its kind belongs in the workflow's trigger field."
            )
            if lowered == "webhook":
                hint += " To call an external endpoint from a step, use template_id 'template-webhook'."
            return hint
        if "person" in lowered or "propert" in lowered or "contact" in lowered:
            return (
                " To set person properties, use template_id 'template-posthog-update-person-properties' "
                "with inputs distinct_id, set_properties and set_once_properties."
            )
        if "webhook" in lowered or "http" in lowered or "request" in lowered:
            return " To call an external endpoint, use template_id 'template-webhook'."
        return ""

    @staticmethod
    def _describe(data: Any) -> str:
        # Echo the value back only when it's a short string. A non-string type is a malformed
        # payload, and interpolating a whole nested object into the message would put it in the
        # response and the logs behind it.
        if not isinstance(data, str):
            return f"(expected a string, got {type(data).__name__})"
        return f'"{data[:100]}"' if len(data) > 100 else f'"{data}"'
