import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from products.replay_vision.backend.max_tools import DraftReplayVisionScannerPromptTool

_FLAG_PATH = "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled"


class TestDraftReplayVisionScannerPromptTool(BaseTest):
    def _tool(self, context: dict | None = None) -> DraftReplayVisionScannerPromptTool:
        configurable: dict = {"team": self.team, "user": self.user}
        if context is not None:
            configurable["contextual_tools"] = {"draft_replay_vision_scanner_prompt": context}
        config: RunnableConfig = {"configurable": configurable}
        return DraftReplayVisionScannerPromptTool(team=self.team, user=self.user, config=config)

    @parameterized.expand(
        [
            ("monitor", "monitor"),
            ("classifier", "classifier"),
            ("scorer", "scorer"),
            ("summarizer", "summarizer"),
            ("unknown_type", None),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_fills_prompt_and_resolves_type(self, scanner_type, expected_type):
        with patch(_FLAG_PATH, return_value=True):
            content, artifact = await self._tool()._arun_impl(
                prompt="  Did checkout fail?  ", scanner_type=scanner_type
            )

        assert "filled it into the configuration form" in content
        assert artifact["prompt"] == "Did checkout fail?"
        assert artifact["scanner_type"] == expected_type

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolves_scanner_type_from_context(self):
        with patch(_FLAG_PATH, return_value=True):
            _, artifact = await self._tool(context={"scanner_type": "scorer"})._arun_impl(prompt="Rate frustration.")

        assert artifact["scanner_type"] == "scorer"

    @parameterized.expand([("", "empty_prompt"), ("   ", "empty_prompt")])
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_rejects_empty_prompt(self, prompt, expected_error):
        with patch(_FLAG_PATH, return_value=True):
            content, artifact = await self._tool()._arun_impl(prompt=prompt)

        assert artifact["error"] == expected_error
        assert "prompt" not in artifact

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_gated_off_when_product_disabled(self):
        with patch(_FLAG_PATH, return_value=False):
            content, artifact = await self._tool()._arun_impl(prompt="Did checkout fail?")

        assert artifact["error"] == "not_enabled"
        assert "not enabled" in content
