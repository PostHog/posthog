"""Shared body for the per-step pytest eval entrypoints."""

from __future__ import annotations

from products.signals.eval.agentic.run import run_and_report


def run_step_eval(step: str, eval_opts: dict) -> None:
    min_pass = eval_opts.pop("min_pass_rate", None)
    results = run_and_report([step], **eval_opts)
    suite = results[step]
    # Evals report rather than gate by default; a threshold makes them CI-gateable on demand.
    if min_pass is not None:
        assert suite.pass_rate >= min_pass, f"{step} pass_rate {suite.pass_rate:.0%} < required {min_pass:.0%}"
