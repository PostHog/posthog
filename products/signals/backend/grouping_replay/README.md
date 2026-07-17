# Frozen Signals grouping replay

This package is the Python-only execution boundary for the elected Lab 3 grouping pipeline.
It verifies every copied artifact before loading ONNX Runtime, enriches missing concern signatures and embeddings through injected providers, replays signals chronologically, and writes an integrity-sealed portable bundle.

The runtime has no Lab checkout, credential-file, Rust, or subprocess dependency.
Only `provider_gateway.py` imports PostHog's Django-aware gateway client.
Callers may instead inject `ProviderSet` implementations for deterministic tests or another approved provider boundary.

`oracle-off` applies the frozen learned shuffler gates.
`oracle-on` invokes the exact `remediation-coherence-v2` oracle after the neural model proposes one mask.
The oracle then replaces the learned action and safety gates for that proposal, may accept, reject, or select one alternative cross-report mask, and fails closed after one invalid-response correction attempt.

Provider responses are append-only JSONL records below `<run_dir>/cache`.
These caches and output bundles contain customer-derived data and must be protected and retained accordingly.
Directories created by the runtime use mode `0700`, and cache records and bundles use mode `0600`.

The runtime accepts at most 10,000 signals per replay.
This is a deliberate safety boundary for the current sequential proof-of-concept retrieval path, not a product-scale throughput claim.
Embedding enrichment makes one provider request per unique text, retries only that request, and shares one bounded concurrency limit across signal and concern-signature vectors.

The public API is `replay_signals`, its management-command wrapper `replay_signals_sync`, and `inspect_bundle`.
Input may be one JSONL file, a prior portable replay bundle, or a directory.
When a directory contains `signals.jsonl`, that file is the replay input and sibling report or label files are not ingested.
The production report partition in `reports.jsonl` is reference and training data only; replay always constructs a new assignment from the signal stream.
