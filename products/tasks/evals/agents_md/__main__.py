# ruff: noqa: T201
import os
import sys
import json
import hashlib
import argparse
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from posthog.dataclasses import frozen

from products.tasks.evals.golden_prs.agents import DEFAULT_MODELS, AgentOutcome, Runtime, run_agent
from products.tasks.evals.golden_prs.scoring import changed_files
from products.tasks.evals.golden_prs.workspace import candidate_diff

from .claims import ARMS, REPO_ROOT, Arm, Claim, agents_md_for, build_prompt, load_claims, select_claims
from .cloud import CLOUD_RUNTIME, CloudAgent, CloudRuntime, TasksClient
from .detectors import DEFAULT_JUDGE_MODEL, Candidate, Detection, TaskAssessment, TaskStatus, assess_task, detect
from .workspace import agents_md_at, checkout_with_agents_md, resolve_ref

DEFAULT_RESULTS_DIR = Path(__file__).with_name("results")
DEFAULT_CASE_TIMEOUT_SECONDS = 15 * 60
DEFAULT_MODEL_MATRIX: tuple[tuple[Runtime, str], ...] = (
    ("claude", "claude-opus-5-5"),
    ("claude", "claude-fable-5-1"),
    ("claude", "claude-sonnet-5-5"),
    ("codex", "gpt-6-astra"),
    ("codex", "gpt-6-sol"),
)


@dataclass(frozen=True, kw_only=True, slots=True)
class Job:
    claim: Claim
    arm: Arm
    repeat: int

    @property
    def name(self) -> str:
        return f"{self.claim.id}-{self.arm}-{self.repeat}"


@dataclass(frozen=True, kw_only=True, slots=True)
class JobResult:
    claim: str
    section: str
    rule: str
    arm: str
    repeat: int
    runtime: str
    model: str
    agent_version: str
    judge_model: str
    ref: str
    started_at: str
    duration_seconds: float
    exit_code: int
    timed_out: bool
    failure: str | None
    violations: float | None
    details: list[str]
    usage: dict[str, float | int]
    changed_files: list[str]
    comparison: str = "rule"
    instructions_sha256: str = ""
    task_assessment: TaskStatus = "unmeasured"
    task_assessment_detail: str = "No task assessment was recorded."
    hooks_disabled: bool = False


@frozen
class Evaluation:
    result: JobResult
    diff: str
    agent_log: str


@frozen
class ModelJob:
    runtime: Runtime | CloudRuntime
    model: str
    job: Job


def evaluate(
    job: Job,
    agents_md: str,
    runtime: Runtime | CloudRuntime,
    model: str,
    judge_model: str,
    timeout_seconds: int,
    repo: Path,
    ref: str,
    candidate_agents_md: str | None = None,
    cloud: CloudAgent | None = None,
) -> Evaluation:
    prompt = build_prompt(job.claim)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    variant = agents_md_for(agents_md, job.claim, job.arm, candidate_agents_md)
    with checkout_with_agents_md(repo, ref, variant) as workdir:
        if runtime == CLOUD_RUNTIME:
            if cloud is None:
                raise ValueError(f"The {CLOUD_RUNTIME} runtime needs a cloud agent.")
            outcome = cloud.run(
                model=model, prompt=prompt, agents_md=variant, workdir=workdir, timeout_seconds=timeout_seconds
            )
        else:
            outcome = AgentOutcome.from_run(
                run_agent(runtime, model, prompt, workdir, timeout_seconds, disable_hooks=True)
            )
        candidate = Candidate.from_diff(candidate_diff(workdir), workdir, reply=outcome.reply)
        failure = outcome.failure
        environment_changes = candidate.changed_files(".flox/*")
        if environment_changes:
            failure = f"Environment setup files changed: {', '.join(environment_changes)}"
        if failure:
            detection = Detection(violations=None, details=(failure,))
            assessment = TaskAssessment(status="unmeasured", reasoning=failure)
        else:
            detection = detect(candidate, job.claim, judge_model)
            assessment = assess_task(candidate, job.claim, model=judge_model)
    result = JobResult(
        claim=job.claim.id,
        section=job.claim.section,
        rule=job.claim.text,
        arm=job.arm,
        repeat=job.repeat,
        runtime=runtime,
        model=model,
        agent_version=outcome.agent_version,
        judge_model=judge_model,
        ref=ref,
        started_at=started_at,
        duration_seconds=outcome.duration_seconds,
        exit_code=outcome.exit_code,
        timed_out=outcome.timed_out,
        failure=failure,
        violations=detection.violations,
        details=list(detection.details),
        usage=outcome.usage,
        changed_files=sorted(changed_files(candidate.diff)),
        comparison="file" if candidate_agents_md is not None else "rule",
        instructions_sha256=hashlib.sha256(variant.encode()).hexdigest(),
        task_assessment=assessment.status,
        task_assessment_detail=assessment.reasoning,
        hooks_disabled=runtime == "claude",
    )
    return Evaluation(result=result, diff=candidate.diff, agent_log=outcome.log)


def write_result(results_dir: Path, name: str, result: JobResult, candidate: str, agent_log: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{name}.diff").write_text(candidate)
    (results_dir / f"{name}.agent.log").write_text(agent_log)
    temporary = results_dir / f"{name}.json.tmp"
    temporary.write_text(json.dumps(asdict(result), indent=2))
    temporary.replace(results_dir / f"{name}.json")


def load_results(results_dir: Path) -> list[dict]:
    return sorted(
        (json.loads(path.read_text()) for path in results_dir.rglob("*.json")),
        key=lambda r: (r["runtime"], r["model"], r["claim"], r["arm"], r["repeat"]),
    )


def _arm_mean(results: list[dict]) -> str:
    measured = [r["violations"] for r in results if r["violations"] is not None]
    if not measured:
        return "n/a"
    return f"{mean(measured):.2f} (n={len(measured)})"


def _delta(results: list[dict]) -> float | None:
    by_arm = {
        arm: [r["violations"] for r in results if r["arm"] == arm and r["violations"] is not None] for arm in ARMS
    }
    if not by_arm["with"] or not by_arm["without"]:
        return None
    return mean(by_arm["without"]) - mean(by_arm["with"])


def _broken(results: list[dict]) -> bool:
    return any(r["violations"] for r in results)


def _effect(results: list[dict]) -> str:
    delta = _delta(results)
    if delta is None:
        return "n/a"
    if not _broken(results):
        return "no evidence"
    return f"{delta:+.2f}"


def _helped(results: list[dict]) -> str:
    """How many repeats the rule won, pairing each with-run against the without-run of the same repeat."""
    by_repeat: dict[int, dict[str, float]] = defaultdict(dict)
    for r in results:
        if r["violations"] is not None:
            by_repeat[r["repeat"]][r["arm"]] = r["violations"]
    pairs = [arms for arms in by_repeat.values() if len(arms) == 2]
    won = sum(1 for arms in pairs if arms["without"] > arms["with"])
    return f"{won} of {len(pairs)}"


def _largest_effect_first(item: tuple[str, list[dict]]) -> float:
    delta = _delta(item[1])
    return float("-inf") if delta is None else delta


def report(results: list[dict]) -> str:
    """One table per agent: violations with the rule, without it, and the difference the rule makes."""
    if not results:
        return "No results found.\n"
    comparisons = {r.get("comparison", "rule") for r in results}
    if len(comparisons) != 1:
        raise ValueError("Report rule removal and whole-file comparisons separately.")
    file_comparison = comparisons == {"file"}
    with_label = "Candidate file" if file_comparison else "With rule"
    without_label = "Current file" if file_comparison else "Without rule"
    effect_label = "Current minus candidate" if file_comparison else "Rule effect"
    successful = [r for r in results if not r.get("failure") and not r.get("timed_out") and not r.get("exit_code")]
    excluded = len(results) - len(successful)
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for result in successful:
        by_agent[f"{result['runtime']} {result['model']}"].append(result)
    sections: list[str] = []
    for agent, agent_results in sorted(by_agent.items()):
        by_claim: dict[str, list[dict]] = defaultdict(list)
        for result in agent_results:
            by_claim[result["claim"]].append(result)
        rows = [
            f"| {claim} | {claim_results[0]['section']} "
            f"| {_arm_mean([r for r in claim_results if r['arm'] == 'with'])} "
            f"| {_arm_mean([r for r in claim_results if r['arm'] == 'without'])} "
            f"| {_effect(claim_results)} | {_helped(claim_results)} |"
            for claim, claim_results in sorted(by_claim.items(), key=_largest_effect_first, reverse=True)
        ]
        header = f"| Claim | Section | {with_label} | {without_label} | {effect_label} | Repeats won |\n|---|---|---|---|---|---|\n"
        table = "\n".join(rows)
        sections.append(f"### {agent}\n\n{header}{table}\n")
        assessment_counts = {
            status: sum(r.get("task_assessment", "unmeasured") == status for r in agent_results)
            for status in ("issues_found", "no_issues_found", "unmeasured")
        }
        sections.append(
            "Task assessment (separate from rule scores): "
            + ", ".join(f"{status}: {count}" for status, count in assessment_counts.items())
            + ".\n"
        )
    comparison_description = (
        "Current minus candidate is positive when the candidate has fewer detected violations in these samples. "
        if file_comparison
        else "Rule effect is without minus with: positive means fewer detected violations with the rule in these samples. "
    )
    return (
        "\n".join(sections)
        + "\nViolations are the detector's count per run, averaged over repeats. "
        + comparison_description
        + f"Repeats won counts the repeats where {without_label.lower()} had a higher detector score than {with_label.lower()}. "
        "These comparisons do not establish statistical confidence or task correctness. "
        "Task assessments are model reviews, not executed tests; no_issues_found does not establish correctness. "
        "Other instructions, skills, and repository examples remain available in both arms.\n"
        + _untempted_traps(successful)
        + (f"\nExcluded {excluded} failed run(s) from detector summaries.\n" if excluded else "")
    )


def _untempted_traps(results: list[dict]) -> str:
    """A rule nobody breaks in either arm says nothing about the rule, only about the trap."""
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        by_claim[result["claim"]].append(result)
    quiet = sorted(
        claim
        for claim, claim_results in by_claim.items()
        if any(r["violations"] is not None for r in claim_results) and not _broken(claim_results)
    )
    if not quiet:
        return ""
    return (
        "\nNo violations were detected in the available results for these claims: "
        f"{', '.join(quiet)}. This does not show that the rules are unnecessary.\n"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents_md", description="Measure whether each AGENTS.md rule changes what an agent does."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Print the claims and their detectors.")
    run = commands.add_parser("run", help="Run each claim's trap task with and without its rule, and count violations.")
    run.add_argument("--claim", action="append", help="Claim id to run. Repeatable. Default: every testable claim.")
    run.add_argument("--arm", action="append", choices=ARMS, help="Arm to run. Repeatable. Default: both.")
    run.add_argument("--repeats", type=int, default=1, help="Runs per claim and arm.")
    run.add_argument("--workers", type=int, default=2, help="Agents to run at the same time.")
    run.add_argument(
        "--runtime",
        choices=("claude", "codex", CLOUD_RUNTIME),
        default="claude",
        help=f"{CLOUD_RUNTIME} runs each job as a PostHog Code cloud task and needs POSTHOG_PERSONAL_API_KEY.",
    )
    run.add_argument("--model", help=f"Agent model. Defaults: {DEFAULT_MODELS}. {CLOUD_RUNTIME} has no default.")
    run.add_argument("--matrix", action="store_true", help="Run the standard five-model comparison set.")
    run.add_argument("--dry-run", action="store_true", help="List jobs without calling agents or judges.")
    run.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    run.add_argument("--case-timeout", type=int, default=DEFAULT_CASE_TIMEOUT_SECONDS, help="Seconds per run.")
    run.add_argument("--ref", default="HEAD", help="The commit whose tree and AGENTS.md the agent works on.")
    run.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    run.add_argument("--repo", type=Path, default=REPO_ROOT)
    run.add_argument("--posthog-host", default="https://us.posthog.com", help=f"Where {CLOUD_RUNTIME} starts tasks.")
    run.add_argument("--project-id", type=int, default=2, help=f"The project {CLOUD_RUNTIME} starts tasks in.")
    run.add_argument(
        "--repository", default="PostHog/posthog", help=f"The GitHub repository {CLOUD_RUNTIME} tasks clone."
    )
    run.add_argument(
        "--git-remote", default="origin", help=f"The remote in --repo that {CLOUD_RUNTIME} pushes branches to."
    )
    run.add_argument(
        "--candidate-agents-md",
        type=Path,
        help="Compare this complete file against the file at --ref. With is candidate; without is current.",
    )
    show = commands.add_parser("report", help="Print a markdown summary of results.")
    show.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser.parse_args(argv)


def jobs_for(
    claims: list[Claim], models: tuple[tuple[Runtime | CloudRuntime, str], ...], arms: list[Arm] | None, repeats: int
) -> list[ModelJob]:
    return [
        ModelJob(runtime=runtime, model=agent_model, job=Job(claim=claim, arm=arm, repeat=repeat))
        for repeat in range(1, repeats + 1)
        for claim in claims
        for runtime, agent_model in models
        for arm in (arms or (ARMS if repeat % 2 else ARMS[::-1]))
    ]


def agent_label(runtime: str, model: str) -> str:
    """A single path segment, since open model ids such as `zai-org/glm-5.3` contain a slash."""
    return f"{runtime}-{model}".replace("/", "_")


def cloud_agent(args: argparse.Namespace, ref: str) -> CloudAgent:
    api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
    if not api_key:
        raise SystemExit(f"The {CLOUD_RUNTIME} runtime needs POSTHOG_PERSONAL_API_KEY with the task:write scope.")
    tasks = TasksClient(args.posthog_host, args.project_id, api_key)
    return CloudAgent(tasks, args.repo, ref, repository=args.repository, remote=args.git_remote)


def run_claims(args: argparse.Namespace, selected: list[Claim]) -> int:
    if args.matrix and args.model:
        raise SystemExit("Use --matrix or --model, not both.")
    if args.runtime == CLOUD_RUNTIME and not args.model:
        raise SystemExit(f"The {CLOUD_RUNTIME} runtime needs --model.")
    model = args.model or DEFAULT_MODELS[args.runtime]
    models = DEFAULT_MODEL_MATRIX if args.matrix else ((args.runtime, model),)
    jobs = jobs_for(selected, models, args.arm, args.repeats)
    if args.dry_run:
        for item in jobs:
            print(f"{item.runtime} {item.model} {item.job.name}")
        return 0
    ref = resolve_ref(args.repo, args.ref)
    agents_md = agents_md_at(args.repo, ref)
    candidate_agents_md = args.candidate_agents_md.read_text() if args.candidate_agents_md else None
    label = "matrix" if args.matrix else agent_label(args.runtime, model)
    results_dir = args.results_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{label}"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "current-agents.md").write_text(agents_md)
    if candidate_agents_md is not None:
        (results_dir / "candidate-agents.md").write_text(candidate_agents_md)
    print(f"{len(jobs)} runs at {ref[:12]}, {args.workers} at a time", flush=True)
    cloud = cloud_agent(args, ref) if args.runtime == CLOUD_RUNTIME else None

    def run_job(item: ModelJob) -> bool:
        name = f"{agent_label(item.runtime, item.model)}/{item.job.name}"
        print(f"{name}: running", flush=True)
        try:
            evaluation = evaluate(
                item.job,
                agents_md,
                item.runtime,
                item.model,
                args.judge_model,
                args.case_timeout,
                args.repo,
                ref,
                candidate_agents_md,
                cloud,
            )
        except Exception:
            print(f"{name}: crashed\n{traceback.format_exc()}", flush=True)
            return False
        result = evaluation.result
        write_result(
            results_dir / agent_label(item.runtime, item.model),
            item.job.name,
            result,
            evaluation.diff,
            evaluation.agent_log,
        )
        outcome = "n/a" if result.violations is None else f"{result.violations:.0f}"
        print(f"{name}: violations {outcome}" + (f" ({result.failure})" if result.failure else ""), flush=True)
        return result.exit_code == 0 and not result.timed_out and result.failure is None

    # The pool would otherwise hold a crash until iteration, after every other job has run.
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            completed = list(pool.map(run_job, jobs))
    finally:
        if cloud:
            cloud.close()
    print(f"\nResults in {results_dir}\n")
    print(report(load_results(results_dir)))
    return 0 if all(completed) else 1


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.command == "report":
        print(report(load_results(args.results_dir)))
        return 0
    claims = load_claims()
    if args.command == "list":
        for claim in claims:
            status = (
                f"untestable: {claim.untestable}" if claim.untestable else ", ".join(d["name"] for d in claim.detectors)
            )
            print(f"{claim.id}\t{claim.section}\t{status}")
        return 0
    selected = (
        select_claims(claims, dict.fromkeys(args.claim))
        if args.claim
        else [claim for claim in claims if claim.testable]
    )
    untestable = [claim.id for claim in selected if not claim.testable]
    if untestable:
        raise SystemExit(f"These claims have no trap task: {untestable}")
    return run_claims(args, selected)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
