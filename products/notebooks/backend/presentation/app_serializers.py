import math
from typing import Any

from django.db import models

import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.utils import flag_identity


def notebook_app_builder_enabled(user: User, team: Team) -> bool:
    identity = flag_identity(user, team, team.organization)
    if identity is None:
        return False
    return bool(
        posthoganalytics.feature_enabled(
            "notebook-app-builder",
            identity.distinct_id,
            groups=identity.groups,
            group_properties=identity.group_properties,
            person_properties=identity.person_properties,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


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
    SLIDER = "slider", "Slider"


class NotebookAppCellDisplay(models.TextChoices):
    OUTPUT = "output", "Output"
    SOURCE = "source", "Source"
    BOTH = "both", "Source and output"


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
    input_kind = serializers.ChoiceField(
        choices=NotebookAppInputKind.choices, default="auto", help_text="Control used for an input."
    )
    options = serializers.ListField(
        child=serializers.CharField(max_length=1000),
        max_length=100,
        default=list,
        help_text="Allowed values for a dropdown.",
    )
    min = serializers.FloatField(default=0, help_text="Slider minimum.")
    max = serializers.FloatField(default=100, help_text="Slider maximum.")
    step = serializers.FloatField(default=1, min_value=0.000001, help_text="Slider increment.")
    display = serializers.ChoiceField(
        choices=NotebookAppCellDisplay.choices,
        default="output",
        help_text="Whether to display cell source, output, or both.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not all(math.isfinite(attrs[field]) for field in ("min", "max", "step")):
            raise serializers.ValidationError("Slider settings must be finite numbers.")
        if attrs["kind"] == "cell" and not attrs["node_id"]:
            raise serializers.ValidationError({"node_id": "Choose a notebook cell."})
        if attrs["kind"] == "input" and not attrs["variable"]:
            raise serializers.ValidationError({"variable": "Choose a notebook variable."})
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
        tab_ids = [tab["id"] for tab in attrs["tabs"]]
        block_ids = [block["id"] for block in attrs["blocks"]]
        if len(set(tab_ids)) != len(tab_ids) or len(set(block_ids)) != len(block_ids):
            raise serializers.ValidationError("Tab and component IDs must be unique.")
        if any(block["tab_id"] not in tab_ids for block in attrs["blocks"]):
            raise serializers.ValidationError("Every component must belong to an existing tab.")
        return attrs


@extend_schema_field(NotebookAppLayoutSerializer)
class NotebookAppLayoutField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        # A PATCH replaces the whole JSON column, so nested fields must be complete even on a partial request.
        serializer = NotebookAppLayoutSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data
