"""Turn a repository-selection model comparison into a quality, latency, and cost table.

    python -m products.tasks.evals.repo_selection.report <comparison-dir> [--json out.json]

Reads each arm's run report, per-trial artifacts, and the eval gateway's captured
`$ai_generation` events. Every planned trial stays in the denominators: a trial with an
error, timeout, or no result counts as incorrect. Gateway cost is what the gateway charged;
the list estimate reprices the same tokens from provider list rates, and halves a call only
when the gateway reports that Flex served it.
"""

from __future__ import annotations

import sys
import json
import argparse
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from products.posthog_ai.eval_harness.log_sink import _case_log_slug

from .fixtures import FIXTURE_VERSION, SELECTOR_CASES, fixture_fingerprint
from .scorers import judge_selection, selector_expected

EXPERIMENT = "repo-selection-selector"
REPO_ROOT = Path(__file__).resolve().parents[4]
LLM_COSTS = REPO_ROOT / "nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json"

# The provider row of `llm-costs.json` each arm's gateway route bills at.
LIST_PRICE_ROWS: dict[str, tuple[str, str]] = {
    "claude-haiku-5-5": ("anthropic/claude-haiku-5.5", "anthropic"),
    "claude-haiku-4-5": ("anthropic/claude-haiku-4.5", "anthropic"),
    "gpt-6-luna": ("openai/gpt-6-luna", "openai"),
    "gpt-5.6-luna": ("openai/gpt-5.6-luna", "openai"),
    "gpt-6.1-terra": ("openai/gpt-6.1-terra", "openai"),
    # No list row names the fast build; the gateway prices it at Baseten's rate (see served.go).
    "deepseek-ai/deepseek-v4.1-flash-1017-fast": ("", "baseten"),
}
BASETEN_DEEPSEEK_V4_1_FAST = {"prompt_token": 0.60e-6, "completion_token": 2.40e-6, "cache_read_token": 0.014e-6}
FLEX_DISCOUNT = 0.5


def _list_prices(model: str) -> dict[str, float] | None:
    row_name, provider = LIST_PRICE_ROWS.get(model, ("", ""))
    if model == "deepseek-ai/deepseek-v4.1-flash-1017-fast":
        return BASETEN_DEEPSEEK_V4_1_FAST
    if not row_name or not LLM_COSTS.exists():
        return None
    rows = json.loads(LLM_COSTS.read_text())
    for row in rows if isinstance(rows, list) else []:
        if row.get("model") == row_name:
            return row["cost"].get(provider) or row["cost"].get("default")
    return None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _list_cost(properties: dict[str, Any], prices: dict[str, float] | None) -> float | None:
    if prices is None:
        return None
    # The gateway reports disjoint buckets for every provider: uncached input, cache reads,
    # cache writes, and output (which includes reasoning tokens).
    cache_read = _number(properties.get("$ai_cache_read_input_tokens"))
    cache_write = _number(properties.get("$ai_cache_creation_input_tokens"))
    input_tokens = _number(properties.get("$ai_input_tokens"))
    cost = (
        input_tokens * prices.get("prompt_token", 0)
        + _number(properties.get("$ai_output_tokens")) * prices.get("completion_token", 0)
        + cache_read * prices.get("cache_read_token", prices.get("prompt_token", 0))
        + cache_write * prices.get("cache_write_token", prices.get("prompt_token", 0))
    )
    return cost * FLEX_DISCOUNT if properties.get("$ai_service_tier") == "flex" else cost


def _generations_by_run(path: str | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path or not Path(path).exists():
        return grouped
    for line in Path(path).read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            grouped[str(record["properties"].get("task_run_id"))].append(record["properties"])
    return grouped


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def summarize_arm(run: dict[str, Any]) -> dict[str, Any]:
    report = run.get("report") or {}
    label = ", ".join(
        part
        for part in (
            f"{run['runtime']}/{run['model']}",
            f"tier={run['service_tier']}" if run.get("service_tier") else "",
            f"effort={run['reasoning_effort']}" if run.get("reasoning_effort") else "",
        )
        if part
    )
    experiment = (report.get("experiments") or {}).get(EXPERIMENT)
    summary: dict[str, Any] = {
        "arm": label,
        "run": {k: run.get(k) for k in ("runtime", "model", "service_tier", "reasoning_effort", "exit_code", "issue")},
    }
    if not experiment:
        return summary | {"status": "not run" if run.get("exit_code") is None else "no results"}

    log_dir = Path(experiment["log_dir"])
    case_results = log_dir / "case_results.jsonl"
    if not case_results.exists():
        raise SystemExit(f"{case_results} is missing. Rerun the comparison with EXPORT_EVAL_RESULTS=1.")
    rows = [json.loads(line) for line in case_results.read_text().splitlines() if line.strip()]
    generations = _generations_by_run(report.get("ai_gateway_generations_path"))
    prices = _list_prices(run["model"])
    expected = {case.scenario.name: (case, selector_expected(case.expected)) for case in SELECTOR_CASES}

    outcomes: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    trials: list[dict[str, Any]] = []
    for row in rows:
        case, spec = expected[row["case_name"]]
        artifacts_path = log_dir / f"{_case_log_slug(row['case_name'], row.get('trial_id'))}.artifacts.json"
        artifacts = json.loads(artifacts_path.read_text()) if artifacts_path.exists() else None
        if row.get("error"):
            outcome = "infra_error"
            correct = 0.0
        else:
            correct, _ = judge_selection(artifacts, spec["repo_selection_correct"])
            outcome = (artifacts or {}).get("outcome") or "timeout"
        outcomes[outcome] += 1
        calls = generations.get(str((artifacts or {}).get("task_run_id")), [])
        for call in calls:
            requested = call.get("$ai_service_tier_requested") or "none"
            served = call.get("$ai_service_tier") or "unreported"
            fallback = "+fallback" if call.get("$ai_service_tier_fallback") else ""
            tiers[f"{requested}->{served}{fallback}"] += 1
        list_costs = [_list_cost(call, prices) for call in calls]
        trials.append(
            {
                "case": row["case_name"],
                "category": case.category,
                "abstain_expected": case.expected.abstain,
                "trial_id": row.get("trial_id"),
                "outcome": outcome,
                "selected": (artifacts or {}).get("selected_repository"),
                "correct": correct,
                "latency_seconds": (artifacts or {}).get("selector_seconds"),
                "calls": len(calls),
                "model_seconds": sum(_number(c.get("$ai_latency")) for c in calls),
                "input_tokens": sum(_number(c.get("$ai_input_tokens")) for c in calls),
                "output_tokens": sum(_number(c.get("$ai_output_tokens")) for c in calls),
                "cache_read_tokens": sum(_number(c.get("$ai_cache_read_input_tokens")) for c in calls),
                "cache_write_tokens": sum(_number(c.get("$ai_cache_creation_input_tokens")) for c in calls),
                "reasoning_tokens": sum(_number(c.get("$ai_reasoning_tokens")) for c in calls),
                "gateway_cost_usd": sum(_number(c.get("$ai_total_cost_usd")) for c in calls),
                "list_cost_usd": None if any(cost is None for cost in list_costs) else sum(list_costs),
                "models_served": sorted({str(c.get("$ai_model")) for c in calls}),
                "providers": sorted({str(c.get("$ai_provider")) for c in calls}),
                "efforts": sorted({str(c.get("$ai_effort")) for c in calls}),
                "products": sorted({str(c.get("$ai_product")) for c in calls}),
                "failed_calls": sum(1 for c in calls if c.get("$ai_gateway_outcome") not in (None, "ok")),
            }
        )

    planned = experiment.get("planned_trials") or len(trials)
    match_trials = [t for t in trials if not t["abstain_expected"]]
    no_match_trials = [t for t in trials if t["abstain_expected"]]
    selected_cases = experiment.get("cases") or {}
    trials_per_case = report.get("trials", 1)
    planned_match = sum(
        count * trials_per_case for name, count in selected_cases.items() if not expected[name][0].expected.abstain
    )
    planned_no_match = sum(
        count * trials_per_case for name, count in selected_cases.items() if expected[name][0].expected.abstain
    )
    correct = sum(t["correct"] for t in trials)
    latencies = [
        t["latency_seconds"]
        for t in trials
        if t["latency_seconds"] is not None and t["outcome"] in {"found", "no_match", "rejected"}
    ]
    model_times = [
        t["model_seconds"] for t in trials if t["calls"] and t["outcome"] in {"found", "no_match", "rejected"}
    ]
    gateway_cost = sum(t["gateway_cost_usd"] for t in trials)
    list_costs = [t["list_cost_usd"] for t in trials]
    return summary | {
        "status": "ok",
        "planned_trials": planned,
        "recorded_trials": len(trials),
        "missing_trials": planned - len(trials),
        "accuracy": correct / planned if planned else None,
        "selection_accuracy": sum(t["correct"] for t in match_trials) / planned_match if planned_match else None,
        "correct_abstention": sum(t["correct"] for t in no_match_trials) / planned_no_match
        if planned_no_match
        else None,
        "false_selection_on_no_match": sum(1 for t in no_match_trials if t["outcome"] in {"found", "rejected"})
        / planned_no_match
        if planned_no_match
        else None,
        "abstained_on_answerable": sum(1 for t in match_trials if t["outcome"] == "no_match"),
        "out_of_candidate": outcomes["rejected"],
        "errors": outcomes["error"] + outcomes["unavailable"] + outcomes["usage_limited"] + outcomes["infra_error"],
        "timeouts": outcomes["timeout"],
        "outcomes": dict(outcomes),
        "latency_p50_seconds": statistics.median(latencies) if latencies else None,
        "latency_p90_seconds": _percentile(latencies, 0.9),
        # Selector latency is quantized by the session's ~10s poll; model time is the gateway's per-call sum.
        "model_seconds_p50": statistics.median(model_times) if model_times else None,
        "model_seconds_p90": _percentile(model_times, 0.9),
        "gateway_cost_usd": gateway_cost,
        "gateway_cost_per_case_usd": gateway_cost / planned if planned else None,
        "gateway_cost_per_correct_usd": gateway_cost / correct if correct else None,
        "list_cost_usd": None if any(c is None for c in list_costs) else sum(c for c in list_costs if c is not None),
        "tokens": {
            key: sum(t[key] for t in trials)
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
        },
        "model_calls": sum(t["calls"] for t in trials),
        "service_tiers": dict(tiers),
        "models_served": sorted({m for t in trials for m in t["models_served"]}),
        "providers": sorted({p for t in trials for p in t["providers"]}),
        "efforts_observed": sorted({e for t in trials for e in t["efforts"]}),
        "products": sorted({p for t in trials for p in t["products"]}),
        "failed_model_calls": sum(t["failed_calls"] for t in trials),
        "per_case": {
            name: {
                "correct": sum(t["correct"] for t in trials if t["case"] == name),
                "trials": sum(1 for t in trials if t["case"] == name),
                "selected": [t["selected"] or t["outcome"] for t in trials if t["case"] == name],
            }
            for name in sorted({t["case"] for t in trials})
        },
        "trials": trials,
    }


def _fmt(value: Any, kind: str = "") -> str:
    if value is None:
        return "n/a"
    if kind == "%":
        return f"{value:.0%}"
    if kind == "$":
        return f"${value:.4f}"
    if kind == "s":
        return f"{value:.0f}s"
    return str(value)


def render(arms: list[dict[str, Any]]) -> str:
    header = [
        "Arm",
        "Accuracy",
        "Selection",
        "Abstain",
        "False sel.",
        "Out-of-cand.",
        "Errors",
        "Timeouts",
        "p50",
        "p90",
        "Model p50",
        "$/case",
        "$/correct",
        "List $/case",
        "Tiers",
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for arm in arms:
        if arm.get("status") != "ok":
            lines.append(f"| {arm['arm']} | {arm.get('status')} |" + " |" * (len(header) - 2))
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    arm["arm"],
                    f"{_fmt(arm['accuracy'], '%')} ({sum(t['correct'] for t in arm['trials']):.0f}/{arm['planned_trials']})",
                    _fmt(arm["selection_accuracy"], "%"),
                    _fmt(arm["correct_abstention"], "%"),
                    _fmt(arm["false_selection_on_no_match"], "%"),
                    str(arm["out_of_candidate"]),
                    str(arm["errors"] + arm["missing_trials"]),
                    str(arm["timeouts"]),
                    _fmt(arm["latency_p50_seconds"], "s"),
                    _fmt(arm["latency_p90_seconds"], "s"),
                    _fmt(arm["model_seconds_p50"], "s"),
                    _fmt(arm["gateway_cost_per_case_usd"], "$"),
                    _fmt(arm["gateway_cost_per_correct_usd"], "$"),
                    _fmt(
                        arm["list_cost_usd"] / arm["planned_trials"] if arm["list_cost_usd"] is not None else None, "$"
                    ),
                    ", ".join(f"{k}:{v}" for k, v in sorted(arm["service_tiers"].items())),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("comparison_dir", type=Path)
    parser.add_argument("--json", type=Path, help="Write the full per-arm and per-trial summary here.")
    args = parser.parse_args(argv)
    comparison = json.loads((args.comparison_dir / "comparison.json").read_text())
    arms = [summarize_arm(run) for run in comparison["runs"]]
    output = {
        "fixture_version": FIXTURE_VERSION,
        "fixture_fingerprint": fixture_fingerprint(),
        "settings": comparison["settings"],
        "issues": comparison.get("issues", []),
        "arms": arms,
    }
    if args.json:
        args.json.write_text(json.dumps(output, indent=2, default=str))
    sys.stdout.write(render(arms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
