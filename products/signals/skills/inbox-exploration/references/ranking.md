## Model predictions as building blocks

The inbox ranking model predicts outcomes for each report. Each row of `inbox-reports-list` and
`inbox-reports-retrieve` carries them in `ranking`:

```json
"ranking": {
  "status": "scored",
  "scored_at": "2026-10-24T05:12:00Z",
  "predictions": [
    { "outcome": "open", "probability": 0.21, "lift": 1.5, "readable": true },
    { "outcome": "action", "probability": 0.09, "lift": 1.4, "readable": true },
    { "outcome": "fix", "probability": 0.3, "lift": 2.7, "readable": true }
  ]
}
```

- `open`: a person opens the report. `action`: a person or their agent acts on it. `fix`:
  someone fixes the problem it describes. Call `inbox-ranking-outcomes-list` for the current
  meaning, horizon and base rate of each outcome, because they follow the served model.
- A prediction says what may happen, never what did. A high `fix` probability does not mean the
  report is fixed: read `status` and the PR fields for that.
- A lift is the probability divided by the outcome's base rate. 1.0 is an average report, 2.7 is
  2.7x as likely. Compare lifts across outcomes. Raw probabilities do not compare, because each
  outcome has its own base rate.
- `readable: false` means the training run could not measure the holdout AUC of that outcome.
  Rank and filter on that outcome with caution.
- `status` is `scored`, `stale` (the title or summary changed after scoring, so the predictions
  describe the old text), `unscored` (no score yet, which is not a low score), or `not_available`
  (the user cannot see the ranking model, so ordering and filtering by it return 400).
- `inbox-reports-retrieve` also names the `model` that made the predictions. Predictions from
  different models do not compare.

Recipes:

- Likely to get a fix: `view=actionable` with `ordering=-ranking_fix`.
- Hidden gems: `priority=P3,P4` with `ranking_min_lift=fix:2`.
- Probably noise: reports with a low lift on all three outcomes are candidates to dedupe or
  dismiss. Read them before you act: a low lift is a hint, not a verdict.
- Add `search` or `source_product` to any recipe to narrow it to a topic.

`ranking_min_lift` and `ranking_min_probability` take comma-separated `<outcome>:<value>` pairs,
and a report must meet every pair. Unscored and stale reports never match.

Caveats:

- The predictions are model estimates, and the top end over-predicts. Use them to rank and
  filter, not as literal odds.
- Most `fix` positives are also `action` positives, so do not add the two together.
