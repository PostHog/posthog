# Signals pipeline training

This directory is a standalone, restartable project for preparing supervision, training the Signals grouping pipeline, replaying frozen validation territories with the compact Rust evaluator, and packaging serving artifacts.

It has no runtime dependency on another lab checkout. The historical Python builder closure is vendored under [`builders/`](builders), and the serving-parity Rust evaluator is vendored under [`engine/`](engine). Compatibility strings that are embedded in elected artifact formats remain unchanged, but paths, fingerprints, and execution do not refer to an external lab.

The project consumes explicit files only. It does not read PostHog databases and does not make hosted model calls. Candidate prompts and append-only ledger contracts form the handoff to an approved human or model labeling process.

## End-to-end flow

```text
export/signals.jsonl + export/reports.jsonl
  -> import and verify the exact report partition
  -> apply concern-signature and embedding enrichment ledger
  -> exact cross-report clone-link scan
  -> deterministic pair, report, and operation candidate selection
  -> append-only LLM ledger + append-only human ledger
  -> normalize judgments without inventing negatives
  -> validate and clean corpus
  -> deal clone-linked train / validation A / validation B territories
  -> enforce the label firewall
  -> construct training surfaces and fit elected models
  -> chronological Rust replay and validation A score
  -> package serving artifacts
  -> optional, explicitly authorized validation B confirmation
```

Every completed stage writes `_stage.json`. A stage is reused only when its implementation, configuration, runtime, content-addressed inputs, vendored builders, and outputs match. Fingerprint keys are relocation-stable and never contain absolute paths. `--force STAGE` invalidates that stage and every selected downstream stage.

## Source export

Set `source.export_directory` in the configuration. The directory must contain:

- `signals.jsonl`, one signal per line with stable `document_id`, timestamp, content, source product, source type, and a 1,536-coordinate content embedding
- `reports.jsonl`, one report per line with stable `report_id` and a non-empty unique `member_ids` array

The reports must be an exact partition of the signals. Supplied `concern_signature` and `concern_signature_embedding` values are reused.

Signals missing content embeddings or concern enrichment generate `work/enrich_concerns/requests.jsonl`. The stage then stops without contacting a provider. An approved enrichment worker appends responses to `source.concern_ledger` and the same command can be resumed. Each event must match the current content hash:

```json
{
  "event_id": "concern-0001",
  "document_id": "signal-123",
  "content_sha256": "...",
  "producer": "approved-batch-worker",
  "model": "model-name",
  "prompt_version": "sig-v1",
  "concern_signature": {
    "polarity": "problem",
    "surface": "session replay",
    "failure_mode": "playback stalls",
    "error_anchor": null,
    "affected_entity": "recording",
    "concern_tags": ["replay", "playback"],
    "one_liner": "prevent session replay playback stalls"
  },
  "concern_signature_embedding": [0.0],
  "embedding": [0.0]
}
```

The two example vectors above are abbreviated. Actual vectors must contain exactly 1,536 finite, nonzero values. The ledger is append-only. When a document has more than one content-matching event, the last event is the explicit revision and prior events remain in the audit history.

## Clone links and label candidates

`build_clone_links` performs an exact all-pairs cosine scan over content embeddings at the lower of the configured grouping and residual thresholds. It has no nearest-neighbor cap. Report links record the maximum cosine and the number of linked members on each side. `clone_scan_batch_size` bounds matrix memory but does not change results.

`select_label_candidates` produces four review files:

- `pairs.jsonl` selects strongest cross-report clone pairs plus within-report concern-diversity pairs
- `reports.jsonl` selects source reports for coherence and exact-component review
- `operations.jsonl` selects clone-linked report pairs for keep-separate, whole-merge, subset, or ambiguous review
- `llm_requests.jsonl` combines those candidates with the expected judgment contract

Candidate IDs bind a stable entity identity to a `candidate_revision`, which is the SHA-256 digest of the complete content and report membership visible to that review. A content change or membership change produces a new candidate ID. Text in these files is sensitive signal data and is ignored by git.

Run only through candidate selection when setting up a new labeling pass:

```bash
./run config.json --to select_label_candidates
```

## Append-only labels

The configuration names independent LLM and human JSONL ledgers. A ledger event references one current candidate and keeps the judgment separate from selection metadata:

```json
{
  "event_id": "review-0001",
  "candidate_id": "pair:0123456789abcdef01234567",
  "candidate_revision": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "label_kind": "pair",
  "reader": "reviewer-or-model-instance",
  "model": "model-name",
  "prompt_version": "pair-review-v1",
  "raw_response_ref": "approved-store/object-id",
  "judgment": {
    "same_concern": true,
    "confidence": 0.94,
    "rationale": "Both signals describe the same independently actionable failure."
  }
}
```

`model` and `prompt_version` are required for the LLM ledger and omitted for the human ledger. Record an event with the append-only helper:

```bash
./record-label config.json llm review-0001.json
./record-label config.json human review-0002.json
```

The helper locks the ledger, rejects duplicate event IDs, verifies the candidate, copies its current revision into the event when omitted, appends one canonical line, flushes, and never rewrites prior entries. External ledger producers must copy both `candidate_id` and `candidate_revision` from the request. `normalize_label_ledgers` preserves every applicable judgment, records provenance, rejects stale IDs or revisions, and writes the atomic pair, report, and operation files used by training. Unknown or unreviewed candidates never become negatives.

Operation judgments may include `secondary_verdict`, `secondary_reader`, and secondary subset selections when a two-reader consensus target is available. The member-compatibility consensus head only consumes retrieved edges with explicit reader agreement plus deterministic synthetic operations whose membership is known by construction.

## Install and run

Create an isolated Python environment and install the project:

```bash
cd products/signals/pipeline_training
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .
cp config.example.json config.json
```

Inspect the full plan without executing a stage:

```bash
./run config.json --plan
```

Run through validation A and package creation:

```bash
./run config.json --to package
```

Resume after an enrichment or labeling pause by rerunning the same command. Current stages are reused. To rebuild one stage and its selected descendants:

```bash
./run config.json --force select_label_candidates --to package
```

Validation B is outside the default route. After selecting one operating point on A, run exactly one frozen B confirmation:

```bash
./run config.json --from evaluate_b --to evaluate_b --allow-validation-b
```

The orchestrator refuses B without the explicit flag. No training stage reads A or B labels. Packaging also refuses a validation A score without positive and negative pair evidence, gold-report evidence, and defined precision, recall, keep-apart, and gold-cohesion metrics.

## Deterministic training stages

After preparation, the existing recipe runs these stages:

| Stage                                                                     | Responsibility                                                                                                |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `validate_inputs`                                                         | Validate IDs, exact partition, vector widths, timestamps, links, labels, and exact components                 |
| `clean_corpus`                                                            | Remove monster and scout-bypass reports and deterministically sample Error tracking-only reports by size band |
| `split_territories`                                                       | Union clone-linked reports, isolate the train annex, balance demographics, and audit residual links           |
| `prepare_labels`                                                          | Normalize and firewall pair, report, and operation evidence across train, A, and B                            |
| `materialize_corpora`                                                     | Produce chronological Rust rows, float32 matrices, signature rows, and explicit document linkage groups       |
| `build_engine`                                                            | Compile the compact Rust evaluator with ONNX support                                                          |
| `build_pair_surface`, `train_pair`                                        | Construct atomic supervision and fit the depth-3 pair model plus isotonic calibrator                          |
| `harvest_groupjoin`, `build_groupjoin_surface`, `train_groupjoin`         | Replay decision-time candidates and fit the GroupJoin tree plus DeepSets stack                                |
| `build_cut_surface`, `train_split_gate`                                   | Construct whole-report cut supervision and fit the report-disjoint split gate                                 |
| `build_shuffler_curriculum`, `build_shuffler_substrate`, `train_shuffler` | Construct human and synthetic operations, sparse member edges, risk controls, and one dynamic-axis shuffler   |
| `evaluate_a`                                                              | Run the complete chronological learned pipeline and score frozen A labels                                     |
| `package`                                                                 | Copy hash-pinned serving artifacts and write `pipeline.json`, `training-run.json`, and the artifact manifest  |
| `evaluate_b`                                                              | Run the single frozen B confirmation only with explicit authorization                                         |

The GroupJoin builders receive `document_groups.json` through an explicit command-line argument. They cannot fall back to historical shard globals. All vendored builders are included in stage fingerprints.

The shuffler exporter writes one ONNX graph with independent symbolic left-member and right-member axes.
Packaging copies that graph, the compact compatibility models, and the runtime manifest into the hash-pinned serving bundle.
Changing from padded export buckets to dynamic axes does not add learned parameters, but it exposes report sizes that may be outside a checkpoint's training distribution.
Model promotion therefore depends on full chronological replay and large-report qualitative review, not export parity alone.

## Reproducibility and security boundary

Data preparation, candidate selection, normalization, territory assignment, and packaging are deterministic for identical configuration and ledger bytes. CPU model fitting is seeded. Accelerator kernels and dependency revisions can change floating-point weights, so manifests record the runtime and source hashes and behavioral evaluation remains authoritative.

Input exports, enrichment requests, candidate prompts, ledgers, work directories, and output packages can contain customer text or customer-derived embeddings. They must stay in approved encrypted storage with explicit retention. The default local paths are ignored by git.

## Explicit limitations

- The project deliberately has no provider adapter. An approved external worker must fulfill enrichment requests and LLM label requests by appending ledger events.
- Exact clone generation is quadratic in signal count. Batching bounds memory, not compute. Large exports should run on a suitably provisioned offline worker.
- The shuffler has no fixed report-width ceiling, but its dense left-by-right interaction is quadratic in balanced report width and remains bounded by available memory.
- Dynamic-axis export does not establish model quality on report sizes absent from training. Training data and validation must cover the intended large-report operating distribution.
- Candidate limits are a labeling-budget choice. They make the review surface deterministic, not exhaustive supervision.
- Files named `*_oof` and model-local fold metrics describe the immediate model's held fold only. Some downstream shuffler inputs were produced by upstream models fitted on overlapping train operations, so those numbers are not end-to-end out-of-fold estimates and must not be treated as unbiased calibration. Chronological validation A, followed by the one-shot frozen validation B confirmation, is the held-out end-to-end evidence.
- Full training is compute intensive and requires the exact pinned Python dependencies plus a Rust toolchain. The cheap validation path is Python compilation and `cargo check`; those do not exercise model fitting.
- The compact Rust training evaluator fails closed when hosted-oracle behavior is requested. Hosted-oracle replay belongs in a separately authorized runtime.
