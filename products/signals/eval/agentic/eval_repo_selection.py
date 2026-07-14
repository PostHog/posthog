"""pytest entrypoint for the repository-selection eval. See README for run commands."""

from products.signals.eval.agentic._entry import run_step_eval


def eval_repo_selection(eval_opts) -> None:
    run_step_eval("repo_selection", dict(eval_opts))
