# ruff: noqa: T201
import sys
import json
import argparse
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from products.tasks.evals.golden_prs.agents import DEFAULT_MODELS, Runtime, agent_failure, agent_usage, run_agent
from products.tasks.evals.golden_prs.scoring import changed_files
from products.tasks.evals.golden_prs.workspace import candidate_diff

from .claims import ARMS, REPO_ROOT, Arm, Claim, agents_md_for, build_prompt, load_claims, select_claims
from .detectors import DEFAULT_JUDGE_MODEL, Candidate, detect
from .workspace import agents_md_at, checkout_with_agents_md, resolve_ref

DEFAULT_RESULTS_DIR = Path(__file__).with_name("results")
DEFAULT_CASE_TIMEOUT_SECONDS = 15 * 60


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


def evaluate(
    job: Job,
    agents_md: str,
    runtime: Runtime,
    model: str,
    judge_model: str,
    timeout_seconds: int,
    repo: Path,
    ref: str,
) -> tuple[JobResult, str, str]:
    prompt = build_prompt(job.claim)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    variant = agents_md_for(agents_md, job.claim, job.arm)
    with checkout_with_agents_md(repo, ref, variant) as workdir:
        run = run_agent(runtime, model, prompt, workdir, timeout_seconds)
        candidate = Candidate.from_diff(candidate_diff(workdir), workdir)
        detection = detect(candidate, job.claim, judge_model)
    result = JobResult(
        claim=job.claim.id,
        section=job.claim.section,
        rule=job.claim.text,
        arm=job.arm,
        repeat=job.repeat,
        runtime=runtime,
        model=model,
        agent_version=run.agent_version,
        judge_model=judge_model,
        ref=ref,
        started_at=started_at,
        duration_seconds=run.duration_seconds,
        exit_code=run.exit_code,
        timed_out=run.timed_out,
        failure=agent_failure(run),
        violations=detection.violations,
        details=list(detection.details),
        usage=agent_usage(run),
        changed_files=sorted(changed_files(candidate.diff)),
    )
    return result, candidate.diff, run.stdout + run.stderr


def write_result(results_dir: Path, name: str, result: JobResult, candidate: str, agent_log: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{name}.json").write_text(json.dumps(asdict(result), indent=2))
    (results_dir / f"{name}.diff").write_text(candidate)
    (results_dir / f"{name}.agent.log").write_text(agent_log)


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


def _effect(results: list[dict]) -> str:
    delta = _delta(results)
    return "n/a" if delta is None else f"{delta:+.2f}"


def _largest_effect_first(item: tuple[str, list[dict]]) -> float:
    delta = _delta(item[1])
    return float("-inf") if delta is None else delta


def report(results: list[dict]) -> str:
    """One table per agent: violations with the rule, without it, and the difference the rule makes."""
    if not results:
        return "No results found.\n"
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for result in results:
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
            f"| {_effect(claim_results)} |"
            for claim, claim_results in sorted(by_claim.items(), key=_largest_effect_first, reverse=True)
        ]
        header = "| Claim | Section | With rule | Without rule | Rule effect |\n|---|---|---|---|---|\n"
        sections.append(f"### {agent}\n\n{header}{chr(10).join(rows)}\n")
    return (
        "\n".join(sections) + "\nViolations are the detector's count per run, averaged over repeats. "
        "Rule effect is without minus with: positive means the rule reduced violations.\n"
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
    run.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    run.add_argument("--model", help=f"Agent model. Defaults: {DEFAULT_MODELS}")
    run.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    run.add_argument("--case-timeout", type=int, default=DEFAULT_CASE_TIMEOUT_SECONDS, help="Seconds per run.")
    run.add_argument("--ref", default="HEAD", help="The commit whose tree and AGENTS.md the agent works on.")
    run.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    run.add_argument("--repo", type=Path, default=REPO_ROOT)
    show = commands.add_parser("report", help="Print a markdown summary of results.")
    show.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser.parse_args(argv)


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
    selected = select_claims(claims, args.claim) if args.claim else [claim for claim in claims if claim.testable]
    untestable = [claim.id for claim in selected if not claim.testable]
    if untestable:
        raise SystemExit(f"These claims have no trap task: {untestable}")
    model = args.model or DEFAULT_MODELS[args.runtime]
    ref = resolve_ref(args.repo, args.ref)
    agents_md = agents_md_at(args.repo, ref)
    results_dir = args.results_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{args.runtime}-{model}"
    jobs = [
        Job(claim=claim, arm=arm, repeat=repeat)
        for claim in selected
        for arm in (args.arm or ARMS)
        for repeat in range(1, args.repeats + 1)
    ]
    print(f"{len(jobs)} runs of {args.runtime} {model} at {ref[:12]}, {args.workers} at a time", flush=True)

    def run_job(job: Job) -> None:
        print(f"{job.name}: running", flush=True)
        try:
            result, candidate, agent_log = evaluate(
                job, agents_md, args.runtime, model, args.judge_model, args.case_timeout, args.repo, ref
            )
        except Exception:
            print(f"{job.name}: crashed\n{traceback.format_exc()}", flush=True)
            return
        write_result(results_dir, job.name, result, candidate, agent_log)
        outcome = "n/a" if result.violations is None else f"{result.violations:.0f}"
        print(f"{job.name}: violations {outcome}" + (f" ({result.failure})" if result.failure else ""), flush=True)

    # The pool would otherwise hold a crash until iteration, after every other job has run.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_job, jobs))
    print(f"\nResults in {results_dir}\n")
    print(report(load_results(results_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
