"""pytest entrypoint for the research eval. See README for run commands."""

from products.signals.eval.agentic._entry import run_step_eval


def eval_research(eval_opts) -> None:
    run_step_eval("research", dict(eval_opts))
