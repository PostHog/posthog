import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.ml_inference.backend.facade import api
from products.ml_inference.backend.facade.contracts import (
    DEFAULT_DECISION_MODEL,
    DecisionQuestion,
    DecisionRequest,
    DecisionsDisabledError,
)


class Command(BaseCommand):
    help = "Ask the decision model questions about one state through the AI gateway and print the answers as JSON."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        state = parser.add_mutually_exclusive_group(required=True)
        state.add_argument("--state", help="the state text; use --state-file for anything long")
        state.add_argument("--state-file", type=Path)
        parser.add_argument(
            "--questions-json",
            required=True,
            help='a JSON object of questions, e.g. {"urgent": {"type": "noul", "instructions": "Is this urgent?"}}',
        )
        parser.add_argument("--model", default=DEFAULT_DECISION_MODEL)
        parser.add_argument("--force", action="store_true", help="ask even when the team's feature flag is off")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        state = self._state(options)
        questions = self._questions(options["questions_json"])
        decision = DecisionRequest(team_id=team_id, state=state, questions=questions, model=options["model"])
        try:
            result = api.decide_unchecked(decision) if options["force"] else api.decide(decision)
        except DecisionsDisabledError as error:
            raise CommandError(f"{error}; pass --force to ask anyway") from error
        self.stdout.write(
            json.dumps(
                {
                    "model": result.model,
                    "answers": {question_id: answer.__dict__ for question_id, answer in result.answers.items()},
                    "input_tokens": result.input_tokens,
                    "latency_ms": result.latency_ms,
                },
                indent=2,
            )
        )

    def _state(self, options: dict[str, Any]) -> str:
        if options["state_file"] is not None:
            return Path(options["state_file"]).read_text()
        return str(options["state"])

    def _questions(self, raw: str) -> dict[str, DecisionQuestion]:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as error:
            raise CommandError(f"--questions-json is not valid JSON: {error}") from error
        if not isinstance(decoded, dict):
            raise CommandError("--questions-json must be a JSON object keyed by question id")
        questions: dict[str, DecisionQuestion] = {}
        for question_id, question in decoded.items():
            if not isinstance(question, dict):
                raise CommandError(f"question {question_id!r} must be an object with type and instructions")
            try:
                questions[question_id] = DecisionQuestion(**question)
            except (TypeError, ValueError) as error:
                raise CommandError(f"question {question_id!r} is invalid: {error}") from error
        return questions
