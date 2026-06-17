from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner, VisionAction, VisionActionRun
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.replay_vision.backend.temporal.vision_actions.synthesis import _markdown_to_slack, _synthesize
from products.replay_vision.backend.temporal.vision_actions.types import SynthesisStatus, SynthesizeActionInputs
from products.replay_vision.backend.tests.helpers import snapshot_for

_SYNTH_PATH = "products.replay_vision.backend.temporal.vision_actions.synthesis"


def _mock_llm(content: str):
    # MaxChatOpenAI(...).invoke([...]) → object with .content
    instance = SimpleNamespace(invoke=lambda _messages: SimpleNamespace(content=content))
    return lambda **_kwargs: instance


class TestVisionActionSynthesis(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="summarizer",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "summarize"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _observation(self, summary: str, title: str | None = None, session_id: str = "s1") -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id=session_id,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={"model_output": {"summary": summary, **({"title": title} if title else {})}},
        )

    def _action(self, **overrides) -> VisionAction:
        defaults: dict = {
            "team": self.team,
            "name": "digest",
            "scanner": self.scanner,
            "created_by": self.user,
            "trigger_config": {"rrule": "FREQ=DAILY", "timezone": "UTC"},
        }
        defaults.update(overrides)
        action = VisionAction(**defaults)
        action.save()
        return action

    def _run_for(self, action: VisionAction, key: str = "k1") -> VisionActionRun:
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key=key)
        run.save()
        return run

    def _synthesize(self, action: VisionAction, run: VisionActionRun, llm_content: str = "# Themes\nAll good."):
        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.MaxChatOpenAI", _mock_llm(llm_content)),
        ):
            return _synthesize(SynthesizeActionInputs(vision_action_id=action.id, run_id=run.id))

    def test_happy_path_persists_markdown_and_slack(self) -> None:
        self._observation("Users churned at checkout", title="Checkout")
        self._observation("Onboarding looked smooth", title="Onboarding", session_id="s2")
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run, llm_content="# Summary\n**Two** themes emerged.")

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 2)
        run.refresh_from_db()
        self.assertIn("Two", run.synthesized_markdown)
        self.assertEqual(run.observation_count, 2)
        # Slack conversion: heading + bold → *...*
        self.assertIn("*Summary*", run.slack_text)
        self.assertIn("*Two*", run.slack_text)

    def test_idempotent_when_already_synthesized(self) -> None:
        self._observation("something")
        action = self._action()
        run = self._run_for(action)
        run.synthesized_markdown = "already here"
        run.observation_count = 5
        run.save()

        # If the LLM were called, this would raise (MaxChatOpenAI patched to blow up).
        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.MaxChatOpenAI", side_effect=AssertionError("LLM should not be called")),
        ):
            result = _synthesize(SynthesizeActionInputs(vision_action_id=action.id, run_id=run.id))

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 5)

    def test_aborts_without_ai_consent(self) -> None:
        self._observation("something")
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.ABORTED_NO_CONSENT)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")

    def test_aborts_without_creator(self) -> None:
        self._observation("something")
        action = self._action(created_by=None)
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.ABORTED_NO_USER)

    def test_skips_when_over_credit_budget(self) -> None:
        self._observation("something")
        action = self._action()
        run = self._run_for(action)

        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=True),
            patch(f"{_SYNTH_PATH}.MaxChatOpenAI", side_effect=AssertionError("LLM should not be called")),
        ):
            result = _synthesize(SynthesizeActionInputs(vision_action_id=action.id, run_id=run.id))

        self.assertEqual(result.status, SynthesisStatus.SKIPPED_OVER_BUDGET)

    def test_skips_empty_window(self) -> None:
        # Observation exists but falls outside the 1-day window.
        obs = self._observation("old news")
        ReplayObservation.objects.filter(pk=obs.pk).update(created_at=datetime.now(UTC) - timedelta(days=10))
        action = self._action(selection={"scanner_type": "summarizer", "window_days": 1})
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SKIPPED_EMPTY)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")

    def test_only_succeeded_observations_feed_synthesis(self) -> None:
        self._observation("good", session_id="ok")
        ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="pending",
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.PENDING,
        )
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.observation_count, 1)

    def test_external_links_are_stripped(self) -> None:
        self._observation("something")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(
            action,
            run,
            llm_content="See [exfil](https://evil.example.com) and visit https://evil.example.com now.",
        )
        run.refresh_from_db()
        self.assertNotIn("https://evil.example.com)", run.synthesized_markdown)  # link target gone
        self.assertIn("`https://evil.example.com`", run.synthesized_markdown)  # bare url defanged

    def test_window_days_omitted_includes_all(self) -> None:
        obs = self._observation("ancient")
        ReplayObservation.objects.filter(pk=obs.pk).update(created_at=datetime.now(UTC) - timedelta(days=365))
        action = self._action(selection={})  # no window_days → no time filter
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)

    def test_prompt_guide_passed_to_llm(self) -> None:
        self._observation("something")
        action = self._action(synthesis_config={"prompt_guide": "focus on rage clicks"})
        run = self._run_for(action)

        captured: dict = {}

        def _capturing_llm(**_kwargs):
            def invoke(messages):
                captured["human"] = messages[-1][1]
                return SimpleNamespace(content="ok")

            return SimpleNamespace(invoke=invoke)

        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.MaxChatOpenAI", _capturing_llm),
        ):
            _synthesize(SynthesizeActionInputs(vision_action_id=action.id, run_id=run.id))

        self.assertIn("focus on rage clicks", captured["human"])


class TestMarkdownToSlack(BaseTest):
    def test_headings_and_bold(self) -> None:
        out = _markdown_to_slack("## Big\nsome **strong** text\n### Small")
        self.assertIn("*Big*", out)
        self.assertIn("*strong*", out)
        self.assertIn("*Small*", out)
        self.assertNotIn("##", out)

    def test_truncates_long_text(self) -> None:
        out = _markdown_to_slack("x" * 50_000)
        self.assertLessEqual(len(out), 39_000)
        self.assertIn("truncated", out)
