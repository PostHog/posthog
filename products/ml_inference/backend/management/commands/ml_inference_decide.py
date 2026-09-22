import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.ml_inference.backend.facade import api
from products.ml_inference.backend.facade.contracts import DEFAULT_DECISION_MODEL, DecisionQuestion, DecisionRequest


class Command(BaseCommand):
    help = "Ask the decision model questions about one state through the AI gateway and print the answers as JSON."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--state", help="the state text; use --state-file for anything long")
        parser.add_argument("--state-file", type=Path)
        parser.add_argument(
            "--questions-json",
            required=True,
            help='a JSON object of questions, e.g. {"urgent": {"type": "noul", "instructions": "Is this urgent?"}}',
        )
        parser.add_argument("--model", default=DEFAULT_DECISION_MODEL)
        parser.add_argument("--force", action="store_true", help="ask even when the team's feature flag is off")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        if not options["force"] and not api.decisions_enabled(team_id):
            raise CommandError(f"decisions are not enabled for team {team_id}; pass --force to ask anyway")
        state = self._state(options)
        questions = {
            question_id: DecisionQuestion(**question)
            for question_id, question in json.loads(options["questions_json"]).items()
        }
        result = api.decide(DecisionRequest(team_id=team_id, state=state, questions=questions, model=options["model"]))
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
        if options["state"] is None:
            raise CommandError("pass --state or --state-file")
        return str(options["state"])
