# Self-driving SWE eval

End-to-end benchmark of the autonomous signals→PR loop against the **real** local stack.
Read `README.md` for the runbook, `DESIGN.md` for the benchmark design, and `TASK_SPEC.md` before changing tasks.

## Layout

| Path                   | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `README.md`            | Setup, validation, full-run commands, output, and troubleshooting           |
| `DESIGN.md`            | Benchmark design: stages, scorers, difficulty tiers                         |
| `TASK_SPEC.md`         | Task authoring convention (`task.json`, `signals.json`, `repo/`, `verify/`) |
| `tasks/<task_id>/`     | Task universes: planted defect + signals + hidden behavioral tests          |
| `harness/provision.py` | Per-task team, synthetic GitHub integration + repo cache entries            |
| `harness/seed.py`      | ClickHouse telemetry seeding (direct `sharded_events` inserts)              |
| `harness/runner.py`    | Drives one task through the real pipeline; collects report/patch/logs       |
| `harness/grade.py`     | Behavioral test execution + LLM judges (no Braintrust dependency)           |
| `harness/drive.py`     | Full-run driver: parallelism, timeouts, result JSON, Braintrust hand-off    |
| `eval_selfdriving.py`  | Braintrust logging (project `signals-self-driving`)                         |

## Validation

Run `hogli test products/signals/backend/test/test_self_driving_eval.py` after changing the harness or task corpus. Run one task with one trial before starting a full experiment.
