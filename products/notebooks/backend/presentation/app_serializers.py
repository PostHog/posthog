import math
from functools import partial
from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.db import models

import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.hogql.errors import ExposedHogQLError

from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.utils import flag_identity, get_safe_cache, safe_cache_set


def notebook_app_builder_enabled(user: User | AnonymousUser, team: Team) -> bool:
    if not isinstance(user, User):
        return False
    identity = flag_identity(user, team, team.organization)
    if identity is None:
        return False
    evaluate = partial(
        posthoganalytics.feature_enabled,
        "notebook-app-builder",
        identity.distinct_id,
        groups=identity.groups,
        group_properties=identity.group_properties,
        person_properties=identity.person_properties,
        send_feature_flag_events=False,
    )
    local = evaluate(only_evaluate_locally=True)
    if local is not None:
        return local

    cache_key = f"notebooks:app-builder:{team.pk}:{user.pk}"
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached is True
    enabled = evaluate() is True
    safe_cache_set(cache_key, enabled, timeout=30)
    return enabled


def update_app_revision(validated_data: dict[str, Any], current_revision: int) -> None:
    revision = validated_data.pop("app_revision", None)
    if "app_draft" in validated_data or "app_published" in validated_data:
        if revision != current_revision:
            raise Conflict("Someone else edited the app. Reload the app builder before saving.")
        validated_data["app_revision"] = current_revision + 1


class NotebookAppBlockKind(models.TextChoices):
    CELL = "cell", "Notebook cell"
    TEXT = "text", "Text"
    INPUT = "input", "Input"
    DIVIDER = "divider", "Divider"


class NotebookAppInputKind(models.TextChoices):
    AUTO = "auto", "Automatic"
    SELECT = "select", "Dropdown"
    QUERY_SELECT = "query_select", "Query dropdown"
    DATE_RANGE = "date_range", "Date range"
    SLIDER = "slider", "Slider"
    TABLE = "table", "Editable table"


class NotebookAppCellDisplay(models.TextChoices):
    OUTPUT = "output", "Output"
    SOURCE = "source", "Source"
    BOTH = "both", "Source and output"


class NotebookAppSelectionSerializer(serializers.Serializer):
    column = serializers.CharField(max_length=256, help_text="Result column whose selected value sets the input.")
    variable = serializers.CharField(max_length=80, help_text="Published input to update.")
    tab_id = serializers.CharField(
        max_length=80, allow_blank=True, default="", help_text="Tab to open after selection."
    )
    condition = serializers.CharField(
        max_length=1200, allow_blank=True, default="", help_text="Optional Hog condition over row, value, and inputs."
    )
    condition_bytecode = serializers.ListField(
        child=serializers.JSONField(), read_only=True, help_text="Compiled Hog condition for this selection."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        from posthog.hogql.compiler.bytecode import to_bytecode

        try:
            attrs["condition_bytecode"] = to_bytecode(attrs["condition"]) if attrs["condition"] else []
        except ExposedHogQLError as error:
            raise serializers.ValidationError({"condition": str(error)}) from error
        return attrs


class NotebookAppSubmitAction(models.TextChoices):
    CREATE_COHORT = "create_cohort", "Create a cohort"
    RUN_WORKFLOW = "run_workflow", "Run a workflow"


class NotebookAppBlockSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=80, help_text="Stable component identifier within the app.")
    kind = serializers.ChoiceField(choices=NotebookAppBlockKind.choices, help_text="Type of app component.")
    tab_id = serializers.CharField(max_length=80, help_text="Tab containing this component.")
    title = serializers.CharField(max_length=256, allow_blank=True, default="", help_text="Optional component title.")
    width = serializers.IntegerField(min_value=1, max_value=12, default=12, help_text="Width in a twelve-column grid.")
    node_id = serializers.CharField(max_length=160, allow_blank=True, default="", help_text="Source notebook cell ID.")
    text = serializers.CharField(
        max_length=20000, allow_blank=True, default="", help_text="Markdown for a text component."
    )
    variable = serializers.CharField(
        max_length=80, allow_blank=True, default="", help_text="Notebook variable controlled by an input."
    )
    end_variable = serializers.CharField(
        max_length=80, allow_blank=True, default="", help_text="End date variable for a date range."
    )
    input_kind = serializers.ChoiceField(
        choices=NotebookAppInputKind.choices, default="auto", help_text="Control used for an input."
    )
    option_column = serializers.CharField(
        max_length=256, allow_blank=True, default="", help_text="Column supplying choices for a query dropdown."
    )
    table_columns = serializers.ListField(
        child=serializers.CharField(max_length=80),
        max_length=9,
        required=False,
        help_text="Additional list variables displayed alongside the first column of a table input.",
    )
    options = serializers.ListField(
        child=serializers.CharField(max_length=1000),
        max_length=100,
        default=list,
        help_text="Allowed values for a dropdown.",
    )
    selection = NotebookAppSelectionSerializer(
        required=False, allow_null=True, help_text="Action when a viewer selects a result."
    )
    min = serializers.FloatField(default=0, help_text="Slider minimum.")
    max = serializers.FloatField(default=100, help_text="Slider maximum.")
    step = serializers.FloatField(default=1, min_value=0.000001, help_text="Slider increment.")
    display = serializers.ChoiceField(
        choices=NotebookAppCellDisplay.choices,
        default="output",
        help_text="Whether to display cell source, output, or both.",
    )
    submit_action = serializers.ChoiceField(
        choices=NotebookAppSubmitAction.choices,
        required=False,
        help_text="Action viewers can explicitly submit with rows from a SQL cell.",
    )
    workflow_id = serializers.UUIDField(required=False, help_text="Workflow to run with the submitted rows.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not all(math.isfinite(attrs[field]) for field in ("min", "max", "step")):
            raise serializers.ValidationError("Slider settings must be finite numbers.")
        if attrs["kind"] == "cell" and not attrs["node_id"]:
            raise serializers.ValidationError({"node_id": "Choose a notebook cell."})
        if attrs.get("submit_action") and (attrs["kind"] != "cell" or attrs["display"] == "source"):
            raise serializers.ValidationError({"submit_action": "Choose a cell with visible output."})
        if attrs.get("submit_action") == "run_workflow" and not attrs.get("workflow_id"):
            raise serializers.ValidationError({"workflow_id": "Choose a workflow."})
        if attrs.get("workflow_id"):
            attrs["workflow_id"] = str(attrs["workflow_id"])
        if attrs["kind"] == "input" and not attrs["variable"]:
            raise serializers.ValidationError({"variable": "Choose a notebook variable."})
        if attrs["input_kind"] == "query_select" and attrs["kind"] != "input":
            raise serializers.ValidationError("Query dropdowns must be input components.")
        if attrs.get("table_columns"):
            columns = [attrs["variable"], *attrs["table_columns"]]
            if attrs["kind"] != "input" or attrs["input_kind"] != "table" or len(columns) != len(set(columns)):
                raise serializers.ValidationError({"table_columns": "Choose distinct list variables for the table."})
        if attrs["min"] >= attrs["max"]:
            raise serializers.ValidationError({"max": "Maximum must be greater than minimum."})
        return attrs


class NotebookAppTabSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=80, help_text="Stable tab identifier.")
    title = serializers.CharField(max_length=80, help_text="Tab label.")


class NotebookAppLayoutSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=256, allow_blank=True, default="", help_text="App title, falling back to the notebook title."
    )
    description = serializers.CharField(
        max_length=2000, allow_blank=True, default="", help_text="Description displayed below the app title."
    )
    full_width = serializers.BooleanField(
        default=False, help_text="Use all available width instead of a centered page."
    )
    tabs: serializers.ListSerializer[dict[str, Any]] = serializers.ListSerializer(
        child=NotebookAppTabSerializer(), allow_empty=False, max_length=20, help_text="Ordered app tabs."
    )
    blocks: serializers.ListSerializer[dict[str, Any]] = serializers.ListSerializer(
        child=NotebookAppBlockSerializer(),
        max_length=100,
        help_text="Ordered components, arranged in rows within each tab.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        from products.notebooks.backend.app_viewer import app_input_names

        tab_ids = [tab["id"] for tab in attrs["tabs"]]
        block_ids = [block["id"] for block in attrs["blocks"]]
        if len(set(tab_ids)) != len(tab_ids) or len(set(block_ids)) != len(block_ids):
            raise serializers.ValidationError("Tab and component IDs must be unique.")
        if any(block["tab_id"] not in tab_ids for block in attrs["blocks"]):
            raise serializers.ValidationError("Every component must belong to an existing tab.")
        inputs = app_input_names(attrs["blocks"])
        for block in attrs["blocks"]:
            if selection := block.get("selection"):
                if block["kind"] != "cell" or selection["variable"] not in inputs:
                    raise serializers.ValidationError("A result selection must set an input included in the app.")
                if selection["tab_id"] and selection["tab_id"] not in tab_ids:
                    raise serializers.ValidationError("Choose an existing tab for the result selection.")
        return attrs


@extend_schema_field(NotebookAppLayoutSerializer)
class NotebookAppLayoutField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        # A PATCH replaces the whole JSON column, so nested fields must be complete even on a partial request.
        serializer = NotebookAppLayoutSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class NotebookAppScheduleSettingsSerializer(serializers.Serializer):
    checked_node_ids = serializers.ListField(
        child=serializers.CharField(max_length=128),
        max_length=3,
        required=False,
        help_text="Published Python or connected SQL cells to check privately with the schedule owner's current access.",
    )
    revision = serializers.IntegerField(min_value=0, help_text="Published revision to refresh.")
    enabled = serializers.BooleanField(help_text="Whether this schedule runs.")
    interval_minutes = serializers.IntegerField(
        min_value=60, max_value=10080, default=1440, help_text="Minutes between scheduled refreshes."
    )
    freshness_minutes = serializers.IntegerField(
        min_value=60, max_value=43200, default=1440, help_text="Maximum acceptable result age, in minutes."
    )

    def validate(self, attrs):
        if attrs["freshness_minutes"] < attrs["interval_minutes"]:
            raise serializers.ValidationError(
                {"freshness_minutes": "Choose a maximum age at least as long as the refresh interval."}
            )
        return attrs


class NotebookAppRefreshHistorySerializer(serializers.Serializer):
    revision = serializers.IntegerField()
    due_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    output_count = serializers.IntegerField()
    checked_count = serializers.IntegerField()
    duration_seconds = serializers.FloatField(allow_null=True)


class NotebookAppRefreshCheckTargetSerializer(serializers.Serializer):
    node_id = serializers.CharField()
    title = serializers.CharField()
    kind = serializers.CharField()


class NotebookAppRefreshStatusSerializer(serializers.Serializer):
    check_targets = NotebookAppRefreshCheckTargetSerializer(many=True)
    checked_node_ids = serializers.ListField(child=serializers.CharField())
    published_revision = serializers.IntegerField()
    enabled = serializers.BooleanField()
    revision = serializers.IntegerField(required=False)
    interval_minutes = serializers.IntegerField(required=False)
    freshness_minutes = serializers.IntegerField(required=False)
    next_due_at = serializers.DateTimeField(required=False)
    last_success_at = serializers.DateTimeField(required=False, allow_null=True)
    stale = serializers.BooleanField(required=False)
    history = NotebookAppRefreshHistorySerializer(many=True)

    def to_representation(self, instance):
        return {key: value for key, value in super().to_representation(instance).items() if value is not None}


class NotebookAppRefreshedOutputSerializer(serializers.Serializer):
    columns = serializers.ListField(child=serializers.CharField(), allow_null=True, required=False)
    results = serializers.ListField(child=serializers.ListField(child=serializers.JSONField()))
    types = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField()), allow_null=True, required=False
    )
    hasMore = serializers.BooleanField(required=False, allow_null=True)


class NotebookAppRefreshOutputsSerializer(serializers.Serializer):
    revision = serializers.IntegerField()
    outputs = serializers.DictField(child=NotebookAppRefreshedOutputSerializer())
