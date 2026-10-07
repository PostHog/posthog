import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.replay_vision.backend.inline_scan import create_inline_scanner
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    ScannerModel,
    ScannerType,
    prompt_fingerprint,
)
from products.replay_vision.backend.prompt_questions import (
    MAX_MODEL_CALLS_PER_TEAM_PER_HOUR,
    MAX_QUESTION_CHARS,
    TEMPLATE_QUESTIONS,
    _budget_key,
    backfill_prompt_questions,
    condense_prompt,
    scanner_question,
)
from products.replay_vision.backend.tests.helpers import snapshot_for

TEMPLATE_PROMPT, (TEMPLATE_QUESTION, _) = next(iter(TEMPLATE_QUESTIONS.items()))
PROMPT = "Did the user struggle to complete checkout?\n\nAnswer yes if they retried the payment form."
LONG_FIRST_LINE = "Look at " + "the checkout flow and " * 20


def _model_says(client: MagicMock, question: str, valence: str = "bad") -> None:
    client.return_value.models.generate_content.side_effect = None
    client.return_value.models.generate_content.return_value = MagicMock(
        text=json.dumps({"question": question, "valence": valence})
    )


class TestPromptQuestions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        estimate = patch("products.replay_vision.backend.api.scanners.refresh_scanner_estimate")
        estimate.start()
        self.addCleanup(estimate.stop)
        client = patch("products.replay_vision.backend.prompt_questions.genai.Client")
        self.client_mock = client.start()
        self.addCleanup(client.stop)
        _model_says(self.client_mock, "Did the user struggle at checkout?")

    @property
    def scanners_url(self) -> str:
        return f"/api/projects/{self.team.id}/vision/scanners/"

    def _scanner(self, **overrides: Any) -> ReplayScanner:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "checkout",
            "scanner_type": ScannerType.MONITOR,
            "scanner_config": {"prompt": PROMPT},
            "model": ScannerModel.GEMINI_3_8_FLASH,
            **overrides,
        }
        return ReplayScanner.objects.create(**fields)

    @parameterized.expand(
        [
            (
                "model_answer",
                "Did the user struggle at checkout?",
                PROMPT,
                True,
                "Did the user struggle at checkout?",
                "bad",
            ),
            (
                "not_a_question_keeps_valence",
                "Checkout struggles",
                PROMPT,
                True,
                "Did the user struggle to complete checkout?",
                "bad",
            ),
            (
                "too_long",
                "Did " + "x" * MAX_QUESTION_CHARS + "?",
                PROMPT,
                True,
                "Did the user struggle to complete checkout?",
                "bad",
            ),
            ("model_error", None, PROMPT, True, "Did the user struggle to complete checkout?", ""),
            ("client_setup_fails", "setup-fails", PROMPT, True, "Did the user struggle to complete checkout?", ""),
            (
                "no_ai_consent",
                "Did the user struggle at checkout?",
                PROMPT,
                False,
                "Did the user struggle to complete checkout?",
                "",
            ),
            (
                "long_first_line_is_cut",
                None,
                LONG_FIRST_LINE,
                True,
                LONG_FIRST_LINE[: MAX_QUESTION_CHARS - 1].rstrip() + "…",
                "",
            ),
            ("empty_prompt", "Did anything happen?", "   ", True, "", ""),
            ("template_needs_no_call", "Did anything happen?", TEMPLATE_PROMPT, False, TEMPLATE_QUESTION, "bad"),
        ]
    )
    def test_condense_prompt(
        self,
        _name: str,
        reply: str | None,
        prompt: str,
        consent: bool,
        expected: str,
        expected_valence: str,
    ) -> None:
        if reply is None:
            self.client_mock.return_value.models.generate_content.side_effect = RuntimeError("provider down")
        elif reply == "setup-fails":
            self.client_mock.side_effect = ValueError("missing API key")
        else:
            _model_says(self.client_mock, reply)
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()

        question = condense_prompt(team_id=self.team.id, scanner_type="monitor", scanner_config={"prompt": prompt})

        assert question.question == expected
        assert (question.valence or "") == expected_valence
        assert question.source == prompt_fingerprint(prompt)
        if not consent:
            self.client_mock.return_value.models.generate_content.assert_not_called()

    def test_team_over_its_hourly_budget_falls_back_without_a_model_call(self) -> None:
        cache.set(_budget_key(self.team.id), MAX_MODEL_CALLS_PER_TEAM_PER_HOUR, timeout=3600)
        self.addCleanup(cache.delete, _budget_key(self.team.id))

        question = condense_prompt(team_id=self.team.id, scanner_type="monitor", scanner_config={"prompt": PROMPT})

        assert question.question == "Did the user struggle to complete checkout?"
        self.client_mock.return_value.models.generate_content.assert_not_called()

    @parameterized.expand(
        [
            ("matches_the_prompt", "Did the user struggle at checkout?", PROMPT, "Did the user struggle at checkout?"),
            (
                "written_for_another_prompt",
                "Did the user abandon their cart?",
                "Other prompt",
                "Did the user struggle to complete checkout?",
            ),
            ("none_yet", "", "", "Did the user struggle to complete checkout?"),
        ]
    )
    def test_scanner_question_only_trusts_a_question_for_the_current_prompt(
        self, _name: str, question: str, source_prompt: str, expected: str
    ) -> None:
        scanner = self._scanner()
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            prompt_question=question, prompt_question_source=prompt_fingerprint(source_prompt) if source_prompt else ""
        )
        scanner.refresh_from_db()

        assert scanner_question(scanner) == expected

    def test_scanner_writes_keep_the_question_in_step_with_the_prompt(self) -> None:
        created = self.client.post(
            self.scanners_url,
            data={
                "name": "checkout",
                "scanner_type": ScannerType.MONITOR,
                "scanner_config": {"prompt": PROMPT},
                "model": ScannerModel.GEMINI_3_8_FLASH,
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        scanner = ReplayScanner.objects.get(id=created.json()["id"])
        assert scanner.prompt_question == "Did the user struggle at checkout?"
        assert scanner.prompt_question_source == prompt_fingerprint(PROMPT)

        calls = self.client_mock.return_value.models.generate_content.call_count
        renamed = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"name": "renamed"}, format="json")
        assert renamed.status_code == 200, renamed.json()
        assert self.client_mock.return_value.models.generate_content.call_count == calls

        _model_says(self.client_mock, "Did the user abandon their cart?")
        edited = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"scanner_config": {"prompt": "Did the user abandon their cart?"}},
            format="json",
        )
        assert edited.status_code == 200, edited.json()
        scanner.refresh_from_db()
        assert scanner.prompt_question == "Did the user abandon their cart?"
        assert scanner.prompt_question_source == prompt_fingerprint("Did the user abandon their cart?")

    def test_scale_label_edit_judges_the_valence_again(self) -> None:
        _model_says(self.client_mock, "How frustrated did the user appear?", valence="bad")
        config: dict[str, Any] = {"prompt": PROMPT, "scale": {"min": 0, "max": 10, "label": "frustration"}}
        created = self.client.post(
            self.scanners_url,
            data={
                "name": "mood",
                "scanner_type": ScannerType.SCORER,
                "scanner_config": config,
                "model": ScannerModel.GEMINI_3_8_FLASH,
            },
            format="json",
        )
        assert created.status_code == 201, created.json()

        _model_says(self.client_mock, "How satisfied did the user appear?", valence="good")
        config["scale"]["label"] = "satisfaction"
        edited = self.client.patch(
            f"{self.scanners_url}{created.json()['id']}/", data={"scanner_config": config}, format="json"
        )
        assert edited.status_code == 200, edited.json()
        scanner = ReplayScanner.objects.get(id=created.json()["id"])
        assert (scanner.prompt_question, scanner.prompt_valence) == ("How satisfied did the user appear?", "good")

    def test_observation_shows_the_question_only_for_the_prompt_it_was_scanned_with(self) -> None:
        scanner = self._scanner(prompt_question="Did the user struggle at checkout?", prompt_valence="bad")
        scanner.prompt_question_source = prompt_fingerprint(PROMPT)
        scanner.save()
        observation = ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id="session-1",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        url = f"/api/projects/{self.team.id}/vision/observations/{observation.id}/"

        assert self.client.get(url).json()["prompt_question"] == "Did the user struggle at checkout?"
        assert self.client.get(url).json()["prompt_valence"] == "bad"

        ReplayScanner.objects.filter(pk=scanner.pk).update(
            scanner_config={"prompt": "Did the user abandon their cart?"},
            prompt_question="Did the user abandon their cart?",
            prompt_question_source=prompt_fingerprint("Did the user abandon their cart?"),
        )
        assert self.client.get(url).json()["prompt_question"] is None
        assert self.client.get(url).json()["prompt_valence"] is None

    def test_backfill_fills_only_stale_questions_without_touching_the_scanner_version(self) -> None:
        stale = self._scanner(name="stale")
        copy = self._scanner(name="copy")
        template = self._scanner(name="template", scanner_config={"prompt": TEMPLATE_PROMPT})
        ReplayScanner.objects.filter(pk__in=[stale.pk, copy.pk, template.pk]).update(
            prompt_question="", prompt_question_source=""
        )
        fresh = self._scanner(name="fresh")
        ReplayScanner.objects.filter(pk=fresh.pk).update(
            prompt_question="Kept as is?", prompt_question_source=prompt_fingerprint(PROMPT), prompt_valence="good"
        )
        unjudged = self._scanner(name="unjudged")
        ReplayScanner.objects.filter(pk=unjudged.pk).update(
            prompt_question="Judged before valence?", prompt_question_source=prompt_fingerprint(PROMPT)
        )
        version = ReplayScanner.objects.get(pk=stale.pk).scanner_version

        dry = backfill_prompt_questions(team_id=self.team.id, dry_run=True)
        assert (dry.checked, dry.written) == (5, 4)
        assert ReplayScanner.objects.get(pk=stale.pk).prompt_question == ""
        self.client_mock.return_value.models.generate_content.reset_mock()

        result = backfill_prompt_questions(team_id=self.team.id)

        assert result.written == 4
        # The copy shares the stale scanner's call and the template needs none; the unjudged scanner sends its kept question.
        calls = self.client_mock.return_value.models.generate_content.call_args_list
        assert ["Judged before valence?" in call.kwargs["contents"] for call in calls] == [False, True]
        assert ReplayScanner.objects.get(pk=copy.pk).prompt_question == "Did the user struggle at checkout?"
        assert ReplayScanner.objects.get(pk=template.pk).prompt_question == TEMPLATE_QUESTION
        stale.refresh_from_db()
        assert stale.prompt_question == "Did the user struggle at checkout?"
        assert stale.prompt_question_source == prompt_fingerprint(PROMPT)
        assert stale.scanner_version == version
        assert ReplayScanner.objects.get(pk=fresh.pk).prompt_question == "Kept as is?"
        unjudged.refresh_from_db()
        assert (unjudged.prompt_question, unjudged.prompt_valence) == ("Judged before valence?", "bad")

    def test_backfill_never_shares_an_answer_across_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        scale = {"min": 0, "max": 10, "label": "checkout friction"}
        ours = self._scanner(scanner_type=ScannerType.SCORER, scanner_config={"prompt": PROMPT, "scale": scale})
        theirs = self._scanner(
            team=other_team, scanner_type=ScannerType.SCORER, scanner_config={"prompt": PROMPT, "scale": scale}
        )
        ReplayScanner.all_origins.filter(pk__in=[ours.pk, theirs.pk]).update(
            prompt_question="", prompt_question_source=""
        )

        backfill_prompt_questions()

        assert self.client_mock.return_value.models.generate_content.call_count == 2

    def test_backfill_retries_the_model_for_each_scanner_after_a_failed_call(self) -> None:
        unjudged = self._scanner(name="unjudged")
        retried = self._scanner(name="retried")
        ReplayScanner.objects.filter(pk__in=[unjudged.pk, retried.pk]).update(
            prompt_question="Judged before valence?", prompt_question_source=prompt_fingerprint(PROMPT)
        )
        reply = MagicMock(text=json.dumps({"question": "Did the user struggle at checkout?", "valence": "bad"}))
        self.client_mock.return_value.models.generate_content.side_effect = [RuntimeError("provider down"), reply]

        result = backfill_prompt_questions(team_id=self.team.id)

        assert result.written == 1
        unjudged.refresh_from_db()
        retried.refresh_from_db()
        assert (unjudged.prompt_question, unjudged.prompt_valence) == ("Judged before valence?", "")
        assert (retried.prompt_question, retried.prompt_valence) == ("Judged before valence?", "bad")

    def test_inline_scanners_only_ever_get_a_template_question(self) -> None:
        self.client_mock.return_value.models.generate_content.reset_mock()
        summarize = create_inline_scanner(
            team=self.team,
            key="summarize-button",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": TEMPLATE_PROMPT},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        custom = create_inline_scanner(
            team=self.team,
            key="one-off",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "Did the user open the pricing page?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        assert (summarize.prompt_question, custom.prompt_question) == (TEMPLATE_QUESTION, "")
        ReplayScanner.all_origins.filter(pk=summarize.pk).update(prompt_question="", prompt_question_source="")

        result = backfill_prompt_questions(team_id=self.team.id, include_inline=True)

        assert result.written == 1
        assert ReplayScanner.all_origins.get(pk=summarize.pk).prompt_question == TEMPLATE_QUESTION
        assert ReplayScanner.all_origins.get(pk=custom.pk).prompt_question == ""
        self.client_mock.return_value.models.generate_content.assert_not_called()
