# ingestion-worker-proto

Rust bindings for the ingestion consumer → worker streaming gRPC API.

Proto definitions live in the top-level [`/proto/ingestion`](/proto/ingestion) directory.
The `ingestion.worker.v1.WorkerIngest` service carries routed sub-batches from `rust/ingestion-consumer` to the Node.js ingestion-api workers over one ordered bidirectional stream per (consumer, worker) pair.

## Building

```bash
cargo build -p ingestion-worker-proto
```

Rust bindings regenerate automatically through `tonic-build` when the crate builds.
