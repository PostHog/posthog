# AI observability capture overview

## Objective

`/i/v0/ai` is the dedicated single-event ingress for AI observability events.
It accepts one AI event per request as `multipart/form-data`, validates it against the AI event contract, and publishes it to Kafka like any other captured event.
Heavy content (prompts, completions, media) rides inline in the event JSON;
oversized media is offloaded to blob storage later, at ingestion, by the Node AI pipeline's blob-offload step (`nodejs/src/ingestion/pipelines/ai/blob-offload/`), not by capture.

Batch traffic uses `/i/v0/ai/batch`, which dispatches to the standard batch handler.
OTLP trace export uses `/i/v0/ai/otel`.
This document covers only the single-event multipart endpoint.

## Supported events

The endpoint accepts exactly six event names (`ALLOWED_AI_EVENTS` in `ai_rejection.rs`):
`$ai_generation`, `$ai_trace`, `$ai_span`, `$ai_embedding`, `$ai_metric`, and `$ai_feedback`.
Every event must carry a non-empty string `$ai_model` property, a `distinct_id`, and a client-supplied `uuid`.

## Request format

The body is `multipart/form-data` with at most two parts, in order:

1. `event` (required, first): the event JSON, including `uuid`, `event`, `distinct_id`, and optionally `timestamp`, `sent_at`, and embedded `properties`.
2. `event.properties` (optional): the properties object as its own JSON part.
   Mutually exclusive with embedded `properties` on the event part; sending both is rejected as `ConflictingProperties`.

Any other part name is rejected as `UnknownField`.
This includes the per-property blob parts (`event.properties.<name>`) from a discarded experiment that stored blobs in S3 at capture time;
media now belongs inline in the event JSON, where the ingestion pipeline offloads it content-addressed to S3 and rewrites it to `phaiblob://` pointers.

Authentication is a `Bearer <token>` Authorization header, validated before any decompression work.

### Size limits

- Event part: 32KB (`MAX_EVENT_SIZE`).
- Event + properties combined: 960KB (`MAX_COMBINED_SIZE`, 1MB minus 64KB of headroom).
- Request body: 110% of `AI_MAX_SUM_OF_PARTS_BYTES` (default 25MB), enforced by the router's body limit and the streaming body reader.

### Compression

`Content-Encoding: gzip` on the whole request body is supported and decompressed before multipart parsing.
No other encoding is accepted.

## Processing flow

1. Stream the body in with a timeout, bounded by the body limit.
2. Validate the Bearer token.
3. Gunzip if `Content-Encoding: gzip`.
4. Parse the `event` part only, extracting event name, distinct id, and uuid for the early gates.
5. Early gates: event restrictions (drop/redirect/force-overflow), token dropper (silent 200), AI-gateway provenance verification, then the quota limiter (`LLMEvents` scoped quota, or the global Events quota for verified gateway events).
6. Parse the remaining parts and merge properties onto the event.
7. Validate the full event structure (allowed name, `$ai_model`, distinct id, uuid).
8. Stamp or strip the `$ai_gateway*` provenance namespace depending on signature verification.
9. Build the `ProcessedEvent`, apply overflow stamping, and publish to the Kafka sink.

Failures after the token parses emit customer-facing ingestion warnings (`invalid_ai_event`, `invalid_ai_payload`) through the mapping in `src/ingestion_warnings/ai.rs`;
see that module for which rejections warn and which stay silent.

## Rejections

`AiRejection` in `src/ai_rejection.rs` is the single vocabulary for customer-caused failures:
framing problems (not multipart, bad boundary), part problems (missing or duplicated event part, unknown fields, non-UTF-8 or non-JSON payloads), size limits, and AI-contract violations (disallowed event name, missing `$ai_model`).
Server-side failures (Kafka, serialization) stay `CaptureError` and never surface as customer warnings.

## History

The endpoint originally accepted per-property binary blob parts and stored them in S3 as byte-range-addressed multipart documents, substituting `s3://` URLs into the event properties.
That capability was an experiment that never shipped to SDKs and was removed;
the ingestion-side blob offload (content-addressed `phaiblob://` pointers written by the Node AI pipeline) replaced it.
