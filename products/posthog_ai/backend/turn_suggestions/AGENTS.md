# Turn suggestion validation

Changes to offer kinds, judge prompts, availability, or thresholds require positive, rejection, and competing-offer cases in `benchmark_cases.yaml`.
Before marking a PR ready, run `.codex/with-flox python manage.py turn_suggestions_benchmark --jev-only` from the repository root.
Inspect wrong picks, missed offers, false offers, and request failures.
The PR records the model, threshold, and results, or the exact blocker and that live selection quality remains unverified.
Mocked classifier tests do not establish live suggestion quality.
