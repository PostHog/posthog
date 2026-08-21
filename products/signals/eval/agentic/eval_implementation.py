"""pytest entrypoint for the implementation eval. See README for run commands."""

from products.signals.eval.agentic._entry import run_step_eval


def eval_implementation(eval_opts) -> None:
    run_step_eval("implementation", dict(eval_opts))
