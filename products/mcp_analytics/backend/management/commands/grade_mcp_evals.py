"""Grade a saved ``run_mcp_evals`` report against the scenarios it ran, without running the agents again.

The same trials can be graded again by other graders to compare them. ``jev`` sends the request,
the success criteria and the agent's answer to a System One model. On TypeSafe, which is approved
only for experiments that send no customer data, grade runs against synthetic or PostHog-owned
projects.
"""

import json
import asyncio
from pathlib import Path
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from pydantic import TypeAdapter, ValidationError

from posthog.egress.typesafe import JEV_LATEST

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.grading import (
    GradedReport,
    Grader,
    TrialGrade,
    format_grade_summary,
    grade_trial,
)
from products.mcp_analytics.backend.agent_evals.model_graders import (
    DEFAULT_GRADERS,
    DEFAULT_JUDGE_MODEL,
    GRADERS,
    GraderSettings,
    GraderUnavailable,
)
from products.mcp_analytics.backend.agent_evals.runner import AgentRunReport
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario


class Command(BaseCommand):
    help = "Grade a saved agent eval report with pluggable graders and write a JSON report."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--report", type=Path, required=True, help="JSON report written by run_mcp_evals.")
        parser.add_argument("--out", type=Path, required=True, help="Where to write the graded JSON report.")
        parser.add_argument(
            "--graders",
            default=",".join(DEFAULT_GRADERS),
            help=f"Comma-separated, from: {', '.join(GRADERS)}. jev runs only when named.",
        )
        parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
        parser.add_argument("--concurrency", type=int, default=4)

    def handle(self, *args: object, **options: object) -> None:
        concurrency = cast(int, options["concurrency"])
        if concurrency <= 0:
            raise CommandError("--concurrency must be a positive integer")
        names = [name.strip() for name in cast(str, options["graders"]).split(",") if name.strip()]
        unknown = sorted(set(names) - set(GRADERS))
        if unknown:
            raise CommandError(f"unknown graders: {', '.join(unknown)}")
        report_path, out = cast(Path, options["report"]), cast(Path, options["out"])
        if out.resolve() == report_path.resolve():
            raise CommandError("--out would overwrite the report being graded")

        try:
            run = TypeAdapter(AgentRunReport).validate_json(report_path.read_bytes())
        except ValidationError as invalid:
            raise CommandError(f"{report_path} is not a run_mcp_evals report: {invalid}") from invalid
        scenarios = {scenario.id: scenario for scenario in run.scenarios}
        missing = sorted({trial.scenario_id for trial in run.trials} - set(scenarios))
        if missing:
            raise CommandError(f"report has trials for scenarios it does not record: {', '.join(missing)}")

        judge_model = cast(str, options["judge_model"])
        grader_settings = GraderSettings(anthropic_api_key=settings.ANTHROPIC_API_KEY or "", judge_model=judge_model)
        graders: dict[str, Grader] = {}
        for name in names:
            try:
                graders[name] = GRADERS[name](grader_settings)
            except GraderUnavailable as unavailable:
                self.stderr.write(f"skipping grader {name}: {unavailable}")
        if not graders:
            raise CommandError("no grader can run")

        models = {"expected_tools": "deterministic", "judge": judge_model, "jev": JEV_LATEST}
        report = GradedReport(
            server_origin=run.server_origin,
            model=run.model,
            effort=run.effort,
            started_at=run.started_at,
            grader_models={name: models[name] for name in graders},
            grades=asyncio.run(_grade_all(run.trials, scenarios, graders, concurrency)),
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2))
        self.stdout.write(f"{format_grade_summary(report)}\nwrote {out}")


async def _grade_all(
    trials: tuple[AgentTrial, ...], scenarios: dict[str, Scenario], graders: dict[str, Grader], concurrency: int
) -> tuple[TrialGrade, ...]:
    slots = asyncio.Semaphore(concurrency)

    async def bounded(trial: AgentTrial) -> TrialGrade:
        async with slots:
            return await grade_trial(scenarios[trial.scenario_id], trial, graders)

    return tuple(await asyncio.gather(*(bounded(trial) for trial in trials)))
