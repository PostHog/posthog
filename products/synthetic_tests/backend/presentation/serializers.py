"""DRF serializers for synthetic_tests."""

from rest_framework import serializers

from products.synthetic_tests.backend.models import SyntheticTest, SyntheticTestRun

VALID_STEP_TYPES = {
    "navigate",
    "click",
    "type",
    "wait",
    "wait_for_selector",
    "assert_element_exists",
    "assert_url_contains",
    "assert_text_visible",
}


class SyntheticTestStepSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=sorted(VALID_STEP_TYPES),
        help_text="The kind of action to perform in this step.",
    )
    url = serializers.URLField(required=False, help_text="Target URL for `navigate` steps.")
    selector = serializers.CharField(
        required=False,
        max_length=1024,
        help_text="CSS selector for steps that target an element (click, type, wait_for_selector, assert_element_exists).",
    )
    value = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2048,
        help_text="Value to type, expected URL fragment, or expected visible text — depending on step type.",
    )
    duration_ms = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=60000,
        help_text="Wait duration in milliseconds for `wait` steps.",
    )


class SyntheticTestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyntheticTestRun
        fields = [
            "id",
            "synthetic_test",
            "started_at",
            "finished_at",
            "status",
            "duration_ms",
            "error_message",
            "error_step_index",
            "screenshot_url",
            "issue_id",
        ]
        read_only_fields = fields


class SyntheticTestSerializer(serializers.ModelSerializer):
    steps = serializers.ListField(
        child=serializers.DictField(),
        help_text="Ordered list of step dicts. Each step has a `type` plus type-specific fields (selector, value, url, duration_ms).",
    )
    last_run = serializers.SerializerMethodField(
        help_text="Most recent run for this test, or null if none have completed yet."
    )
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = SyntheticTest
        fields = [
            "id",
            "name",
            "description",
            "target_url",
            "steps",
            "schedule_cron",
            "timezone",
            "status",
            "create_issue_on_failure",
            "source_replay_id",
            "created_by",
            "created_at",
            "updated_at",
            "next_run_at",
            "last_run_at",
            "last_run",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "next_run_at",
            "last_run_at",
            "last_run",
        ]

    def get_last_run(self, obj: SyntheticTest) -> dict | None:
        run = obj.runs.order_by("-started_at").first()
        if run is None:
            return None
        return SyntheticTestRunSerializer(run).data

    def validate_steps(self, steps: list[dict]) -> list[dict]:
        if not isinstance(steps, list):
            raise serializers.ValidationError("Steps must be a list.")
        for idx, step in enumerate(steps):
            step_ser = SyntheticTestStepSerializer(data=step)
            if not step_ser.is_valid():
                raise serializers.ValidationError({f"step_{idx}": step_ser.errors})
        return steps


class GenerateFromReplayRequestSerializer(serializers.Serializer):
    session_recording_id = serializers.CharField(
        max_length=255,
        help_text="ID of the session recording to convert into a synthetic test step list.",
    )


class GenerateFromReplayResponseSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Suggested name for the test based on the recording.")
    target_url = serializers.URLField(help_text="Inferred starting URL from the recording's first navigation.")
    steps = serializers.ListField(
        child=serializers.DictField(),
        help_text="Generated step list, ready to drop into the step builder.",
    )
