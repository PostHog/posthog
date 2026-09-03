from typing import Any

from rest_framework import serializers

from products.notebooks.backend.facade.widgets import (
    DEFAULT_WIDGET_MODEL,
    MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH,
    MAX_WIDGET_PROMPT_LENGTH,
    WIDGET_LIFECYCLE_STATUS_CHOICES,
    WIDGET_MODEL_CHOICES,
)


class WidgetGenerateRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH,
        trim_whitespace=False,
        error_messages={
            "max_length": f"Keep widget instructions to {MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH:,} characters or fewer."
        },
        help_text=(
            "Instructions for the generated widget. Initial and improvement instructions accept up to 20,000 "
            "characters; regeneration accepts complete instructions up to 50,000 characters."
        ),
    )
    generation_id = serializers.UUIDField(help_text="Idempotency key for this generation job.")
    model = serializers.ChoiceField(
        choices=WIDGET_MODEL_CHOICES,
        default=DEFAULT_WIDGET_MODEL,
        help_text="AI model used to generate the widget.",
    )
    generation_operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve"],
        default="regenerate",
        help_text="Whether to generate from scratch or improve the current source.",
    )
    expected_current_version_id = serializers.UUIDField(
        required=False,
        help_text="Current widget version the improvement is based on. Required for improve operations.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        operation = attrs["generation_operation"]
        prompt = attrs["prompt"].strip()
        if operation != "regenerate" and len(prompt) > MAX_WIDGET_PROMPT_LENGTH:
            raise serializers.ValidationError(
                {"prompt": f"Keep widget instructions to {MAX_WIDGET_PROMPT_LENGTH:,} characters or fewer."}
            )
        if operation == "improve" and "expected_current_version_id" not in attrs:
            raise serializers.ValidationError({"expected_current_version_id": "Reload the widget before improving it."})
        return attrs


class WidgetCancelRequestSerializer(serializers.Serializer):
    generation_id = serializers.UUIDField(help_text="Generation job to cancel.")


class WidgetJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Generation job identifier.")
    status = serializers.ChoiceField(
        choices=["queued", "generating", "publishing"],
        help_text="Current durable job state.",
    )
    phase = serializers.CharField(help_text="Current generation phase.")
    model = serializers.CharField(help_text="AI model processing the job.")
    created_at = serializers.DateTimeField(help_text="When the job was queued.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="When a worker started the job.")


class WidgetSecurityFindingSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(
        choices=["low", "medium", "high", "critical"],
        help_text="Severity of this potential security issue.",
    )
    title = serializers.CharField(help_text="Short description of the potential security issue.")
    details = serializers.CharField(help_text="Why the source may be unsafe and what it could do.")


class WidgetSecurityReviewSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(
        choices=["none", "low", "medium", "high", "critical"],
        help_text="Highest severity found, or none when the review found no issues.",
    )
    summary = serializers.CharField(help_text="Concise result from the automated security review.")
    findings = WidgetSecurityFindingSerializer(many=True, help_text="Potential security issues found in the source.")
    model = serializers.CharField(help_text="Fast AI model used for the security review.")
    review_version = serializers.CharField(help_text="Version of the security review instructions and parser.")
    reviewed_at = serializers.DateTimeField(help_text="When this exact widget source was reviewed.")


class WidgetStatusSerializer(serializers.Serializer):
    lifecycle_status = serializers.ChoiceField(
        choices=WIDGET_LIFECYCLE_STATUS_CHOICES,
        help_text="Current widget and preview state.",
    )
    error_detail = serializers.CharField(required=False, allow_null=True, help_text="Actionable failure detail.")
    error_code = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Stable failure code for support and diagnostics.",
    )
    failure_phase = serializers.ChoiceField(
        choices=["generating_source", "reviewing_source", "publishing_source", "unknown"],
        required=False,
        allow_null=True,
        help_text="Generation step that failed, if a generation job failed.",
    )
    artifact_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Short-lived URL for the selected widget version's preview.",
    )
    frame_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Logical dataframe slots available to the selected version.",
    )
    current_version_id = serializers.UUIDField(allow_null=True, help_text="Selected immutable widget version.")
    widget_id = serializers.UUIDField(allow_null=True, help_text="Reusable widget identity.")
    instance_id = serializers.UUIDField(allow_null=True, help_text="Placement in this notebook.")
    has_versions = serializers.BooleanField(help_text="Whether the widget has generated history.")
    active_job = WidgetJobSerializer(allow_null=True, help_text="Active generation job, if any.")
    security_review = WidgetSecurityReviewSerializer(
        allow_null=True,
        help_text="Automated review for the selected source, or null for a legacy unreviewed version.",
    )
    build_hash = serializers.CharField(
        allow_null=True,
        help_text="Hex SHA-256 over the exact immutable artifact manifest selected for display.",
    )


class WidgetVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Immutable widget version identifier.")
    parent_version_id = serializers.UUIDField(allow_null=True, help_text="Version this one was based on.")
    version = serializers.IntegerField(min_value=1, help_text="One-based version number.")
    version_operation = serializers.ChoiceField(
        source="operation",
        choices=["initial", "regenerate", "improve", "revert"],
        help_text="Action that created this version.",
    )
    prompt_delta = serializers.CharField(help_text="Instructions added by this version.")
    effective_prompt = serializers.CharField(
        max_length=MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH,
        help_text="Complete instructions represented by this version, up to 50,000 characters.",
    )
    model = serializers.CharField(allow_null=True, help_text="AI model, or null when this version did not run a model.")
    created_at = serializers.DateTimeField(help_text="When this version was created.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        allow_null=True,
        help_text="Preview build state.",
    )
    artifact_url = serializers.URLField(allow_null=True, help_text="Preview URL when retained and ready.")
    frame_names = serializers.ListField(
        child=serializers.CharField(), help_text="Logical dataframe slots available to this version."
    )
    is_current = serializers.BooleanField(help_text="Whether this notebook instance currently displays this version.")
    security_review = WidgetSecurityReviewSerializer(
        allow_null=True,
        help_text="Automated review for this source, or null for a legacy unreviewed version.",
    )
    build_hash = serializers.CharField(
        allow_null=True,
        help_text="Hex SHA-256 over this version's exact immutable artifact manifest.",
    )


class WidgetVersionPageSerializer(serializers.Serializer):
    results = WidgetVersionSerializer(many=True, help_text="Versions ordered newest first.")
    count = serializers.IntegerField(min_value=0, help_text="Total versions.")
    next_offset = serializers.IntegerField(allow_null=True, help_text="Offset for the next page.")


class WidgetVersionQuerySerializer(serializers.Serializer):
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Zero-based version offset.")
    limit = serializers.IntegerField(default=25, min_value=1, max_value=100, help_text="Maximum versions to return.")


class WidgetSourceSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        help_text="Read-only source code for the current widget version."
    )


class WidgetSourceQuerySerializer(serializers.Serializer):
    version_id = serializers.UUIDField(
        required=False,
        help_text="Immutable widget version whose source should be returned. Defaults to the displayed version.",
    )


class WidgetRevertRequestSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Earlier version to restore as a new version.")
    expected_current_version_id = serializers.UUIDField(help_text="Current version used for optimistic concurrency.")


class WidgetFrameQuerySerializer(serializers.Serializer):
    version_id = serializers.UUIDField(required=False, help_text="Version requesting the data.")
    run_id = serializers.UUIDField(required=False, help_text="Completed run selected by the first page request.")
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Zero-based row offset.")
    limit = serializers.IntegerField(default=100, min_value=1, max_value=500, help_text="Maximum rows in this page.")


class WidgetFrameColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Column name.")
    type = serializers.CharField(help_text="Column type reported by the completed notebook run.")


class WidgetFrameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Logical dataframe name.")
    runId = serializers.UUIDField(help_text="Completed notebook run used for every page in this iframe load.")
    columns = WidgetFrameColumnSerializer(many=True, help_text="Dataframe columns in display order.")
    rows = serializers.ListField(
        child=serializers.ListField(child=serializers.JSONField()), help_text="Requested page of dataframe rows."
    )
    totalRowCount = serializers.IntegerField(min_value=0, help_text="Rows available in the completed run.")
    includedRowCount = serializers.IntegerField(min_value=0, help_text="Rows returned in this response.")
    offset = serializers.IntegerField(min_value=0, help_text="Zero-based offset of this page.")
    nextOffset = serializers.IntegerField(min_value=0, allow_null=True, help_text="Offset for the next page, if any.")
    truncated = serializers.BooleanField(help_text="Whether more rows exist after this page.")


class WidgetErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    detail = serializers.CharField(help_text="Actionable error detail.")
