import json

from rest_framework import serializers

from posthog.cdp.validation import generate_template_bytecode

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
