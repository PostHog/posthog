# Turn suggestion validation

Changes to offer kinds, judge prompts, availability, or thresholds require positive, rejection, and competing-offer cases in `benchmark_cases.yaml`.
Before marking a PR ready, run `flox activate -- bash -c "python manage.py turn_suggestions_benchmark --jev-only"` from the repository root.
Inspect wrong picks, missed offers, false offers, and request failures.
Changes to drafter prompts also require a run with `--draft`, and you must read the live drafts it prints.
The PR records the model, threshold, and results, or the exact blocker and that live selection quality remains unverified.
Mocked classifier tests do not establish live suggestion quality.
