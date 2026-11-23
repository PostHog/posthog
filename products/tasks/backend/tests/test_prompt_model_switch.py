import json
from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.model_catalogue import ModelChoice
from products.tasks.backend.logic.services.prompt_model_switch import with_prompt_model_switch

MODULE = "products.tasks.backend.logic.services.prompt_model_switch"
CATALOGUE = (
    ModelChoice(
        runtime_adapter="claude", model="claude-opus-4-8", label="Claude Opus 4.8", supported_efforts=("high",)
    ),
    ModelChoice(runtime_adapter="codex", model="gpt-5.5", label="GPT 5.5", supported_efforts=("low", "high")),
    ModelChoice(runtime_adapter="claude", model="claude-sonnet-4-6", label="Claude Sonnet 4.6", supported_efforts=()),
    # Served to PostHog Code, but outside the posthog_ai pin a PostHog AI run mints its token under.
    ModelChoice(runtime_adapter="codex", model="zai-org/glm-5.3", label="GLM 5.3", supported_efforts=()),
)
CODEX_SELECTION = {"runtime_adapter": "codex", "model": "gpt-5.5", "initial_permission_mode": "full-access"}


class TestWithPromptModelSwitch(SimpleTestCase):
    def setUp(self) -> None:
        # A fresh team per test keeps the cached answers of one test away from the next.
        self.team = MagicMock(id=uuid4().int)
        self.user = MagicMock(id=1, distinct_id="person-1")

    def _apply(self, data: dict, *, reply: dict, flag: bool = True) -> tuple[dict, MagicMock]:
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
            updated = with_prompt_model_switch(data, team=self.team, user=self.user)
        return updated, build

    def test_a_new_run_moves_to_a_model_on_another_harness(self) -> None:
        data = {**CODEX_SELECTION, "pending_user_message": "use opus for this"}

        updated, _build = self._apply(data, reply={"model": "claude-opus-4-8", "reasoning_effort": "high"})

        # The request's own data stays as it arrived. Its caller reads the switch from the copy.
        assert data == {**CODEX_SELECTION, "pending_user_message": "use opus for this"}
        data = updated
        assert data["runtime_adapter"] == "claude"
        assert data["model"] == "claude-opus-4-8"
        assert data["reasoning_effort"] == "high"
        # Claude has no "full-access" mode, and a mode the harness lacks fails the run when it starts.
        assert data["initial_permission_mode"] == "default"

    def test_the_run_create_reuses_the_answer_of_the_task_create(self) -> None:
        reply = {"model": "claude-opus-4-8", "reasoning_effort": None}
        first = {**CODEX_SELECTION, "pending_user_message": "use opus for this"}
        second = {**CODEX_SELECTION, "pending_user_message": "use opus for this"}

        _first, first_build = self._apply(first, reply=reply)
        second_updated, second_build = self._apply(second, reply=reply)

        assert first_build.call_count == 1
        second_build.assert_not_called()
        assert second_updated["model"] == "claude-opus-4-8"

    @parameterized.expand(
        [
            # Sonnet 4.6 supports low, medium and high, and the run rejects any other effort.
            ("effort_the_model_supports", "high", "high"),
            ("effort_the_model_lacks", "max", None),
        ]
    )
    def test_an_effort_only_request_is_checked_against_the_run_model(self, _name, requested, expected) -> None:
        data = {
            "runtime_adapter": "claude",
            "model": "claude-sonnet-4-6",
            "pending_user_message": f"use {requested} effort",
        }

        updated, _build = self._apply(data, reply={"model": None, "reasoning_effort": requested})

        assert updated.get("reasoning_effort") == expected

    def test_a_model_outside_the_posthog_ai_pin_is_never_offered(self) -> None:
        data = {**CODEX_SELECTION, "pending_user_message": "use glm for this"}

        updated, build = self._apply(data, reply={"model": "zai-org/glm-5.3", "reasoning_effort": None})

        offered = build.return_value.with_options.return_value.chat.completions.create.call_args.kwargs[
            "response_format"
        ]["json_schema"]["schema"]["properties"]["model"]["enum"]
        assert "zai-org/glm-5.3" not in offered
        assert updated == data

    @parameterized.expand(
        [
            # The untrusted context can hold any text, such as an insight named after a model.
            (
                "model_named_only_in_page_context",
                "<posthog_untrusted_context>Insight: opus rollout</posthog_untrusted_context>\nfix the flaky test",
                True,
            ),
            ("flag_off", "use opus for this", False),
        ]
    )
    def test_leaves_the_selection_alone_without_a_chance_of_a_request(self, _name, message, flag) -> None:
        data = {**CODEX_SELECTION, "pending_user_message": message}

        updated, build = self._apply(data, reply={"model": "claude-opus-4-8", "reasoning_effort": None}, flag=flag)

        assert updated == {**CODEX_SELECTION, "pending_user_message": message}
        build.assert_not_called()
