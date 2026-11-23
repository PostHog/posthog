import json

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.model_catalogue import ModelChoice
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.activities.switch_model_from_message import (
    SwitchModelFromMessageInput,
    switch_model,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.switch_model_from_message"
CATALOGUE = (
    ModelChoice(
        runtime_adapter="claude", model="claude-opus-4-8", label="Claude Opus 4.8", supported_efforts=("high",)
    ),
    ModelChoice(runtime_adapter="claude", model="claude-sonnet-4-6", label="Claude Sonnet 4.6", supported_efforts=()),
    ModelChoice(runtime_adapter="codex", model="gpt-5.5", label="GPT 5.5", supported_efforts=("high",)),
)
START_STATE = {"runtime_adapter": "claude", "model": "claude-sonnet-4-6"}
OPUS_REPLY = {"model": "claude-opus-4-8", "reasoning_effort": None}


def _switch(run, *, reply: dict, flag: bool = True, **input_fields) -> tuple[bool, MagicMock]:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(reply)))]
    with (
        patch(f"{MODULE}.available_model_choices", return_value=CATALOGUE),
        patch(f"{MODULE}.prompt_model_switch_enabled", return_value=flag),
        patch(f"{MODULE}.get_model_access_error", return_value=None),
        patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=False),
        patch("products.tasks.backend.logic.model_override.build_ai_gateway_openai_client") as build,
    ):
        build.return_value.with_options.return_value.chat.completions.create.return_value = completion
        switched = switch_model(SwitchModelFromMessageInput(run_id=str(run.id), **input_fields))
    return switched, build


@pytest.mark.django_db
class TestSwitchModelFromMessage:
    @pytest.fixture
    def run(self, test_task, test_task_run):
        test_task.origin_product = Task.OriginProduct.POSTHOG_AI
        test_task.save(update_fields=["origin_product"])
        test_task_run.state = {**START_STATE, "pending_user_message": "use opus for this"}
        test_task_run.save(update_fields=["state"])
        return test_task_run

    def test_first_message_switch_is_written_before_the_agent_starts(self, run):
        switched, _build = _switch(run, reply=OPUS_REPLY)

        run.refresh_from_db()
        assert switched is True
        assert run.state["model"] == "claude-opus-4-8"

    @pytest.mark.parametrize(
        "message,origin,flag",
        [
            pytest.param(
                "<posthog_untrusted_context>Insight: opus rollout</posthog_untrusted_context>\nfix the flaky test",
                Task.OriginProduct.POSTHOG_AI,
                True,
                id="model_named_only_in_page_context",
            ),
            pytest.param("use opus for this", Task.OriginProduct.SLACK, True, id="other_origin"),
            pytest.param("use opus for this", Task.OriginProduct.POSTHOG_AI, False, id="flag_off"),
        ],
    )
    def test_never_calls_the_classifier_without_a_chance_of_a_request(self, run, message, origin, flag):
        run.task.origin_product = origin
        run.task.save(update_fields=["origin_product"])
        run.state = {**START_STATE, "pending_user_message": message}
        run.save(update_fields=["state"])

        switched, build = _switch(run, reply=OPUS_REPLY, flag=flag)

        run.refresh_from_db()
        assert switched is False
        assert run.state["model"] == "claude-sonnet-4-6"
        build.assert_not_called()

    def test_a_model_from_another_runtime_is_no_switch(self, run):
        switched, _build = _switch(run, reply={"model": "gpt-5.5", "reasoning_effort": None})

        run.refresh_from_db()
        assert switched is False
        assert run.state["model"] == "claude-sonnet-4-6"

    def test_live_switch_goes_to_the_agent_before_the_message(self, run):
        result = MagicMock(success=True)
        with (
            patch(
                "products.tasks.backend.logic.services.agent_command.send_set_config_option", return_value=result
            ) as send,
            patch("products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token"),
        ):
            switched, _build = _switch(run, reply=OPUS_REPLY, message="use opus for this", live=True)

        run.refresh_from_db()
        assert switched is True
        assert [(c.args[1], c.args[2]) for c in send.call_args_list] == [("model", "claude-opus-4-8")]
        assert run.state["model"] == "claude-opus-4-8"
