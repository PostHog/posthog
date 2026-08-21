# Signals agentic evals

- Keep suite entrypoints under `products/signals/evals/` so shared discovery finds them.
- Use `WorkflowPublicEval`; do not add a second execution, concurrency, timeout, or reporting loop.
- Cases must use synthetic data and public repositories. Synthetic repository names use `posthog/`.
- Runners call production Signals workflows and return JSON-safe outputs.
- Implementation scores the diff captured from the task log, not model-reported artifacts.
- Add deterministic scorers for exact behavior and a shared-harness judge only for fuzzy quality.
- Do not add cassette, replay, record, or manual project-seeding modes.
