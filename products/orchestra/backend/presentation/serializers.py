from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import DeploymentSummary, EventRecord, ExecutionDetail, ExecutionSummary


class EventRecordSerializer(DataclassSerializer):
    class Meta:
        dataclass = EventRecord


class ExecutionSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = ExecutionSummary


class ExecutionDetailSerializer(DataclassSerializer):
    input = serializers.JSONField(allow_null=True, help_text="Input passed to the execution.")
    result = serializers.JSONField(allow_null=True, help_text="Result returned by the execution.")
    error = serializers.JSONField(allow_null=True, help_text="Error details if the execution failed.")
    events = EventRecordSerializer(many=True, help_text="Ordered list of events in the execution history.")

    class Meta:
        dataclass = ExecutionDetail


class ExecutionFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["RUNNING", "COMPLETED", "FAILED"],
        required=False,
        help_text="Filter by execution status.",
    )
    execution_type = serializers.CharField(
        required=False,
        help_text="Filter by registered execution type name.",
    )
    date_from = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Lower bound for `started_at`. Accepts PostHog relative dates (e.g. '-1h', 'dStart').",
    )
    date_to = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Upper bound for `started_at`. Accepts PostHog relative dates.",
    )
    limit = serializers.IntegerField(
        default=50,
        min_value=1,
        max_value=200,
        help_text="Maximum number of results to return.",
    )
    offset = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text="Number of results to skip for pagination.",
    )


class DeploymentSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = DeploymentSummary


class DeploymentFilterSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Lower bound for `started_at`. Accepts PostHog relative dates (e.g. '-7d', 'dStart').",
    )
    date_to = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Upper bound for `started_at`. Accepts PostHog relative dates.",
    )
    limit = serializers.IntegerField(
        default=50,
        min_value=1,
        max_value=500,
        help_text="Maximum number of deployments to return.",
    )


class DeploymentRegisterSerializer(serializers.Serializer):
    code_version = serializers.CharField(
        max_length=64,
        help_text="Short identifier for the deployed code (e.g. 12-char content hash).",
    )
    image_name = serializers.CharField(
        max_length=512,
        help_text=(
            "Container image reference for this deployment. Built by `bin/deploy-orchestra <folder>` "
            "locally and tagged like `orchestra-user:team-<id>-<sha>`. PostHog `docker run`s it."
        ),
    )
    registered_executions = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
        help_text=(
            "Names of `@execution` definitions registered by the image, discovered from the source. "
            "Used to populate the trigger UI."
        ),
    )


class TriggerExecutionSerializer(serializers.Serializer):
    execution_type = serializers.CharField(
        max_length=255,
        help_text="Name of the registered @execution to start.",
    )
    input = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Input payload passed to the execution function.",
    )


class TriggeredExecutionResponseSerializer(serializers.Serializer):
    execution_id = serializers.CharField(help_text="Identifier of the newly created execution.")
