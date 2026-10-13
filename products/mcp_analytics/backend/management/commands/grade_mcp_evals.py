"""Grade a saved ``run_mcp_evals`` report against its scenarios, without running the agents again.

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

from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial
from products.mcp_analytics.backend.agent_evals.grading import (
    GradedReport,
    Grader,
    TrialGrade,
    format_grade_summary,
    grade_trial,
    parse_trials,
)
from products.mcp_analytics.backend.agent_evals.model_graders import (
    DEFAULT_JUDGE_MODEL,
    GRADERS,
    GraderSettings,
    GraderUnavailable,
)
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario, load_scenarios


class Command(BaseCommand):
    help = "Grade a saved agent eval report with pluggable graders and write a JSON report."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--report", type=Path, required=True, help="JSON report written by run_mcp_evals.")
        parser.add_argument("--scenarios", type=Path, required=True, help="YAML file of the scenarios that were run.")
        parser.add_argument("--out", type=Path, required=True, help="Where to write the graded JSON report.")
        parser.add_argument(
            "--graders", default=",".join(GRADERS), help=f"Comma-separated, from: {', '.join(GRADERS)}."
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

        raw = json.loads(cast(Path, options["report"]).read_text())
        trials = parse_trials(raw["trials"])
        scenarios = {scenario.id: scenario for scenario in load_scenarios(cast(Path, options["scenarios"])).scenarios}
        missing = sorted({trial.scenario_id for trial in trials} - set(scenarios))
        if missing:
            raise CommandError(f"report has scenario ids missing from the scenarios file: {', '.join(missing)}")

        grader_settings = GraderSettings(
            anthropic_api_key=settings.ANTHROPIC_API_KEY or "", judge_model=cast(str, options["judge_model"])
        )
        graders: dict[str, Grader] = {}
        for name in names:
            try:
                graders[name] = GRADERS[name](grader_settings)
            except GraderUnavailable as unavailable:
                self.stderr.write(f"skipping grader {name}: {unavailable}")
        if not graders:
            raise CommandError("no grader can run")

        grades = asyncio.run(_grade_all(trials, scenarios, graders, concurrency))
        report = GradedReport(
            server_url=raw["server_url"],
            model=raw["model"],
            effort=raw["effort"],
            started_at=raw["started_at"],
            graders=tuple(graders),
            grades=grades,
        )
        out = cast(Path, options["out"])
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
