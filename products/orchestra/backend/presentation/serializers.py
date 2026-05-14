from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import EventRecord, ExecutionDetail, ExecutionSummary


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
