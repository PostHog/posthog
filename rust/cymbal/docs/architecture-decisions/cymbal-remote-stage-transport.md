# Cymbal remote stage transport

## Decision

Cymbal remote stages use a unary internal gRPC call:

```text
CymbalStageRuntime.ProcessStage(StageBatch) -> StageBatchResult
```

The public ingestion API remains streaming.
This decision only affects the internal Cymbal stage-pod API.

## Shape

`StageBatch` contains one `StageStart` envelope plus repeated `StageItem` payloads.
`StageBatchResult` contains repeated `StageItemResult` values, repeated `StageItemError` values for item-level failures, and optional `StageLoad` metadata.
Request-level gRPC errors are reserved for malformed batches, resource exhaustion before per-item work can be represented, unknown stages, dependency failures, and transport failures.

## Rationale

The stage contract is a buffered stage invocation with item-level success and error reporting.
A unary call matches that runtime model while keeping the transport easy to reason about:

- one request maps to one selected endpoint sub-batch;
- stage implementations can perform vectorized repository/cache work;
- load metadata is tied to the concrete pod that handled or rejected the sub-batch;
- request-level failures stay distinct from item-level processing failures;
- transport state machines stay smaller than a stream-shaped envelope would require.

Public response streaming is implemented above this internal transport.
The pipeline can advance item-progress stages and stream ordered final outcomes without exposing internal stage envelopes to Node callers.

## Compatibility

`ProcessStage` is an internal Cymbal deployment contract, not a public product API.
Pipeline and stage pods for the same target must use compatible protobuf definitions and `StagePayload` type IDs.
When a remote payload shape changes, bump the relevant `StagePayload::TYPE.version`, update the sending registry and receiving stage registry together, and validate server integration snapshots.
