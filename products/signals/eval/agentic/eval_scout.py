"""pytest entrypoint for the synthetic scout decision eval. See README for run commands."""

from products.signals.eval.agentic._entry import run_step_eval


def eval_scout(eval_opts) -> None:
    run_step_eval("scout", dict(eval_opts))
