# Replay Vision evals

## Labeling benchmark

Test a core prompt change or a new Gemini model against recordings that human labelers answered questions about, instead of shipping and watching production.
`eval_benchmark` asks Replay Vision each labeling question through the production scan pipeline (`run_scan`: same Jinja templates, response schemas, events tool) over the case's rendered video and production inputs.
It then scores the answer against every labeler's answer, not a consensus.

### The loop

1. Build a benchmark version once in production (`build_replay_vision_benchmark`). A version never changes after it is built.
2. Copy a tier of it to your machine or devbox.
3. Run the suite to get a baseline.
4. Edit the prompt templates under `../backend/temporal/scanners/prompts/`, or set a different model.
5. Re-run and compare. Runs of one version and tier share an experiment name, so their history accumulates.

### Copying a version

```bash
AWS_PROFILE=<a profile that can read the benchmark bucket> \
python manage.py pull_replay_vision_benchmark v1 --tier fast --dest ~/.posthog/replay-vision-benchmark \
    --bucket <the benchmark bucket>
```

`--tier fast` copies a fixed sample of 50 built cases, for iterating on a prompt.
`--tier full` copies every built case, for a final check before a prompt or model change ships.
The fast tier is chosen by hash, so it is the same 50 cases every time for a given version.

### Running the suite

```bash
REPLAY_VISION_BENCHMARK_DIR=~/.posthog/replay-vision-benchmark \
GEMINI_API_KEY=... \
LLM_GATEWAY_ANTHROPIC_API_KEY=... \
BRAINTRUST_API_KEY=... \
hogli evals eval_benchmark
```

`GEMINI_API_KEY` runs the scans.
`LLM_GATEWAY_ANTHROPIC_API_KEY` and `BRAINTRUST_API_KEY` satisfy the harness preflight, although this suite calls no judge and sends nothing to Braintrust.
Set `REPLAY_VISION_BENCHMARK_MODEL` to compare a model other than the default for new scanners.
Without `REPLAY_VISION_BENCHMARK_DIR` the suite logs a warning and runs nothing, so it never breaks a full `hogli evals` run.
Use `--trials N` for variance on Gemini nondeterminism and `--eval <recording-id>` for the questions about one recording.
It runs the same way on a devbox as on a laptop.

### How a question is asked

Each case is one (recording, question) cell, asked with one scan per question:

| Labeling question                           | Scan                    | Answer compared                                   |
| ------------------------------------------- | ----------------------- | ------------------------------------------------- |
| Binary                                      | Monitor                 | The verdict                                       |
| Timeline marking, itemized                  | Monitor                 | The verdict as presence, the citations as moments |
| Multiple choice (single, ordinal, multiple) | Classifier over options | The chosen options                                |
| Multiple choice with a rating scale         | One scorer per option   | Each option's rating                              |
| Free text, ranking, correction              | Not asked               | Nothing comparable                                |

The question's own prompt and description are the scan prompt, so the labeling questions stay unchanged.

### Scorers

| Scorer              | Meaning                                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| `answered`          | The scan gave a comparable answer. A failed scan, or a choice outside the question's options, scores 0.     |
| `label_agreement`   | Mean agreement of Replay Vision's answer with each labeler's. No answer scores 0, so abstaining never pays. |
| `labeler_agreement` | Each labeler scored against the others. This is the ceiling to read `label_agreement` against.              |

Agreement is exact for binary and nominal questions, distance on the scale for ordinal and rating questions, Jaccard overlap for multiple selection, and presence plus a moment F1 for timeline and itemized questions.
A moment matches when the two overlap or sit within two seconds of each other; a Replay Vision citation is a single point in time.

### Data handling

A copy contains session recordings and analytics events.

- Keep it on your machine or devbox only; never commit it, upload it, or reference its contents in PRs.
- A copy expires 30 days after it was pulled: the suite refuses an older copy. Pull again to refresh it.
- The suite is `OneShotPrivateEval`, so per-case logs stay in the local `eval_harness/logs/` directory.
- The only content that leaves the machine is the Gemini scan, the same provider call production makes through `run_scan`.
- The build checked AI data-processing consent for every case before it copied anything.
