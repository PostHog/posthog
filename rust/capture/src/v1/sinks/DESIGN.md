# v1/sinks

The v1 sink stack described by earlier revisions of this document
(`Event`/`Sink`/`Router` traits, `serialize_batch`, the per-sink Kafka
producer) has been dissolved into the shared outputs machinery: v1 events map
onto the `ProcessedEvent` interchange via `WrappedEvent::to_processed` and
publish through `crate::outputs` (`KafkaOutputs` surfaces named by
`CAPTURE_V1_SINKS`, composed by `OutputsRouter`). See
`rust/capture/OUTPUTS_REFACTOR_PLAN.md` (step 20) for the convergence design
and the parity oracle in `v1/analytics/types.rs` (`shared_prep_parity`).

What remains here:

- `SinkName` + per-sink env config loading (`CAPTURE_V1_SINKS`,
  `CAPTURE_V1_SINK_<NAME>_KAFKA_*`) in `mod.rs` / `kafka/config.rs`, including
  the field-for-field mapping onto the shared `KafkaConfig`.
- `Destination` — the v1 routing vocabulary, bridged onto the shared
  `Address` via `Destination::as_address`.
- `OutputsRouter` — named shared-outputs surfaces with a default.
