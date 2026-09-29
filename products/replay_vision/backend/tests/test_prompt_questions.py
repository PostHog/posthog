import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

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
    MAX_QUESTION_CHARS,
    TEMPLATE_QUESTIONS,
    backfill_prompt_questions,
    condense_prompt,
)
from products.replay_vision.backend.tests.helpers import snapshot_for

TEMPLATE_PROMPT, TEMPLATE_QUESTION = next(iter(TEMPLATE_QUESTIONS.items()))
PROMPT = "Did the user struggle to complete checkout?\n\nAnswer yes if they retried the payment form."
LONG_FIRST_LINE = "Look at " + "the checkout flow and " * 20


def _model_says(client: MagicMock, question: str) -> None:
    client.return_value.models.generate_content.side_effect = None
    client.return_value.models.generate_content.return_value = MagicMock(text=json.dumps({"question": question}))


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
            ("model_answer", "Did the user struggle at checkout?", PROMPT, True, "Did the user struggle at checkout?"),
            ("not_a_question", "Checkout struggles", PROMPT, True, "Did the user struggle to complete checkout?"),
            (
                "too_long",
                "Did " + "x" * MAX_QUESTION_CHARS + "?",
                PROMPT,
                True,
                "Did the user struggle to complete checkout?",
            ),
            ("model_error", None, PROMPT, True, "Did the user struggle to complete checkout?"),
            (
                "no_ai_consent",
                "Did the user struggle at checkout?",
                PROMPT,
                False,
                "Did the user struggle to complete checkout?",
            ),
            (
                "long_first_line_is_cut",
                None,
                LONG_FIRST_LINE,
                True,
                LONG_FIRST_LINE[: MAX_QUESTION_CHARS - 1].rstrip() + "…",
            ),
            ("empty_prompt", "Did anything happen?", "   ", True, ""),
            ("template_needs_no_call", "Did anything happen?", TEMPLATE_PROMPT, False, TEMPLATE_QUESTION),
        ]
    )
    def test_condense_prompt(self, _name: str, reply: str | None, prompt: str, consent: bool, expected: str) -> None:
        if reply is None:
            self.client_mock.return_value.models.generate_content.side_effect = RuntimeError("provider down")
        else:
            _model_says(self.client_mock, reply)
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save()

        question = condense_prompt(team_id=self.team.id, scanner_type="monitor", scanner_config={"prompt": prompt})

        assert question.question == expected
        assert question.source == prompt_fingerprint(prompt)
        if not consent:
            self.client_mock.return_value.models.generate_content.assert_not_called()

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

    def test_observation_shows_the_question_only_for_the_prompt_it_was_scanned_with(self) -> None:
        scanner = self._scanner(prompt_question="Did the user struggle at checkout?")
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

        ReplayScanner.objects.filter(pk=scanner.pk).update(
            scanner_config={"prompt": "Did the user abandon their cart?"},
            prompt_question="Did the user abandon their cart?",
            prompt_question_source=prompt_fingerprint("Did the user abandon their cart?"),
        )
        assert self.client.get(url).json()["prompt_question"] is None

    def test_backfill_fills_only_stale_questions_without_touching_the_scanner_version(self) -> None:
        stale = self._scanner(name="stale")
        copy = self._scanner(name="copy")
        template = self._scanner(name="template", scanner_config={"prompt": TEMPLATE_PROMPT})
        ReplayScanner.objects.filter(pk__in=[stale.pk, copy.pk, template.pk]).update(
            prompt_question="", prompt_question_source=""
        )
        fresh = self._scanner(name="fresh")
        ReplayScanner.objects.filter(pk=fresh.pk).update(
            prompt_question="Kept as is?", prompt_question_source=prompt_fingerprint(PROMPT)
        )
        version = ReplayScanner.objects.get(pk=stale.pk).scanner_version

        dry = backfill_prompt_questions(team_id=self.team.id, dry_run=True)
        assert (dry.checked, dry.written) == (4, 3)
        assert ReplayScanner.objects.get(pk=stale.pk).prompt_question == ""
        self.client_mock.return_value.models.generate_content.reset_mock()

        result = backfill_prompt_questions(team_id=self.team.id)

        assert result.written == 3
        # The copy shares the stale scanner's prompt and the template needs none, so one call covers all three.
        assert self.client_mock.return_value.models.generate_content.call_count == 1
        assert ReplayScanner.objects.get(pk=copy.pk).prompt_question == "Did the user struggle at checkout?"
        assert ReplayScanner.objects.get(pk=template.pk).prompt_question == TEMPLATE_QUESTION
        stale.refresh_from_db()
        assert stale.prompt_question == "Did the user struggle at checkout?"
        assert stale.prompt_question_source == prompt_fingerprint(PROMPT)
        assert stale.scanner_version == version
        assert ReplayScanner.objects.get(pk=fresh.pk).prompt_question == "Kept as is?"
