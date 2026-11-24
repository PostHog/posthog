import json

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.tasks.backend.logic.services.model_catalogue import ModelChoice
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.process_task.activities.switch_model_from_message import (
    SwitchModelFromMessageInput,
    switch_model,
)

LOOKUP = "products.tasks.backend.logic.services.prompt_model_switch"
CATALOGUE = (
    ModelChoice(
        runtime_adapter="claude", model="claude-opus-4-8", label="Claude Opus 4.8", supported_efforts=("high",)
    ),
    ModelChoice(runtime_adapter="claude", model="claude-sonnet-4-6", label="Claude Sonnet 4.6", supported_efforts=()),
    ModelChoice(runtime_adapter="codex", model="gpt-5.5", label="GPT 5.5", supported_efforts=("high",)),
)
START_STATE = {"runtime_adapter": "claude", "model": "claude-sonnet-4-6"}


def _switch(run, message: str, *, reply: dict, flag: bool = True) -> tuple[bool, MagicMock, MagicMock]:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(reply)))]
    with (
        patch(f"{LOOKUP}.available_model_choices", return_value=CATALOGUE),
        patch(f"{LOOKUP}.prompt_model_switch_enabled", return_value=flag),
        patch(f"{LOOKUP}.get_model_access_error", return_value=None),
        patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=False),
        patch("products.tasks.backend.logic.model_override.build_ai_gateway_openai_client") as build,
        patch(
            "products.tasks.backend.logic.services.agent_command.send_set_config_option",
            return_value=MagicMock(success=True),
        ) as send,
        patch("products.tasks.backend.logic.services.connection_token.create_sandbox_connection_token"),
    ):
        build.return_value.with_options.return_value.chat.completions.create.return_value = completion
        switched = switch_model(SwitchModelFromMessageInput(run_id=str(run.id), message=message))
    return switched, build, send


@pytest.mark.django_db
class TestSwitchModelFromMessage:
    @pytest.fixture
    def run(self, test_task, test_task_run):
        cache.clear()
        test_task.origin_product = Task.OriginProduct.POSTHOG_AI
        test_task.save(update_fields=["origin_product"])
        test_task_run.state = dict(START_STATE)
        test_task_run.save(update_fields=["state"])
        return test_task_run

    def test_live_switch_goes_to_the_agent_before_the_message(self, run):
        switched, _build, send = _switch(run, "use opus for this", reply={"model": "claude-opus-4-8"})

        run.refresh_from_db()
        assert switched is True
        assert [(c.args[1], c.args[2]) for c in send.call_args_list] == [("model", "claude-opus-4-8")]
        assert run.state["model"] == "claude-opus-4-8"

    @pytest.mark.parametrize(
        "origin,reply",
        [
            pytest.param(Task.OriginProduct.SLACK, {"model": "claude-opus-4-8"}, id="other_origin"),
            # A live run cannot change its harness, so a Codex model is no answer for a Claude run.
            pytest.param(Task.OriginProduct.POSTHOG_AI, {"model": "gpt-5.5"}, id="other_harness"),
        ],
    )
    def test_leaves_the_live_run_alone(self, run, origin, reply):
        run.task.origin_product = origin
        run.task.save(update_fields=["origin_product"])

        switched, _build, send = _switch(run, "use opus for this", reply={"reasoning_effort": None, **reply})

        run.refresh_from_db()
        assert switched is False
        send.assert_not_called()
        assert run.state["model"] == "claude-sonnet-4-6"

    def test_a_revoked_consent_stops_a_queued_follow_up_switch(self, run):
        run.task.team.organization.is_ai_data_processing_approved = False
        run.task.team.organization.save(update_fields=["is_ai_data_processing_approved"])

        switched, build, send = _switch(run, "use opus for this", reply={"model": "claude-opus-4-8"})

        assert switched is False
        build.assert_not_called()
        send.assert_not_called()

    def test_a_classification_past_its_budget_changes_nothing(self, run):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.switch_model_from_message.monotonic",
            side_effect=[0.0, 26.0],
        ):
            switched, _build, send = _switch(run, "use opus for this", reply={"model": "claude-opus-4-8"})

        run.refresh_from_db()
        assert switched is False
        send.assert_not_called()
        assert run.state["model"] == "claude-sonnet-4-6"
