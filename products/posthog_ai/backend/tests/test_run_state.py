import unittest

from products.posthog_ai.backend.run_state import PostHogAIRunState

SYSTEM_PROMPT = {"type": "preset", "preset": "claude_code", "append": "SYS"}


class TestPostHogAIRunState(unittest.TestCase):
    def test_validate_accepts_wire_alias(self) -> None:
        state = PostHogAIRunState.model_validate({"systemPrompt": SYSTEM_PROMPT})
        assert state.system_prompt == SYSTEM_PROMPT

    def test_dump_emits_wire_alias(self) -> None:
        state = PostHogAIRunState(system_prompt=SYSTEM_PROMPT)
        dumped = state.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert dumped == {"systemPrompt": SYSTEM_PROMPT}

    def test_exclude_unset_dumps_only_set_keys(self) -> None:
        state = PostHogAIRunState(
            system_prompt=SYSTEM_PROMPT,
            attached_context=[{"type": "dashboard", "id": 123, "name": "Funnel"}],
            initial_permission_mode="default",
            pending_user_message="wrapped",
        )
        dumped = state.model_dump(mode="json", by_alias=True, exclude_unset=True)
        assert dumped == {
            "systemPrompt": SYSTEM_PROMPT,
            "attached_context": [{"type": "dashboard", "id": 123, "name": "Funnel"}],
            "initial_permission_mode": "default",
            "pending_user_message": "wrapped",
        }

    def test_parent_extra_allow_config_survives_subclassing(self) -> None:
        state = PostHogAIRunState.model_validate({"systemPrompt": SYSTEM_PROMPT, "sandbox_quirk": True})
        dumped = state.model_dump(by_alias=True)
        assert dumped["sandbox_quirk"] is True

    def test_base_run_state_fields_still_parse(self) -> None:
        state = PostHogAIRunState.model_validate(
            {"pending_user_message": "hi", "initial_permission_mode": "default", "resume_from_run_id": "r-1"}
        )
        assert state.pending_user_message == "hi"
        assert state.initial_permission_mode == "default"
        assert state.resume_from_run_id == "r-1"
