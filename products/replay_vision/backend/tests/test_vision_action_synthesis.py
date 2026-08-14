import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner, VisionAction, VisionActionRun
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionActionRunStatus
from products.replay_vision.backend.temporal.vision_actions.synthesis import (
    _CHUNK_SYSTEM_PROMPT,
    SLACK_BLOCK_TEXT_LIMIT,
    _markdown_to_slack,
    _slack_blocks,
    _split_long_line,
    _synthesize,
)
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
            model=ScannerModel.GEMINI_3_7_FLASH,
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
        # Delivery renders the pre-split blocks; a short report is one section block of the same text.
        self.assertEqual(
            run.output["slack_blocks"], [{"type": "section", "text": {"type": "mrkdwn", "text": run.output["slack"]}}]
        )

    def test_labels_each_observation_line_for_citation(self) -> None:
        # Every fed observation line is prefixed with a 1-based `[obs N]` label so the model can cite the
        # observations behind a theme; the frontend resolves those labels back to observation links. A
        # dropped or misaligned label would break that resolution.
        self._observation("Users churned at checkout", title="Checkout")
        self._observation("Onboarding looked smooth", title="Onboarding", session_id="s2")
        action = self._action()
        run = self._run_for(action)

        prompts: list[str] = []
        self._synthesize(action, run, captured_prompts=prompts)

        self.assertIn("[obs 1] (", prompts[0])
        self.assertIn("[obs 2] (", prompts[0])
        self.assertNotIn("[obs 3]", prompts[0])

    def test_slack_renders_citations_as_observation_links(self) -> None:
        # The canonical report keeps the raw `[obs N]` markers for the in-app renderer; the Slack payload
        # resolves them to `<url|[N]>` links so a Slack reader can open the recording behind a cited theme.
        obs = self._observation("Users churned at checkout", title="Checkout")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="Users hit friction at checkout [obs 1].")

        run.refresh_from_db()
        self.assertIn("[obs 1]", run.synthesized_markdown)
        expected_link = f"<{settings.SITE_URL}/project/{self.team.id}/replay-vision/observations/{obs.id}|[1]>"
        self.assertIn(expected_link, run.output["slack"])
        self.assertNotIn("[obs 1]", run.output["slack"])

    def test_slack_drops_unresolvable_citation(self) -> None:
        # A citation the model invents past the observation count can't resolve to a link, so it's dropped
        # rather than emitted as a dead label or a link to the wrong recording.
        self._observation("Users churned at checkout", title="Checkout")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="Friction everywhere [obs 9].")

        run.refresh_from_db()
        self.assertNotIn("[9]", run.output["slack"])
        self.assertNotIn("[obs 9]", run.output["slack"])

    @parameterized.expand(
        [
            ("space_separated", " "),
            ("comma_separated", ", "),
        ]
    )
    def test_caps_runaway_citation_lists(self, _label: str, separator: str) -> None:
        # A theme the model backs with many recordings must not render a wall of citations: an adjacent run
        # is trimmed to a representative handful, keeping the first few. Guards both the in-app markdown and
        # (once it renders links) the Slack payload, since the cap runs on the stored report. The model
        # separates citations with commas as often as spaces — both shapes must count as one run.
        for i in range(10):
            self._observation(f"obs {i}", session_id=f"s{i}")
        action = self._action()
        run = self._run_for(action)

        citations = separator.join(f"[obs {i}]" for i in range(1, 10))  # 9 adjacent citations
        self._synthesize(action, run, llm_content=f"Users hit friction across this flow {citations}.")

        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown.count("[obs "), 6)
        self.assertIn("[obs 1] [obs 2] [obs 3] [obs 4] [obs 5] [obs 6]", run.synthesized_markdown)

    def test_summary_leads_with_scanner_window_and_count_header(self) -> None:
        # The report must always state which scanner it's for, how many recordings it covers, and the
        # window start — prepended in code so it's present regardless of what the LLM returns. The
        # scanner name links to this run's page so both the in-app report and Slack can jump back to it.
        self._observation("Users churned at checkout", title="Checkout")
        self._observation("Onboarding looked smooth", title="Onboarding", session_id="s2")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="# Summary\nThemes.")

        run.refresh_from_db()
        run_url = f"{settings.SITE_URL}/project/{self.team.id}/replay-vision/actions/{action.id}/runs/{run.id}"
        self.assertTrue(
            run.synthesized_markdown.startswith(f"**Summary for [summarizer]({run_url})** — 2 recordings since "),
            run.synthesized_markdown,
        )
        # The linked header rides into the Slack payload too (**bold** → *bold*, [name](url) → <url|name>).
        self.assertIn(f"*Summary for <{run_url}|summarizer>*", run.output["slack"])

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
        self.assertIn("**Summary for [Checkoutflow](", run.synthesized_markdown)

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

    def test_summary_header_name_cannot_break_out_of_the_run_link(self) -> None:
        # _linkify_summary_header wraps the name in [name](run_url) AFTER the external-link strip pass.
        # A name carrying `](url)` would break out of that link and plant a header link to an attacker
        # domain (the "]" arms the injected link once linkify supplies the opening "["). The name's
        # bracket/paren chars must be stripped so the only link the header can point to is the run page.
        self.scanner.name = "Checkout](//attacker.example/)"
        self.scanner.save()
        self._observation("churned")
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run)

        run.refresh_from_db()
        run_url = f"{settings.SITE_URL}/project/{self.team.id}/replay-vision/actions/{action.id}/runs/{run.id}"
        # The header still links, but only to the run page — the attacker domain can't be a link
        # target. It may survive as inert label text; what must not exist is a link pointing at it.
        self.assertIn(f"]({run_url})", run.synthesized_markdown)
        self.assertNotIn("](//attacker.example", run.synthesized_markdown)
        self.assertNotIn("attacker.example|", run.output["slack"])
        self.assertNotIn("<//attacker.example", run.output["slack"])

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
            model=ScannerModel.GEMINI_3_7_FLASH,
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

    def test_explicit_window_overrides_the_derived_window(self) -> None:
        # A "summarize a period" run covers exactly [window_start, window_end): observations before the
        # start or after the end stay out, regardless of when the previous run happened.
        before = self._observation("before the period", session_id="before")
        ReplayObservation.objects.filter(pk=before.pk).update(created_at=datetime.now(UTC) - timedelta(days=40))
        inside = self._observation("inside the period", session_id="inside")
        ReplayObservation.objects.filter(pk=inside.pk).update(created_at=datetime.now(UTC) - timedelta(days=20))
        self._observation("after the period", session_id="after")  # created now, past window_end

        action = self._action()
        run = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="period",
            scheduled_at=datetime.now(UTC),
            window_start=datetime.now(UTC) - timedelta(days=30),
            window_end=datetime.now(UTC) - timedelta(days=1),
        )
        run.save()

        result = self._synthesize(action, run)
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        run.refresh_from_db()
        self.assertEqual(run.observation_ids, [str(inside.id)])

    def test_explicit_window_run_does_not_anchor_the_next_derived_window(self) -> None:
        # A period rollup deliberately overlaps history. If it anchored the next derived window, every
        # observation between the last cadence run and the rollup's trigger time would never appear in
        # a cadence digest.
        action = self._action()
        cadence = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="cadence",
            status=VisionActionRunStatus.COMPLETED,
            scheduled_at=datetime.now(UTC) - timedelta(days=2),
        )
        cadence.save()
        rollup = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="rollup",
            status=VisionActionRunStatus.COMPLETED,
            scheduled_at=datetime.now(UTC) - timedelta(hours=1),
            window_start=datetime.now(UTC) - timedelta(days=30),
            window_end=datetime.now(UTC) - timedelta(hours=1),
        )
        rollup.save()
        obs = self._observation("between cadence runs")
        ReplayObservation.objects.filter(pk=obs.pk).update(created_at=datetime.now(UTC) - timedelta(hours=12))

        run = self._run_for(action)
        result = self._synthesize(action, run)
        # Anchored on the cadence run (2d ago), not the rollup (1h ago), so the 12h-old observation
        # is summarized instead of falling into a gap.
        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 1)

    def test_header_states_the_full_period_for_explicit_window_runs(self) -> None:
        # An explicit window is bounded on both sides, so "since X" would misreport it; the header
        # must state the full period.
        self._observation("in the period")
        action = self._action()
        run = VisionActionRun(
            vision_action=action,
            team=self.team,
            idempotency_key="period",
            scheduled_at=datetime.now(UTC),
            window_start=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            window_end=datetime.now(UTC),
        )
        run.save()

        self._synthesize(action, run)
        run.refresh_from_db()
        self.assertIn("1 recording from Jun 1, 2026 at 9:00 AM UTC to ", run.synthesized_markdown)

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

    def test_summarizer_line_carries_outcome_and_friction_signal(self) -> None:
        # The synthesis line must surface the summarizer's structured outcome + friction status, not just its
        # prose — that explicit signal is what lets the model (and the validator) tell a clean session from an
        # error one. Without it, a successful waitlist signup reads the same as a failed one.
        self._typed_observation(
            {
                "scanner_type": "summarizer",
                "title": "Signup",
                "summary": "User joined the waitlist",
                "outcome": "successfully joined the waitlist",
                "friction_points": [],
            },
            session_id="s1",
        )
        action = self._action()
        run = self._run_for(action)

        prompts: list[str] = []
        self._synthesize(action, run, captured_prompts=prompts)

        self.assertIn("friction: none", prompts[0])
        self.assertIn("outcome: successfully joined the waitlist", prompts[0])

    def test_validation_drops_clean_citation_on_negative_claim(self) -> None:
        # The fabricated-cluster guard: a clean session (friction_points empty, outcome present) cited as
        # evidence of an error is a false citation. It must be stripped from the stored report so a reader
        # who clicks it doesn't land on a success. The surrounding prose is left intact.
        self._typed_observation(
            {
                "scanner_type": "summarizer",
                "title": "Signup",
                "summary": "User joined the waitlist with no problems",
                "outcome": "successfully joined the waitlist",
                "friction_points": [],
            },
            session_id="s1",
        )
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="Some users hit an invalid invite link error [obs 1].")

        run.refresh_from_db()
        self.assertNotIn("[obs 1]", run.synthesized_markdown)
        self.assertIn("invalid invite link error", run.synthesized_markdown)

    def test_validation_keeps_citation_when_observation_reports_friction(self) -> None:
        # A citation that genuinely backs a negative claim (the observation itself reports friction) must be
        # preserved — the validator only removes contradictions, never real evidence.
        self._typed_observation(
            {
                "scanner_type": "summarizer",
                "title": "Broken link",
                "summary": "User could not sign up",
                "outcome": "abandoned after the invite link failed",
                "friction_points": ["invalid invite link"],
            },
            session_id="s1",
        )
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="Some users hit an invalid invite link error [obs 1].")

        run.refresh_from_db()
        self.assertIn("[obs 1]", run.synthesized_markdown)

    def test_validation_keeps_clean_citation_on_non_negative_claim(self) -> None:
        # A clean session cited for a non-negative claim (a success or neutral pattern) is a valid citation —
        # the validator must not touch it. Only error/friction claims trigger the contradiction check.
        self._typed_observation(
            {
                "scanner_type": "summarizer",
                "title": "Signup",
                "summary": "User joined the waitlist",
                "outcome": "successfully joined the waitlist",
                "friction_points": [],
            },
            session_id="s1",
        )
        action = self._action()
        run = self._run_for(action)

        self._synthesize(action, run, llm_content="Many users successfully joined the waitlist [obs 1].")

        run.refresh_from_db()
        self.assertIn("[obs 1]", run.synthesized_markdown)

    def test_run_max_observations_overrides_the_action_cap(self) -> None:
        # The per-run coverage override ("summarize a period" at a chosen tier) must beat the
        # per-action setting — if the cap line drops it, every deep run silently shrinks back to 100.
        for i in range(3):
            self._observation(f"obs {i}", session_id=f"s{i}")
        action = self._action(max_observations=3)
        run = self._run_for(action)
        run.max_observations = 1
        run.save(update_fields=["max_observations"])

        result = self._synthesize(action, run)
        self.assertEqual(result.observation_count, 1)

    def test_run_max_observations_is_clamped_to_the_ceiling(self) -> None:
        # The run-level ceiling bounds every override — without it a crafted run row could queue an
        # unbounded LLM job. Patched small so the test doesn't need thousands of rows.
        for i in range(3):
            self._observation(f"obs {i}", session_id=f"s{i}")
        action = self._action()
        run = self._run_for(action)
        run.max_observations = 5
        run.save(update_fields=["max_observations"])

        with patch(f"{_SYNTH_PATH}.MAX_RUN_OBSERVATIONS", 2):
            result = self._synthesize(action, run)
        self.assertEqual(result.observation_count, 2)


def _first_label(text: str) -> str:
    match = re.search(r"\[obs \d+\]", text)
    assert match is not None, f"no [obs N] label in: {text[:200]}"
    return match.group(0)


class TestChunkedSynthesis(BaseTest):
    """Map-reduce synthesis: batches over the chunk size go through per-chunk digests plus a reduce
    pass, with finished chunk digests cached on the run so a retry never re-bills them."""

    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="summarizer",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "summarize"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        self.action = VisionAction(
            team=self.team,
            name="summary",
            scanner=self.scanner,
            created_by=self.user,
            trigger_config={"rrule": "FREQ=DAILY", "timezone": "UTC"},
        )
        self.action.save()

    def _observations(self, count: int) -> None:
        for i in range(count):
            ReplayObservation.objects.create(
                scanner=self.scanner,
                session_id=f"s{i}",
                scanner_snapshot=snapshot_for(self.scanner),
                triggered_by=ObservationTrigger.SCHEDULE,
                status=ObservationStatus.SUCCEEDED,
                completed_at=timezone.now(),
                scanner_result={
                    "model_output": {"scanner_type": ScannerType.SUMMARIZER, "summary": f"observation body {i}"}
                },
            )

    def _run(self, key: str = "k1") -> VisionActionRun:
        run = VisionActionRun(vision_action=self.action, team=self.team, idempotency_key=key)
        run.save()
        return run

    def _routing_client(
        self, calls: list[tuple[str, str]], reduce_content: str, fail_chunk_with_label: str | None = None
    ) -> Any:
        # Routes on the system prompt: chunk-digest calls use the compressor prompt, everything else
        # is the reduce pass. Chunk responses echo the chunk's first global label so the reduce input
        # (and the resume cache) is attributable per chunk.
        def _create(**kwargs: Any) -> SimpleNamespace:
            system = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
            user = _user_message(kwargs)
            calls.append((system, user))
            if system == _CHUNK_SYSTEM_PROMPT:
                if fail_chunk_with_label is not None and fail_chunk_with_label in user:
                    raise RuntimeError("chunk call failed")
                content = f"- recurring friction, 2 of 2 in this batch {_first_label(user)}"
            else:
                content = reduce_content
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
        return lambda **_kwargs: client

    def _synthesize_with(self, run: VisionActionRun, client: Any) -> Any:
        with (
            patch(f"{_SYNTH_PATH}.is_team_over_ai_credit_budget", return_value=False),
            patch(f"{_SYNTH_PATH}.SYNTHESIS_CHUNK_SIZE", 2),
            patch(f"{_SYNTH_PATH}.OpenAI", client),
        ):
            return _synthesize(SynthesizeGroupSummaryInputs(run_id=run.id, team_id=self.team.id))

    def test_over_chunk_size_runs_chunk_digests_then_one_reduce(self) -> None:
        # 5 observations at chunk size 2 → 3 chunk calls + 1 reduce. If the batch silently went
        # through the flat single pass instead, coverage past the first context would degrade —
        # the regression the map-reduce path exists to prevent.
        self._observations(5)
        run = self._run()
        calls: list[tuple[str, str]] = []

        result = self._synthesize_with(run, self._routing_client(calls, "**TL;DR:** merged themes [obs 3]"))

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        self.assertEqual(result.observation_count, 5)
        chunk_calls = [(s, u) for s, u in calls if s == _CHUNK_SYSTEM_PROMPT]
        reduce_calls = [(s, u) for s, u in calls if s != _CHUNK_SYSTEM_PROMPT]
        self.assertEqual((len(chunk_calls), len(reduce_calls)), (3, 1))
        # Labels are global across chunks (chunk 2 starts at [obs 3]) so reduce citations resolve
        # against the run's full observation_ids list, not a per-chunk numbering.
        self.assertEqual({_first_label(u) for _, u in chunk_calls}, {"[obs 1]", "[obs 3]", "[obs 5]"})
        # The reduce pass reads every chunk digest, fenced as data.
        _, reduce_user = reduce_calls[0]
        for label in ("[obs 1]", "[obs 3]", "[obs 5]"):
            self.assertIn(f"in this batch {label}", reduce_user)
        self.assertIn("<digests>", reduce_user)

        run.refresh_from_db()
        self.assertIn("merged themes", run.synthesized_markdown)
        self.assertIn("5 recordings", run.synthesized_markdown)
        # The reduce citation resolves through the normal Slack pipeline like any single-pass one.
        self.assertIn("|[3]>", run.output["slack"])
        # The final save drops the in-flight chunk cache — it must not linger on completed runs.
        self.assertNotIn("chunk_digests", run.output)

    def test_failed_chunk_persists_finished_digests_and_retry_resumes(self) -> None:
        # An LLM failure mid-fan-out must not lose the chunks that finished: they're billed calls.
        # The retry must serve them from the run's cache and only re-call the failed chunk + reduce.
        self._observations(4)
        run = self._run()
        first_attempt: list[tuple[str, str]] = []

        with self.assertRaises(RuntimeError):
            self._synthesize_with(run, self._routing_client(first_attempt, "unused", fail_chunk_with_label="[obs 3]"))

        run.refresh_from_db()
        self.assertEqual(run.synthesized_markdown, "")
        cached = run.output["chunk_digests"]
        self.assertEqual(len(cached), 1)
        self.assertIn("[obs 1]", next(iter(cached.values())))

        retry_calls: list[tuple[str, str]] = []
        result = self._synthesize_with(run, self._routing_client(retry_calls, "**TL;DR:** recovered [obs 1]"))

        self.assertEqual(result.status, SynthesisStatus.SYNTHESIZED)
        # Only the failed chunk and the reduce ran — the finished chunk came from the cache.
        chunk_users = [u for s, u in retry_calls if s == _CHUNK_SYSTEM_PROMPT]
        self.assertEqual(len(chunk_users), 1)
        self.assertIn("[obs 3]", chunk_users[0])
        reduce_user = next(u for s, u in retry_calls if s != _CHUNK_SYSTEM_PROMPT)
        self.assertIn("in this batch [obs 1]", reduce_user)  # the cached digest fed the reduce
        run.refresh_from_db()
        self.assertIn("recovered", run.synthesized_markdown)
        self.assertNotIn("chunk_digests", run.output)


class TestMarkdownToSlack(BaseTest):
    @parameterized.expand(
        [
            ("h2_heading", "## Big things", "*Big things*"),
            ("h3_heading", "### Small things", "*Small things*"),
            ("bold", "some **strong** text", "*strong*"),
        ]
    )
    def test_markdown_converted_to_slack_mrkdwn(self, _label: str, markdown: str, expected: str) -> None:
        out = _markdown_to_slack(markdown, team_id=self.team.id, observation_ids=[])
        self.assertIn(expected, out)
        self.assertNotIn("#", out)
        self.assertNotIn("**", out)

    def test_truncates_only_past_the_api_cap(self) -> None:
        # Truncation is a last resort against Slack's ~40k chat.postMessage rejection; display
        # splitting is handled by `_slack_blocks`, so ordinary long reports must NOT be cut.
        out = _markdown_to_slack("x" * 50_000, team_id=self.team.id, observation_ids=[])
        self.assertLessEqual(len(out), 39_000)
        self.assertIn("truncated", out)
        untouched = _markdown_to_slack("line\n" * 1_500, team_id=self.team.id, observation_ids=[])
        self.assertNotIn("truncated", untouched)

    def test_truncation_does_not_split_a_citation_link(self) -> None:
        # A citation link straddling the cut point must be dropped whole, not cut in half — a dangling
        # `<https://…` renders as garbage in Slack. The cut backs up to the previous line break.
        from products.replay_vision.backend.temporal.vision_actions.synthesis import SLACK_TEXT_MAX

        obs_id = str(uuid4())
        text = "a" * (SLACK_TEXT_MAX - 50) + "\n" + "More friction at checkout [obs 1] and beyond. " * 5
        out = _markdown_to_slack(text, team_id=self.team.id, observation_ids=[obs_id])
        self.assertLessEqual(len(out), SLACK_TEXT_MAX + 100)
        self.assertIn("truncated", out)
        self.assertEqual(out.count("<"), out.count(">"))
        self.assertNotIn(obs_id[:8], out)  # the straddling link is gone entirely, not half-emitted

    def test_truncation_does_not_re_expose_defanged_url(self) -> None:
        # A non-PostHog URL straddling SLACK_TEXT_MAX must stay defanged after truncation.
        # If truncation splits a `` `url` `` code span the bare-URL re-run must catch it.
        from products.replay_vision.backend.temporal.vision_actions.synthesis import SLACK_TEXT_MAX

        padding = "a" * (SLACK_TEXT_MAX - 5)
        evil = "https://evil.example.com/exfil"
        out = _markdown_to_slack(padding + evil, team_id=self.team.id, observation_ids=[])
        # The host must not appear as a live (unquoted) URL in the output.
        sanitized = out.replace("`https://evil.example.com/exfil`", "")
        self.assertNotIn("https://evil.example.com/exfil", sanitized)

    def test_slack_blocks_split_at_line_boundaries_and_keep_links_whole(self) -> None:
        # Slack auto-splits `text` over ~4k at arbitrary positions, cutting <url|[N]> links in half —
        # the pre-split blocks are what delivery renders instead, so every block must fit Slack's
        # 3,000-char section limit, split only at line breaks, and carry the whole report.
        link = f"<https://us.posthog.com/project/1/replay-vision/observations/{uuid4()}|[1]>"
        paragraph = f"Users hit friction at checkout and abandoned their carts repeatedly. {link}"
        text = "\n".join(paragraph for _ in range(80))  # ~11k characters

        blocks = _slack_blocks(text)

        self.assertGreater(len(blocks), 1)
        for block in blocks:
            self.assertEqual(block["type"], "section")
            self.assertLessEqual(len(block["text"]["text"]), SLACK_BLOCK_TEXT_LIMIT)
            # No half links: every < has its closing > within the same block.
            self.assertEqual(block["text"]["text"].count("<"), block["text"]["text"].count(">"))
        # Nothing dropped: rejoining the blocks reproduces the full report.
        self.assertEqual("\n".join(b["text"]["text"] for b in blocks), text)

    @parameterized.expand(
        [
            ("leading_token", "<https://evil.example/" + "a" * (SLACK_BLOCK_TEXT_LIMIT * 2)),
            ("whitespace_then_token", "   <" + "a" * (SLACK_BLOCK_TEXT_LIMIT * 2)),
        ]
    )
    def test_split_long_line_consumes_unterminated_leading_token(self, _label: str, line: str) -> None:
        # A line opening with an unterminated `<` token longer than the block limit used to make
        # the back-up-before-the-token cut resolve to position 0 — zero forward progress, spinning
        # the synthesis activity forever. The hard-cut guard must always consume input.
        parts = _split_long_line(line)
        self.assertTrue(all(len(p) <= SLACK_BLOCK_TEXT_LIMIT for p in parts))
        self.assertEqual("".join(parts).replace(" ", ""), line.replace(" ", ""))
