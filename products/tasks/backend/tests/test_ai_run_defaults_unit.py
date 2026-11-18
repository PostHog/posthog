import pytest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from products.tasks.backend.logic.services.ai_run_defaults import validate_ai_run_preferences
from products.tasks.backend.presentation.serializers import TaskRunCreateRequestSerializer


class TestValidateAIRunPreferences:
    """The write-path guard. The config endpoints reject most of this at the serializer, so
    these call it directly: the admin form and any future writer reach it with no serializer
    in front."""

    @parameterized.expand(
        [
            ("pi_with_an_adapter", "pi", "codex", "gpt-5.6-terra", None),
            ("pi_without_a_model", "pi", None, None, "high"),
            ("pi_with_a_value_that_is_not_a_depth", "pi", None, "gpt-5.6-terra", "deep"),
            ("pi_with_a_depth_it_cannot_run", "pi", None, "gpt-5.6-terra", "ultracode"),
            ("acp_with_a_value_that_is_not_a_depth", None, "codex", "gpt-5.6-terra", "deep"),
            ("acp_with_a_model_and_no_adapter", None, None, "gpt-5.6-terra", None),
        ]
    )
    def test_rejects(self, _name, runtime, runtime_adapter, model, reasoning_effort):
        with pytest.raises(ValidationError):
            validate_ai_run_preferences(runtime_adapter, model, reasoning_effort, runtime=runtime)

    @parameterized.expand(
        [
            ("a_pi_pair", "pi", None, "gpt-5.6-terra", "off"),
            ("an_acp_triple", None, "codex", "gpt-5.6-terra", "high"),
            ("an_all_null_clear", None, None, None, None),
        ]
    )
    def test_accepts(self, _name, runtime, runtime_adapter, model, reasoning_effort):
        validate_ai_run_preferences(runtime_adapter, model, reasoning_effort, runtime=runtime)


class TestRunCreateSerializerModeWithoutAdapter:
    # A composer that pins nothing must still be able to state the launch mode — the
    # server resolves the runtime from the stored default and clamps the mode to it.
    def test_mode_without_adapter_is_accepted(self):
        serializer = TaskRunCreateRequestSerializer(data={"initial_permission_mode": "plan"})
        assert serializer.is_valid(), serializer.errors

    def test_mode_outside_the_pinned_adapters_vocabulary_is_still_rejected(self):
        serializer = TaskRunCreateRequestSerializer(
            data={"runtime_adapter": "codex", "model": "gpt-5.5", "initial_permission_mode": "acceptEdits"}
        )
        assert not serializer.is_valid()
        assert "initial_permission_mode" in serializer.errors
