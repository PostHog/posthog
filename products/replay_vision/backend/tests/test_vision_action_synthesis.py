from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner, VisionAction, VisionActionRun
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionActionRunStatus
from products.replay_vision.backend.temporal.vision_actions.synthesis import _markdown_to_slack, _synthesize
from products.replay_vision.backend.temporal.vision_actions.types import SynthesisStatus, SynthesizeGroupSummaryInputs
from products.replay_vision.backend.tests.helpers import snapshot_for

_SYNTH_PATH = "products.replay_vision.backend.temporal.vision_actions.synthesis"


def _user_message(kwargs: dict) -> str:
    return next((m["content"] for m in kwargs.get("messages", []) if m["role"] == "user"), "")


def _mock_openai(content: str, captured: list[str] | None = None):
    # OpenAI(...).chat.completions.create(...) → object with .choices[0].message.content
    def _create(**kwargs) -> SimpleNamespace:
        if captured is not None:
            captured.append(_user_message(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    return lambda **_kwargs: client


def _no_llm_client(**_kwargs):
    raise AssertionError("LLM should not be called")


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
            scanner_result={
                "model_output": {
                    "scanner_type": ScannerType.SUMMARIZER,
                    "summary": summary,
                    **({"title": title} if title else {}),
                }
            },
        )

    def _action(self, **overrides) -> VisionAction:
        defaults: dict = {
            "team": self.team,
            "name": "summary",
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

    def _synthesize(
        self,
        action: VisionAction,
        run: VisionActionRun,
        llm_content: str = "# Themes\nAll good.",
        captured_prompts: list[str] | None = None,
    ):
        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.OpenAI", _mock_openai(llm_content, captured_prompts)),
        ):
            return _synthesize(SynthesizeGroupSummaryInputs(run_id=run.id, team_id=self.team.id))

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
        # Slack conversion: heading + bold → *...* — stored under output["slack"]
        self.assertIn("*Summary*", run.output["slack"])
        self.assertIn("*Two*", run.output["slack"])

    def test_summary_leads_with_scanner_window_and_count_header(self) -> None:
        # The report must always state which scanner it's for, how many recordings it covers, and the
        # window start — prepended in code so it's present regardless of what the LLM returns.
        self._observation("Users churned at checkout", title="Checkout")
        self._observation("Onboarding looked smooth", title="Onboarding", session_id="s2")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="# Summary\nThemes.")

        run.refresh_from_db()
        self.assertTrue(
            run.synthesized_markdown.startswith("**Summary for summarizer** — 2 recordings since "),
            run.synthesized_markdown,
        )
        # The header rides into the Slack payload too (bold header → *bold*).
        self.assertIn("*Summary for summarizer*", run.output["slack"])

    def test_header_flags_sampling_when_window_exceeds_cap(self) -> None:
        # When the period holds more observations than the cap, the header must say the summary covers
        # only a sample — otherwise a capped summary reads as if it saw everything.
        for i in range(3):
            self._observation(f"obs {i}", session_id=f"s{i}")
        action = self._action(max_observations=2)
        run = self._run_for(action)

        self._synthesize(action, run)

        run.refresh_from_db()
        self.assertIn("sampled 2 of 3 recordings", run.synthesized_markdown)

    def test_summary_header_sanitizes_scanner_name(self) -> None:
        # A scanner name is free text; markdown/mrkdwn control chars must be stripped so they can't
        # garble the bold header (the "**" bold regex breaks on an interior "*").
        self.scanner.name = "Check*out_flow"
        self.scanner.save()
        self._observation("churned")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run)

        run.refresh_from_db()
        self.assertIn("**Summary for Checkoutflow**", run.synthesized_markdown)

    def test_summary_header_defangs_links_in_scanner_name(self) -> None:
        # A scanner name is free text and lands in the header; a name with link/image markdown must not
        # become an active external link/image in the delivered report (in-app or Slack).
        self.scanner.name = "Checkout ![x](https://evil.example/pixel)"
        self.scanner.save()
        self._observation("churned")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run)

        run.refresh_from_db()
        self.assertNotIn("](https://evil.example", run.synthesized_markdown)
        self.assertNotIn("](https://evil.example", run.output["slack"])

    def test_persists_only_included_observation_ids(self) -> None:
        # observation_ids must track the summaries actually included — a blank-summary observation is
        # skipped by _fetch_observations, so its id must not land in the persisted list.
        included = self._observation("Users churned at checkout", title="Checkout")
        self._observation("   ", session_id="s2")  # blank summary → excluded from the summary and the ids
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [str(included.id)])

    def test_samples_across_window_when_over_cap(self) -> None:
        # Over the action's cap, observations are sampled evenly across the window by recency rank —
        # not just the newest N — so a busy window still reflects the whole period. With 9 in-window
        # observations and a cap of 3, the stride (9/3=3) picks recency ranks 0, 3, 6.
        obs = []
        for i in range(1, 10):
            o = self._observation(f"obs {i}", session_id=f"s{i}")
            ReplayObservation.objects.filter(pk=o.pk).update(created_at=datetime.now(UTC) - timedelta(hours=i))
            obs.append(o)  # obs[0] is newest (1h ago) … obs[8] is oldest (9h ago)
        action = self._action(max_observations=3)
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 3)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [str(obs[0].id), str(obs[3].id), str(obs[6].id)])

    def test_sample_is_deterministic_when_timestamps_tie(self) -> None:
        # Observations are often bulk-created with identical created_at; without an `-id` tiebreaker
        # Postgres orders ties arbitrarily and the sampled set (and persisted observation_ids) can drift
        # run-to-run. With the tiebreak, the window is ordered by (-created_at, -id), so the sample is
        # stable and predictable. Random UUIDs mean id-desc order differs from insertion order — asserting
        # the id-desc picks fails if the tiebreak is dropped.
        tied_at = datetime.now(UTC) - timedelta(hours=1)
        obs = []
        for i in range(6):
            o = self._observation(f"obs {i}", session_id=f"s{i}")
            ReplayObservation.objects.filter(pk=o.pk).update(created_at=tied_at)
            obs.append(o)
        action = self._action(max_observations=3)
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 3)
        # Ordered by -id (created_at all equal); stride 6/3=2 picks ranks 0, 2, 4 of that order.
        by_id_desc = sorted((str(o.id) for o in obs), reverse=True)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [by_id_desc[0], by_id_desc[2], by_id_desc[4]])

    def test_empty_model_output_skips_without_persisting(self) -> None:
        # An empty generation must not persist synthesized_markdown="" — that would read as "not done"
        # to the idempotency guard and re-bill the LLM on every retry.
        self._observation("something")
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run, llm_content="   \n  ")

        self.assertEqual(result.status, SynthesisStatus.SKIPPED_EMPTY)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")

    def test_idempotent_when_already_synthesized(self) -> None:
        self._observation("something")
        action = self._action()
        run = self._run_for(action)
        run.synthesized_markdown = "already here"
        run.observation_count = 5
        run.save()

        # If the LLM were called, this would raise (OpenAI client patched to blow up).
        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.OpenAI", _no_llm_client),
        ):
            result = _synthesize(SynthesizeGroupSummaryInputs(run_id=run.id, team_id=self.team.id))

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 5)

    @parameterized.expand(
        [
            ("no_consent", SynthesisStatus.ABORTED_NO_CONSENT),
            ("no_creator", SynthesisStatus.ABORTED_NO_USER),
            ("over_budget", SynthesisStatus.SKIPPED_OVER_BUDGET),
            ("empty_window", SynthesisStatus.SKIPPED_EMPTY),
        ]
    )
    def test_short_circuit_gates(self, gate: str, expected: SynthesisStatus) -> None:
        # Each gate must return early without persisting markdown and without ever touching the LLM.
        if gate == "empty_window":
            # First run looks back 24h; a 10-day-old observation falls outside it.
            obs = self._observation("old news")
            ReplayObservation.objects.filter(pk=obs.pk).update(created_at=datetime.now(UTC) - timedelta(days=10))
            action = self._action()
        else:
            self._observation("something")
            action = self._action(created_by=None if gate == "no_creator" else self.user)

        if gate == "no_consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()

        run = self._run_for(action)

        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=(gate == "over_budget")),
            patch(f"{_SYNTH_PATH}.OpenAI", _no_llm_client),
        ):
            result = _synthesize(SynthesizeGroupSummaryInputs(run_id=run.id, team_id=self.team.id))

        self.assertEqual(result.status, expected)
        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")

    def test_only_succeeded_observations_feed_synthesis(self) -> None:
        self._observation("good", session_id="ok")
        # Give the pending observation a well-formed result, so the ONLY reason it's excluded is the
        # status filter (not the model_output guard) — that's what conclusively proves the filter.
        ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="pending",
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.PENDING,
            scanner_result={"model_output": {"summary": "pending but well-formed"}},
        )
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.observation_count, 1)

    def test_summarizes_reasoning_and_outcome_when_no_summary(self) -> None:
        # Non-summarizer scanners (monitor/classifier/scorer) emit `reasoning`, not `summary`. The group
        # summary must fall back to reasoning so those actions don't skip as empty — and must feed the model
        # the actual outcome (verdict/score/tags) too, not just reasoning it would otherwise have to infer.
        ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id="classified",
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={
                "model_output": {
                    "scanner_type": ScannerType.CLASSIFIER,
                    "reasoning": "user abandoned at the payment step",
                    "tags": ["abandoned"],
                }
            },
        )
        action = self._action()
        run = self._run_for(action)

        prompts: list[str] = []
        result = self._synthesize(action, run, captured_prompts=prompts)

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)
        # The observation's outcome (tags) and its reasoning both reach the model.
        self.assertIn("tags=abandoned", prompts[0])
        self.assertIn("user abandoned at the payment step", prompts[0])

    def test_excludes_scanners_the_creator_cannot_read(self) -> None:
        # The action's bound scanner_ids are user-supplied, so synthesis must filter them through the
        # creator's RBAC. Without that a creator could bind a same-team scanner they can't read and pull
        # its recording-derived reasoning/outcome into the summary.
        hidden = ReplayScanner.objects.create(
            team=self.team,
            name="hidden",
            scanner_type=ScannerType.CLASSIFIER,
            scanner_config={"prompt": "classify"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        self._observation("visible scanner output", session_id="visible")
        ReplayObservation.objects.create(
            scanner=hidden,
            session_id="hidden",
            scanner_snapshot=snapshot_for(hidden),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={"model_output": {"scanner_type": ScannerType.CLASSIFIER, "reasoning": "leaked reasoning"}},
        )
        action = self._action(selection={"scanner_ids": [str(self.scanner.id), str(hidden.id)]})
        run = self._run_for(action)

        prompts: list[str] = []
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.filter_queryset_by_access_level",
            side_effect=lambda qs, **_: qs.exclude(pk=hidden.pk),
        ):
            result = self._synthesize(action, run, captured_prompts=prompts)

        self.assertEqual(result.observation_count, 1)
        self.assertIn("visible scanner output", prompts[0])
        self.assertNotIn("leaked reasoning", prompts[0])

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

    def test_first_run_looks_back_24h(self) -> None:
        # No previous run → the window is the last 24h; anything older is excluded.
        self._observation("today", session_id="recent")
        old = self._observation("ancient", session_id="old")
        ReplayObservation.objects.filter(pk=old.pk).update(created_at=datetime.now(UTC) - timedelta(days=2))
        action = self._action()
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)  # only the recent observation

    def test_window_starts_at_previous_completed_run(self) -> None:
        # A prior completed run extends the window back to its scheduled_at, beyond the 24h default.
        action = self._action()
        previous = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="prev",
            status=VisionActionRunStatus.COMPLETED,
            scheduled_at=datetime.now(UTC) - timedelta(days=3),
        )
        previous.save()
        obs = self._observation("two days ago")
        ReplayObservation.objects.filter(pk=obs.pk).update(created_at=datetime.now(UTC) - timedelta(days=2))
        run = self._run_for(action)

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)

    def test_window_excludes_observations_after_this_runs_scheduled_tick(self) -> None:
        # The window is half-open [prev.scheduled_at, this.scheduled_at). An observation created after
        # this run's scheduled tick (during the scheduling/execution lag) is deferred to the next run
        # rather than summarized by both — guarding against double-counting across consecutive runs.
        action = self._action()
        previous = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="prev",
            status=VisionActionRunStatus.COMPLETED,
            scheduled_at=datetime.now(UTC) - timedelta(days=2),
        )
        previous.save()
        in_window = self._observation("inside the window", session_id="in")
        ReplayObservation.objects.filter(pk=in_window.pk).update(created_at=datetime.now(UTC) - timedelta(hours=12))
        after_tick = self._observation("created during execution lag", session_id="after")
        ReplayObservation.objects.filter(pk=after_tick.pk).update(created_at=datetime.now(UTC))

        run = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="k1",
            scheduled_at=datetime.now(UTC) - timedelta(hours=1),
        )
        run.save()

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)  # only the in-window one; the post-tick one waits for next run

    def test_prompt_guide_passed_to_llm(self) -> None:
        self._observation("something")
        action = self._action(synthesis_config={"prompt_guide": "focus on rage clicks"})
        run = self._run_for(action)

        captured: dict = {}

        def _capturing_client(**_kwargs):
            def create(**kwargs):
                captured["human"] = _user_message(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.OpenAI", _capturing_client),
        ):
            _synthesize(SynthesizeGroupSummaryInputs(run_id=run.id, team_id=self.team.id))

        human = captured["human"]
        self.assertIn("focus on rage clicks", human)
        # The guide is a trusted instruction and must lead, so the fenced untrusted observation
        # block stays the last thing the model reads.
        self.assertLess(human.index("focus on rage clicks"), human.index("<observations>"))

    def _typed_observation(self, model_output: dict, session_id: str) -> ReplayObservation:
        return ReplayObservation.objects.create(
            scanner=self.scanner,
            session_id=session_id,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result={"model_output": model_output},
        )

    def test_targeting_verdict_only_feeds_matching_observations(self) -> None:
        matching = self._typed_observation(
            {"scanner_type": "monitor", "verdict": "yes", "reasoning": "user rage clicked"}, session_id="s1"
        )
        self._typed_observation(
            {"scanner_type": "monitor", "verdict": "no", "reasoning": "calm session"}, session_id="s2"
        )
        action = self._action(selection={"verdict": ["yes"]})
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [str(matching.id)])

    def test_targeting_score_bounds_compare_numerically(self) -> None:
        # score 10 must satisfy min_score 9 — catches the jsonb bound regressing to text
        # comparison, where "10" < "9" lexicographically.
        self._typed_observation({"scanner_type": "scorer", "score": 2, "reasoning": "meh"}, session_id="s1")
        high = self._typed_observation({"scanner_type": "scorer", "score": 10, "reasoning": "great"}, session_id="s2")
        action = self._action(selection={"min_score": 9})
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [str(high.id)])

    def test_targeting_tags_match_fixed_or_freeform(self) -> None:
        fixed = self._typed_observation(
            {"scanner_type": "classifier", "tags": ["bug"], "reasoning": "hit a bug"}, session_id="s1"
        )
        freeform = self._typed_observation(
            {"scanner_type": "classifier", "tags": [], "tags_freeform": ["slow"], "reasoning": "felt slow"},
            session_id="s2",
        )
        self._typed_observation({"scanner_type": "classifier", "tags": ["ux"], "reasoning": "ux note"}, session_id="s3")
        action = self._action(selection={"tags": ["bug", "slow"]})
        run = self._run_for(action)

        result = self._synthesize(action, run)

        self.assertEqual(result.observation_count, 2)
        run.refresh_from_db()
        self.assertEqual(set(run.observation_ids), {str(fixed.id), str(freeform.id)})


class TestMarkdownToSlack(BaseTest):
    @parameterized.expand(
        [
            ("h2_heading", "## Big things", "*Big things*"),
            ("h3_heading", "### Small things", "*Small things*"),
            ("bold", "some **strong** text", "*strong*"),
        ]
    )
    def test_markdown_converted_to_slack_mrkdwn(self, _label: str, markdown: str, expected: str) -> None:
        out = _markdown_to_slack(markdown)
        self.assertIn(expected, out)
        self.assertNotIn("#", out)
        self.assertNotIn("**", out)

    def test_truncates_long_text(self) -> None:
        out = _markdown_to_slack("x" * 50_000)
        self.assertLessEqual(len(out), 39_000)
        self.assertIn("truncated", out)

    def test_truncation_does_not_re_expose_defanged_url(self) -> None:
        # A non-PostHog URL straddling SLACK_TEXT_MAX must stay defanged after truncation.
        # If truncation splits a `` `url` `` code span the bare-URL re-run must catch it.
        from products.replay_vision.backend.temporal.vision_actions.synthesis import SLACK_TEXT_MAX

        padding = "a" * (SLACK_TEXT_MAX - 5)
        evil = "https://evil.example.com/exfil"
        out = _markdown_to_slack(padding + evil)
        # The host must not appear as a live (unquoted) URL in the output.
        sanitized = out.replace("`https://evil.example.com/exfil`", "")
        self.assertNotIn("https://evil.example.com/exfil", sanitized)
