"""pytest entrypoint for the synthetic scout decision eval. See README for run commands."""

import pytest

from products.signals.eval.agentic._entry import run_step_eval


def eval_scout(eval_opts) -> None:
    if eval_opts["mode"] != "live":
        pytest.skip("Scout has no replay dataset. Run it with --eval-mode live.")
    run_step_eval("scout", dict(eval_opts))
