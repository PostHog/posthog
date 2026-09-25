import os
import json
import time
import statistics
from collections import Counter
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
    BenchmarkCase,
    CaseResult,
    Expectation,
    JudgeRun,
    Outcome,
    SystemOneEndpoint,
    ThresholdScore,
    agreement,
    best_threshold,
    closest_to_offer_rate,
    disagreements,
    load_cases,
    on_shared_cases,
    parse_endpoints,
    run_cases,
    score,
    sweep,
    sweep_thresholds,
)
from products.posthog_ai.backend.turn_suggestions.classifier import SHOW_THRESHOLD, build_draft, card_copy
from products.posthog_ai.backend.turn_suggestions.judgment import build_judge_state, judge_model
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


def _f1(value: float | None) -> str:
    return "   -" if value is None else f"{value:.2f}"


ENDPOINTS_VARIABLE = "TURN_SUGGESTIONS_BENCHMARK_ENDPOINTS"
_SERVER_SETTINGS = ("AI_GATEWAY_URL", "AI_GATEWAY_API_KEY", "TYPESAFE_API_KEY")
DEFAULT_TARGET_OFFER_RATE = 0.45

# A judge is Jev through the configured System One server (no endpoint) or one candidate endpoint.
type Judge = tuple[str, SystemOneEndpoint | None]


def _from_env_local(name: str) -> str | None:
    env_local = Path(settings.BASE_DIR) / ".env.local"
    if not env_local.is_file():
        return None
    for line in env_local.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name and value.strip():
            return value.strip()
    return None


def _judges(options: dict[str, Any], jev_label: str | None) -> list[Judge]:
    judges: list[Judge] = []
    if not options["skip_jev"]:
        if jev_label is None:
            raise CommandError(
                "Set AI_GATEWAY_URL and AI_GATEWAY_API_KEY, or TYPESAFE_API_KEY, in the environment or in "
                ".env.local, or pass --skip-jev."
            )
        judges.append((jev_label, None))
    if options["jev_only"]:
        return judges
    # Flags replace the variable, so one run can try an endpoint without editing the environment.
    value = " ".join(options["endpoint"]) or os.environ.get(ENDPOINTS_VARIABLE) or _from_env_local(ENDPOINTS_VARIABLE)
    try:
        endpoints = parse_endpoints(value or "")
    except ValueError as error:
        raise CommandError(str(error)) from None
    for endpoint in endpoints:
        label = endpoint.label
        # Two specs can share a host and a model, so number the repeats to keep the columns apart.
        taken = {existing for existing, _ in judges}
        if label in taken:
            label = next(f"{label} #{index}" for index in range(2, len(judges) + 2) if f"{label} #{index}" not in taken)
        judges.append((label, endpoint))
    if not judges:
        raise CommandError(f"--skip-jev needs at least one endpoint in {ENDPOINTS_VARIABLE} or --endpoint.")
    if len(judges) > 1 and (options["state"] or options["draft"]):
        raise CommandError("--state and --draft work with one judge only.")
    return judges


class Command(BaseCommand):
    help = (
        "Run the labeled turn suggestion cases through live Jev, or through candidate System One endpoints, "
        "and score the policy across show thresholds. With more than one judge, compare them side by side. "
        f"{ENDPOINTS_VARIABLE} in the environment or in .env.local lists the endpoints, separated by spaces, "
        "commas, or semicolons. Each one is http[s]://[username:password@]host[:port][/path][#model]. "
        "The path defaults to /v1/systemone, and the fragment names the model to send."
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
        parser.add_argument("--workers", type=int, default=8, help="Parallel requests per judge (default 8).")
        parser.add_argument("--cases-file", type=Path, default=CASES_PATH, help="YAML file with the cases.")
        parser.add_argument("--state", action="store_true", help="Print the masked state Jev reads for each case.")
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Also ask the language model to write the scout or notebook text for picked offers.",
        )
        parser.add_argument(
            "--endpoint",
            action="append",
            default=[],
            metavar="URL",
            help=(
                "Also judge with this System One URL, in the same form as "
                f"{ENDPOINTS_VARIABLE}. Repeat it to compare several. It replaces the variable for this run."
            ),
        )
        judge_choice = parser.add_mutually_exclusive_group()
        judge_choice.add_argument("--skip-jev", action="store_true", help="Judge with the endpoints only.")
        judge_choice.add_argument(
            "--jev-only", action="store_true", help=f"Ignore {ENDPOINTS_VARIABLE} and judge with Jev."
        )
        parser.add_argument(
            "--target-offer-rate",
            type=float,
            default=DEFAULT_TARGET_OFFER_RATE,
            help=(
                "Find each judge's show threshold whose offer rate over the cases lands nearest this share "
                f"(default {DEFAULT_TARGET_OFFER_RATE}). With more than one judge, compare the judges there."
            ),
        )
        parser.add_argument(
            "--sweep",
            action="store_true",
            help="With more than one judge, also print each judge's full threshold sweep.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # The ai-gateway answers where it is configured, and TypeSafe elsewhere, as in production.
        servers = {name: getattr(settings, name) or _from_env_local(name) or "" for name in _SERVER_SETTINGS}
        with override_settings(**servers):
            judges = _judges(options, judge_model())
            for label, endpoint in judges:
                if endpoint is not None and endpoint.sends_credentials_in_clear:
                    self.stderr.write(
                        self.style.WARNING(f"{label} gets its username and password over plain http. Use https:// ")
                        + self.style.WARNING("unless the network to that host is trusted.")
                    )
            self._run(options, judges)

    def _run(self, options: dict[str, Any], judges: list[Judge]) -> None:
        threshold: float = options["threshold"]
        if not 0 <= threshold <= 1:
            raise CommandError("--threshold is a probability between 0 and 1, such as 0.5.")
        if not 0 <= options["target_offer_rate"] <= 1:
            raise CommandError("--target-offer-rate is a share between 0 and 1, such as 0.45.")
        try:
            all_cases = load_cases(options["cases_file"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        cases = [
            case
            for case in all_cases
            if (not options["case"] or any(needle in case.name for needle in options["case"]))
            and (not options["category"] or case.category in options["category"])
        ]
        if not cases:
            raise CommandError("No case matches those filters.")
        if len(judges) == 1:
            self._run_one(options, cases, judges[0], threshold)
        else:
            self._run_comparison(options, cases, judges, threshold)

    def _run_one(self, options: dict[str, Any], cases: list[BenchmarkCase], judge: Judge, threshold: float) -> None:
        label, endpoint = judge
        self.stdout.write(f"Judging {len(cases)} cases with {label} at show threshold {threshold}\n\n")
        team_id = self._team_id() if options["draft"] else 0

        def on_result(result: CaseResult) -> None:
            self._print_result(result, threshold)
            if options["state"]:
                state = json.dumps(build_judge_state(result.case.transcript), indent=2, ensure_ascii=False)
                self.stdout.write(self.style.HTTP_INFO("\n".join(f"    {line}" for line in state.splitlines())))
            if options["draft"]:
                self._print_draft(result, threshold, team_id)

        results = run_cases(cases, workers=options["workers"], on_result=on_result, endpoint=endpoint)
        self._print_distribution(results)
        self._print_sweep(sweep(results, sweep_thresholds(threshold)), threshold)
        target: float = options["target_offer_rate"]
        closest = closest_to_offer_rate(results, target)
        if closest is not None:
            f1 = _f1(closest.f1).strip()
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nClosest to a {_percent(target).strip()} offer rate: threshold {closest.threshold:.2f} offers on "
                    f"{_percent(closest.offer_rate).strip()} of cases, with precision {_percent(closest.precision).strip()}, "
                    f"recall {_percent(closest.recall).strip()}, and F1 {f1}."
                )
            )

    def _run_comparison(
        self, options: dict[str, Any], cases: list[BenchmarkCase], judges: list[Judge], threshold: float
    ) -> None:
        self.stdout.write(f"Judging {len(cases)} cases with {len(judges)} judges at show threshold {threshold}\n")
        width = max(len(label) for label, _ in judges)
        runs = []
        for label, endpoint in judges:
            started = time.monotonic()
            results = run_cases(cases, workers=options["workers"], on_result=lambda _: None, endpoint=endpoint)
            failed = [result for result in results if result.judgment is None]
            line = f"  {label:{width}}  {len(results) - len(failed)} judged, {len(failed)} failed, {time.monotonic() - started:.0f}s"
            self.stdout.write(self.style.ERROR(line) if failed else line)
            # One repeated error, such as a 401, usually explains every failure, so print each distinct one once.
            errors = Counter(result.error or "Jev request failed" for result in failed)
            for error, count in errors.most_common():
                self.stdout.write(self.style.ERROR(f"    {count}x {error}"))
            runs.append(JudgeRun(label=label, results=tuple(results)))

        answered = [run for run in runs if any(result.judgment is not None for result in run.results)]
        for run in runs:
            if run not in answered:
                self.stdout.write(self.style.ERROR(f"\n{run.label} answered no case, so the tables leave it out."))
        if not answered:
            return
        scored = on_shared_cases(answered)
        shared = len(scored[0].results)
        if shared < len(cases):
            self.stdout.write(
                self.style.WARNING(f"\nThe scores cover the {shared} of {len(cases)} cases every judge answered.")
            )
        if not shared:
            return
        self._print_summary(answered, scored, threshold, width)
        target: float = options["target_offer_rate"]
        matched = self._print_target(scored, target, width)
        if len(scored) > 1:
            self._print_disagreements(
                scored, matched, f"each at its threshold for a {_percent(target).strip()} offer rate"
            )
        if options["sweep"]:
            for run in scored:
                self.stdout.write(self.style.MIGRATE_HEADING(f"\n{run.label}"))
                self._print_sweep(sweep(run.results, sweep_thresholds(threshold)), threshold)

    def _print_summary(
        self, runs: Sequence[JudgeRun], scored: Sequence[JudgeRun], threshold: float, width: int
    ) -> None:
        reference = scored[0]
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nScores at show threshold {threshold}"))
        self.stdout.write(
            f"  {'judge':{width}}  failed  offer rate  precision  recall    F1   best F1       agrees   median"
        )
        for run, scored_run in zip(runs, scored):
            current = score(scored_run.results, threshold)
            best = best_threshold(sweep(scored_run.results, sweep_thresholds(threshold)))
            failed = sum(1 for result in run.results if result.judgment is None)
            f1 = _f1(current.f1)
            best_f1 = f"{best.f1:.2f} at {best.threshold:.2f}" if best is not None and best.f1 is not None else "-"
            agrees = (
                "    -"
                if scored_run is reference
                else f"{_percent(agreement(scored_run, threshold, reference, threshold))} "
            )
            # A failed request often waits out the timeout, which says nothing about how fast the judge answers.
            # Another judge's failures leave this judge's answers in, so the median reads every one of them.
            answered = [result.seconds for result in run.results if result.judgment is not None]
            median = f"{statistics.median(answered):5.1f}s" if answered else "     -"
            self.stdout.write(
                f"  {run.label:{width}}  {failed:6}     {_percent(current.offer_rate)}       {_percent(current.precision)}"
                f"     {_percent(current.recall)}   {f1}   {best_f1:12}  {agrees}   {median}"
            )
        self.stdout.write(
            f"\n  agrees: the share of cases where the judge picks the same offer as {reference.label}. "
            "best F1: the judge's best score across thresholds, with the threshold that gets it. "
            "median: the latency of answered requests."
        )

    def _print_target(self, runs: Sequence[JudgeRun], target: float, width: int) -> list[float]:
        """Prints each judge's scores at the threshold nearest the target offer rate, and returns those thresholds."""
        reference = runs[0]
        matched = [closest_to_offer_rate(run.results, target) for run in runs]
        thresholds = [entry.threshold if entry is not None else 1.0 for entry in matched]
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nClosest to a {_percent(target).strip()} offer rate"))
        self.stdout.write(
            f"  {'judge':{width}}  threshold  offer rate  precision  recall    F1   false offers  missed  wrong kind  agrees"
        )
        for run, entry, run_threshold in zip(runs, matched, thresholds):
            if entry is None:
                continue
            f1 = _f1(entry.f1)
            agrees = (
                "    -"
                if run is reference
                else _percent(agreement(run, run_threshold, reference, thresholds[0])).rjust(5)
            )
            self.stdout.write(
                f"  {run.label:{width}}  {entry.threshold:9.2f}     {_percent(entry.offer_rate)}       "
                f"{_percent(entry.precision)}     {_percent(entry.recall)}   {f1}   {entry.false_offers:12}  "
                f"{entry.missed:6}  {entry.wrong_kind:10}  {agrees}"
            )
        self.stdout.write(
            "\n  Compare judges here rather than at one shared threshold, because two models can calibrate their "
            "show probability differently. The case file leans toward offers, so the same threshold offers less "
            "often on real traffic."
        )
        return thresholds

    def _print_disagreements(self, runs: Sequence[JudgeRun], thresholds: Sequence[float], at: str) -> None:
        rows = disagreements(runs, thresholds)
        total = len(runs[0].results)
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nCases where the judges pick differently, {at} ({len(rows)} of {total})")
        )
        if not rows:
            self.stdout.write("  Every judge picks the same offer on every case.")
            return
        widths = [max(len(run.label), 18) for run in runs]
        name_width = max(len(row[0].case.name) for row in rows)
        header = f"  {'case':{name_width}} {'want':24}" + "".join(f"  {run.label:{w}}" for run, w in zip(runs, widths))
        self.stdout.write(header)
        for row in rows:
            case = row[0].case
            want = case.want_label
            cells = "".join(
                f"  {self._cell(result, threshold):{w}}" for result, threshold, w in zip(row, thresholds, widths)
            )
            self.stdout.write(f"  {case.name:{name_width}} {want:24}{cells}".rstrip())
        self.stdout.write(
            "\n  ✓ good pick   ✗ wrong pick   ~ either is fine   ! failed. The number is the show probability."
        )

    def _cell(self, result: CaseResult, threshold: float) -> str:
        if result.judgment is None:
            return "! failed"
        return f"{_MARKS[result.outcome(threshold)]} {result.picked(threshold)} {result.judgment.show_probability:.2f}"

    def _team_id(self) -> int:
        team = Team.objects.order_by("id").first()
        if team is None:
            raise CommandError("--draft needs a team in the local database to attribute the language model calls.")
        return team.id

    def _print_result(self, result: CaseResult, threshold: float) -> None:
        case = result.case
        outcome = result.outcome(threshold)
        want = case.want_label
        line = f"{_MARKS[outcome]} {case.name:28} want {want:24}"
        judgment = result.judgment
        if judgment is None:
            self.stdout.write(self.style.ERROR(f"{line} judge request failed {result.error or ''}".rstrip()))
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
            f1 = _f1(entry.f1)
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
