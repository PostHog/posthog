# Replay Vision golden-dataset evals

Test scanner prompt changes against a fixed set of real, already-observed sessions instead of shipping and watching production.
The suite re-runs the exact production scan pipeline (`run_scan`: same Jinja templates, response schemas, events tool) over collected videos, then scores the fresh output against the recorded output and its human thumbs label.

## The loop

1. Collect a dataset once (and re-collect occasionally as labels accumulate).
2. Run the suite to get a baseline.
3. Edit prompt templates under `../backend/temporal/scanners/prompts/`.
4. Re-run the suite and compare scores across runs (same experiment name accumulates history).

## Collecting a dataset

Uses only the public API plus the dogfood warehouse, with a personal API key that can read the source project (scanner read + session recording read + query scopes):

```bash
POSTHOG_API_KEY=... python -m products.replay_vision.evals.collect \
    --project-id 2 --per-type 25 --output ~/.posthog/replay-vision-golden-dataset
```

Selection is per scanner type: human-labeled observations first (thumbs up/down carry ground truth), then a seeded uniform sample of unlabeled ones.
Only observations whose original rasterized MP4 still exists are collectable: the system assets expire after 90 days, a session re-rasterized after that is a different video than the one behind the recorded output (so those are skipped too), and the warehouse copy of the exports table lags up to a day, so very fresh observations are skipped.
Each case also captures the prompt context the production scan carried: the project's product context (Max core memory needs a full-access personal key; otherwise the project description is used), the session's custom-event descriptions, and, for freeform classifiers, the known-tag vocabulary.
Re-running the collector is idempotent per case: completed cases are reused as-is, half-written ones are re-collected, and the manifest is merged with previously collected cases that are still valid on disk.
After a collector change that alters what a case captures, collect into a fresh directory so reused cases don't keep the old shape.

## Running the suite

```bash
REPLAY_VISION_EVAL_DATASET=~/.posthog/replay-vision-golden-dataset \
GEMINI_API_KEY=... \
LLM_GATEWAY_ANTHROPIC_API_KEY=... \
BRAINTRUST_API_KEY=... \
hogli evals eval_scanner_quality
```

`GEMINI_API_KEY` runs the scans themselves.
`LLM_GATEWAY_ANTHROPIC_API_KEY` satisfies the suite env preflight (judge models are routed through the internal LLM gateway).
`BRAINTRUST_API_KEY` is required by the harness engine even though this private suite only logs locally.
Without `REPLAY_VISION_EVAL_DATASET` the suite logs a warning and runs nothing, so it never breaks a full `hogli evals` run.
Use `--trials N` for variance on Gemini nondeterminism and `--eval <case-substring>` for one case.

## Scorers

| Scorer              | Applies to                               | Meaning                                                                                                    |
| ------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `scan_completed`    | all cases                                | The scan produced schema-valid, semantically-valid output.                                                 |
| `labeled_outcome`   | labeled monitor/classifier               | kept/fixed = 1, regressed/still_wrong = 0 (same semantics as the in-product prompt-suggestion evaluation). |
| `output_stability`  | unlabeled monitor/classifier             | Fresh outcome matches the recorded baseline; measures churn, not correctness.                              |
| `score_alignment`   | scorer (reference not thumbs-downed)     | 1 minus the scale-normalized distance from the recorded score.                                             |
| `summary_alignment` | summarizer (reference not thumbs-downed) | LLM judge: does the fresh summary tell the same story as the recorded one?                                 |

`output_stability` and `labeled_outcome` deliberately pull in opposite directions, so read them as a pair: a prompt change that only adds churn shows up as `labeled_outcome` flat or up while `output_stability` drops.

## Data handling

The dataset contains real session recordings and event data.

- Keep it in a local or internal location only; never commit it, upload it, or reference its contents in PRs.
- A dataset expires 30 days after its last collection: the suite refuses to run it, because the consent verification (and the recordings themselves) can lapse after collection. Re-running collect.py re-verifies consent and refreshes the manifest.
- The suite is `OneShotPrivateEval`: results stay in the local `eval_harness/logs/` directory and are not sent to Braintrust.
- `summary_alignment` sends the recorded and fresh session summaries to the LLM judge (`gpt-5.4` via the internal LLM gateway); besides the Gemini scans themselves, this is the only path where dataset-derived content leaves the machine.
- Collecting from projects other than PostHog's own requires a data-governance decision first; see the product's consent gating (`backend/consent.py`) and note that customer-facing copy does not cover internal reuse today.
