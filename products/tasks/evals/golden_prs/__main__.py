# ruff: noqa: T201
import sys
import json
import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from .agents import DEFAULT_MODELS, AgentRun, Runtime, agent_failure, agent_usage, run_agent
from .cases import GoldenPR, build_prompt, load_golden_prs, select_golden_prs
from .scoring import DEFAULT_JUDGE_MODEL, DiffScores, Verdict, changed_files, judge, score_diffs
from .workspace import candidate_diff, checkout_parent, ensure_golden_commits, golden_diff

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RESULTS_DIR = Path(__file__).with_name("results")
DEFAULT_CASE_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True, kw_only=True, slots=True)
class CaseResult:
    pr: int
    title: str
    author: str
    runtime: str
    model: str
    agent_version: str
    judge_model: str
    started_at: str
    duration_seconds: float
    exit_code: int
    timed_out: bool
    scores: DiffScores
    judge_score: float
    judge_reasoning: str
    usage: dict[str, float | int]
    golden_files: list[str]
    candidate_files: list[str]


def verdict_for(run: AgentRun, prompt: str, candidate: str, golden: str, judge_model: str) -> Verdict:
    failure = agent_failure(run)
    if failure and not candidate.strip():
        return Verdict(score=0.0, reasoning=f"The agent failed before changing any file: {failure}")
    return judge(prompt, candidate, golden, model=judge_model)


def evaluate(
    pr: GoldenPR, runtime: Runtime, model: str, judge_model: str, timeout_seconds: int, repo: Path
) -> tuple[CaseResult, str, str]:
    ensure_golden_commits(repo, pr)
    golden = golden_diff(repo, pr)
    prompt = build_prompt(pr)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    with checkout_parent(repo, pr) as workdir:
        run = run_agent(runtime, model, prompt, workdir, timeout_seconds)
        candidate = candidate_diff(workdir)
    verdict = verdict_for(run, prompt, candidate, golden, judge_model)
    result = CaseResult(
        pr=pr.number,
        title=pr.title,
        author=pr.author,
        runtime=runtime,
        model=model,
        agent_version=run.agent_version,
        judge_model=judge_model,
        started_at=started_at,
        duration_seconds=run.duration_seconds,
        exit_code=run.exit_code,
        timed_out=run.timed_out,
        scores=score_diffs(candidate, golden),
        judge_score=verdict.score,
        judge_reasoning=verdict.reasoning,
        usage=agent_usage(run),
        golden_files=sorted(changed_files(golden)),
        candidate_files=sorted(changed_files(candidate)),
    )
    return result, candidate, run.stdout + run.stderr


def write_result(results_dir: Path, result: CaseResult, candidate: str, agent_log: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{result.pr}.json").write_text(json.dumps(asdict(result), indent=2))
    (results_dir / f"{result.pr}.diff").write_text(candidate)
    (results_dir / f"{result.pr}.agent.log").write_text(agent_log)


def load_results(results_dir: Path) -> list[dict]:
    return sorted((json.loads(path.read_text()) for path in results_dir.rglob("*.json")), key=lambda r: r["pr"])


def report(results: list[dict]) -> str:
    if not results:
        return "No results found.\n"
    header = "| PR | Title | Author | Agent | Files hit | Line F1 | Judge | Minutes | Cost $ |\n|---|---|---|---|---|---|---|---|---|\n"
    rows = [
        f"| #{r['pr']} | {r['title']} | {r['author']} | {r['runtime']} {r['model']} "
        f"| {r['scores']['file_recall']:.2f} | {r['scores']['added_line_f1']:.2f} | {r['judge_score']:.2f} "
        f"| {r['duration_seconds'] / 60:.1f}{' (timed out)' if r['timed_out'] else ''} "
        f"| {r['usage'].get('total_cost_usd', 0):.2f} |"
        for r in results
    ]
    means = (
        f"| **Mean** | | | | {mean(r['scores']['file_recall'] for r in results):.2f} "
        f"| {mean(r['scores']['added_line_f1'] for r in results):.2f} | {mean(r['judge_score'] for r in results):.2f} | | |"
    )
    reasoning = "\n".join(f"- **#{r['pr']}** ({r['judge_score']:.2f}): {r['judge_reasoning']}" for r in results)
    return f"{header}{chr(10).join(rows)}\n{means}\n\n### Judge reasoning\n\n{reasoning}\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="golden_prs", description="Score a coding agent against human-written PRs.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Print the golden set.")
    run = commands.add_parser("run", help="Run the agent on golden PRs and score the result.")
    run.add_argument("--pr", type=int, action="append", help="PR number to run. Repeatable. Default: every PR.")
    run.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    run.add_argument("--model", help=f"Agent model. Defaults: {DEFAULT_MODELS}")
    run.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    run.add_argument("--case-timeout", type=int, default=DEFAULT_CASE_TIMEOUT_SECONDS, help="Seconds per PR.")
    run.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    run.add_argument("--repo", type=Path, default=REPO_ROOT, help="A posthog checkout to fetch golden commits into.")
    show = commands.add_parser("report", help="Print a markdown summary of results.")
    show.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    golden_prs = load_golden_prs()
    if args.command == "list":
        for pr in golden_prs:
            print(f"#{pr.number}\t{pr.merged_at[:10]}\t{pr.author}\t{pr.title}")
        return 0
    if args.command == "report":
        print(report(load_results(args.results_dir)))
        return 0
    selected = select_golden_prs(golden_prs, args.pr) if args.pr else golden_prs
    model = args.model or DEFAULT_MODELS[args.runtime]
    results_dir = args.results_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{args.runtime}-{model}"
    for pr in selected:
        print(f"#{pr.number} {pr.title}: running {args.runtime} {model}", flush=True)
        result, candidate, agent_log = evaluate(pr, args.runtime, model, args.judge_model, args.case_timeout, args.repo)
        write_result(results_dir, result, candidate, agent_log)
        print(f"#{pr.number}: judge {result.judge_score:.2f}, files hit {result.scores.file_recall:.2f}", flush=True)
    print(f"\nResults in {results_dir}\n")
    print(report(load_results(results_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
