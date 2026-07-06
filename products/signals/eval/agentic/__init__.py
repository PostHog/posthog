"""Agentic task-run eval framework for the Signals pipeline.

This package evaluates the *agentic* steps of the Signals pipeline — research,
repository selection, and implementation — by driving the **real** production step
functions (``run_multi_turn_research``, ``select_repository_for_team``, the tasks
implementation flow) and grading their outputs against hand-authored ground truth.

It mirrors the philosophy of the sibling grouping eval (``eval_grouping_e2e.py``):
run the real pipeline, swap only the infrastructure. Here the single swappable seam
is the agent itself — every step drives the LLM through ``MultiTurnSession``, so the
framework injects a :class:`SessionBackend` (live sandbox, recorded replay, or a
scripted fake) at that one boundary and leaves the production prompt-building and
result-collapsing logic untouched.

See ``README.md`` for the architecture and run commands.
"""
