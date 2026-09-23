# Signals agentic evals

- Keep suite entrypoints under `products/signals/evals/` so shared discovery finds them.
- Use the shared workflow eval runner; do not add a second execution, concurrency, timeout, or reporting loop.
- Public suites use `WorkflowPublicEval`, synthetic data, and public repositories. Private saved cases use `WorkflowPrivateEval` and keep source data and results outside version control. Synthetic repository names use `posthog/`.
- Runners call production Signals workflows and return JSON-safe outputs.
- Implementation scores the diff captured from the task log, not model-reported artifacts.
- Add deterministic scorers for exact behavior and a shared-harness judge only for fuzzy quality.
- Saved cases restore fresh projects through the shared case setup hook and use real tools. Do not add tool-response replay or manually prepared project dependencies.
