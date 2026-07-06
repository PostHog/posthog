# Agentic eval framework — agent pointer

Read `README.md` first. Key facts:

- Evaluates the agentic steps (research, repo selection, implementation) by driving the
  **real** production step functions and grading outputs against ground truth.
- The one swappable seam is `MultiTurnSession`. `replay` (default) feeds recorded cassettes
  through the real validation/collapsing logic — deterministic, no stack, no LLM. `live` runs
  the real sandbox agent (needs the local stack + Docker).
- Run: `python manage.py run_agentic_signals_eval [--step ...] [--mode replay|record|live] [--judge] [--capture] [--min-pass-rate N]`.
- Unit tests are `test_*.py` here (DB-free); evals are `eval_*.py` (collected by `../pytest.ini`).

When changing a step's prompt/flow in `report_generation/` or `repo_selection/`:

- If the turn sequence changed, existing cassettes will fail to replay — re-record
  (`--mode record`) or hand-update them.
- Keep `run_multi_turn_research` persistence-free for `signal_report_id=None` (replay relies on it).
- Add cases/scorers rather than loosening assertions; every scorer must discriminate (a
  matching `test_scorers.py` test asserts good-passes / bad-fails).
