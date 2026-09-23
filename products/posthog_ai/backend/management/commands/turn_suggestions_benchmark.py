import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import override_settings

from posthog.models import Team

from products.posthog_ai.backend.turn_suggestions.benchmark import (
    CASES_PATH,
    CaseResult,
    Expectation,
    Outcome,
    ThresholdScore,
    best_threshold,
    load_cases,
    run_cases,
    sweep,
)
from products.posthog_ai.backend.turn_suggestions.classifier import SHOW_THRESHOLD, build_draft, card_copy
from products.posthog_ai.backend.turn_suggestions.judgment import JUDGE_MODEL, build_judge_state
from products.posthog_ai.backend.turn_suggestions.verdict import NotebookDraft, OfferKind, ScoutDraft

_MARKS = {
    Outcome.CORRECT: "✓",
    Outcome.FALSE_OFFER: "✗",
    Outcome.MISSED: "✗",
    Outcome.WRONG_KIND: "✗",
    Outcome.EITHER: "~",
    Outcome.FAILED: "!",
}


def _percent(value: float | None) -> str:
    return "  -" if value is None else f"{value * 100:3.0f}%"


def _api_key_from_env_local() -> str | None:
    env_local = Path(settings.BASE_DIR) / ".env.local"
    if not env_local.is_file():
        return None
    for line in env_local.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "TYPESAFE_API_KEY" and value.strip():
            return value.strip()
    return None


class Command(BaseCommand):
    help = (
        "Run the labeled turn suggestion cases through live Jev, print each verdict as it arrives, "
        "and score the policy across show thresholds."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--threshold",
            type=float,
            default=SHOW_THRESHOLD,
            help=f"Show threshold for the per-case verdicts (default {SHOW_THRESHOLD}).",
        )
        parser.add_argument("--case", action="append", default=[], help="Only run cases whose name contains this.")
        parser.add_argument("--category", action="append", default=[], help="Only run cases in this category.")
        parser.add_argument("--workers", type=int, default=8, help="Parallel Jev requests (default 8).")
        parser.add_argument("--cases-file", type=Path, default=CASES_PATH, help="YAML file with the cases.")
        parser.add_argument("--state", action="store_true", help="Print the masked state Jev reads for each case.")
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Also ask the language model to write the scout or notebook text for picked offers.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        api_key = settings.TYPESAFE_API_KEY or _api_key_from_env_local()
        if not api_key:
            raise CommandError("Set TYPESAFE_API_KEY in the environment or in .env.local.")
        with override_settings(TYPESAFE_API_KEY=api_key):
            self._run(options)

    def _run(self, options: dict[str, Any]) -> None:
        threshold: float = options["threshold"]
        cases = [
            case
            for case in load_cases(options["cases_file"])
            if (not options["case"] or any(needle in case.name for needle in options["case"]))
            and (not options["category"] or case.category in options["category"])
        ]
        if not cases:
            raise CommandError("No case matches those filters.")

        self.stdout.write(f"Judging {len(cases)} cases with {JUDGE_MODEL} at show threshold {threshold}\n\n")
        team_id = self._team_id() if options["draft"] else 0

        def on_result(result: CaseResult) -> None:
            self._print_result(result, threshold)
            if options["state"]:
                state = json.dumps(build_judge_state(result.case.transcript), indent=2, ensure_ascii=False)
                self.stdout.write(self.style.HTTP_INFO("\n".join(f"    {line}" for line in state.splitlines())))
            if options["draft"]:
                self._print_draft(result, threshold, team_id)

        results = run_cases(cases, workers=options["workers"], on_result=on_result)
        self._print_distribution(results)
        self._print_sweep(sweep(results), threshold)

    def _team_id(self) -> int:
        team = Team.objects.order_by("id").first()
        if team is None:
            raise CommandError("--draft needs a team in the local database to attribute the language model calls.")
        return team.id

    def _print_result(self, result: CaseResult, threshold: float) -> None:
        case = result.case
        outcome = result.outcome(threshold)
        want = "nothing" if case.expectation == Expectation.NOTHING else "|".join(sorted(case.acceptable))
        line = f"{_MARKS[outcome]} {case.name:28} want {want:24}"
        judgment = result.judgment
        if judgment is None:
            self.stdout.write(self.style.ERROR(f"{line} Jev request failed"))
            return
        picked = result.picked(threshold)
        probabilities = " · ".join(
            f"{kind} {probability:.2f}"
            for kind, probability in sorted(judgment.offer_probabilities.items(), key=lambda item: -item[1])
            if probability >= 0.01
        )
        line += f" got {picked:12} show {judgment.show_probability:.2f}   {probabilities}   {result.seconds:.1f}s"
        style = {
            Outcome.CORRECT: self.style.SUCCESS,
            Outcome.EITHER: self.style.WARNING,
        }.get(outcome, self.style.ERROR)
        self.stdout.write(style(line))

    def _print_draft(self, result: CaseResult, threshold: float, team_id: int) -> None:
        judgment = result.judgment
        picked = result.picked(threshold)
        if judgment is None or picked == OfferKind.NONE:
            return
        draft = build_draft(picked, judgment, result.case.transcript, team_id=team_id, today=datetime.now(UTC).date())
        if draft is None:
            self.stdout.write(self.style.ERROR("    The draft failed, so the card would not show."))
            return
        copy = card_copy(draft)
        lines = [f"    {copy.title}", f"    {copy.description}"]
        match draft:
            case ScoutDraft():
                lines += [f"    Scout: {draft.display_name} ({draft.mode}, {draft.cadence})", ""]
                lines += [f"      {line}" for line in draft.body.splitlines()]
            case NotebookDraft():
                lines += [f"    Notebook: {draft.title}", f"      {draft.summary}"]
                if draft.incident is not None:
                    lines += [f"      Cause: {draft.incident.cause}", f"      Fix: {draft.incident.fix}"]
        self.stdout.write("\n".join(lines) + "\n")

    def _print_distribution(self, results: Sequence[CaseResult]) -> None:
        self.stdout.write("\nShow probability by label\n")
        for expectation, label in (
            (Expectation.OFFER, "should offer"),
            (Expectation.EITHER, "either is fine"),
            (Expectation.NOTHING, "should not offer"),
        ):
            values = sorted(
                result.judgment.show_probability
                for result in results
                if result.judgment is not None and result.case.expectation == expectation
            )
            self.stdout.write(f"  {label:17} {' '.join(f'{value:.2f}' for value in values) or '-'}")

    def _print_sweep(self, scores: Sequence[ThresholdScore], threshold: float) -> None:
        best = best_threshold(scores)
        self.stdout.write("\nthreshold  offer rate  precision  recall    F1   false offers  missed  wrong kind")
        for entry in scores:
            f1 = f"{entry.f1:.2f}" if entry.f1 is not None else "   -"
            row = (
                f"  {entry.threshold:.2f}       {_percent(entry.offer_rate)}       {_percent(entry.precision)}"
                f"     {_percent(entry.recall)}   {f1}   {entry.false_offers:12}  {entry.missed:6}  {entry.wrong_kind:10}"
            )
            notes = [
                note
                for note, applies in (("current", entry.threshold == threshold), ("best F1", entry is best))
                if applies
            ]
            self.stdout.write(row + (f"   <- {', '.join(notes)}" if notes else ""))
        if best is not None:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nBest F1 at {best.threshold:.2f}. A tie goes to the higher threshold, which shows fewer cards."
                )
            )
        self.stdout.write(
            "Offer rate counts every case. The cases lean toward offers compared with real traffic, "
            "so expect a lower rate in production."
        )
