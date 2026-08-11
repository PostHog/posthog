# Fixing AI endpoint rejections

Covers `invalid_ai_event`, `invalid_ai_payload`, and `no_ai_spans_ingested`.

These come from capture's two dedicated LLM analytics endpoints, not from the ingestion pipeline:

- `/i/v0/ai` — one event per request, sent as multipart with an `event` part and an optional `event.properties` part. Warnings carry `path: ai_events`.
- `/i/v0/ai/otel` — OTLP trace export, protobuf or JSON. Warnings carry `path: ai_otel`.

Both reject at the edge, so a rejected event reaches nothing downstream. It is not in `events`, not in any insight, and has no other trace beyond the warning. `count` is the number of events or spans that didn't land.

Check `lib` and `libVersion` first on every one of these. A rejection concentrated on one SDK version is an upgrade, not a payload problem.

## `invalid_ai_event`

The event reached the endpoint and parsed, but isn't a valid AI event.

Two causes, told apart by the details:

**An unsupported event name** (`eventName` is present). The endpoint accepts only `$ai_generation`, `$ai_trace`, `$ai_span`, `$ai_embedding`, `$ai_metric`, and `$ai_feedback`. Anything else is rejected.

If `eventName` is something like `$pageview` or a custom event, ordinary analytics is being pointed at the AI endpoint. That is usually a misconfigured host or proxy rule rather than deliberate. Send those to `/i/v0/e` or `/batch` instead. If it looks like an AI event with the wrong name (`ai_generation` without the `$`, or `$ai_completion`), fix the name at the callsite.

**No usable `$ai_model`** (no `eventName` in the details). Every AI event must carry `$ai_model` as a non-empty string. A model set to `null`, a number, or an empty string is rejected the same as a missing one. This usually means the value is unset at the callsite: the variable holding the model name is empty when the provider call fails early, or the SDK wrapper wasn't given a model.

## `invalid_ai_payload`

The request body couldn't be used. Read the details to see which check failed.

**`format`** is present for OTLP decode failures, and names what the content-type resolved to:

- `format: unknown` — the content-type itself is wrong. OTLP requires `application/x-protobuf` or `application/json`. An exporter sending `application/octet-stream` or no content-type lands here.
- `format: protobuf` or `json` — the content-type was right but the body didn't match it. Check for a proxy that rewrites or re-compresses request bodies, and for a `content-encoding` other than gzip, which is the only one supported.

**`stage`** and `spanCount` are present when an export carried too many spans. `stage: raw` means more than 1000 spans arrived before filtering; `stage: ai` means more than 100 AI spans survived filtering. Both mean the exporter needs a smaller batch size or a shorter flush interval. `limit` is the cap that was exceeded.

**`part`** is present for multipart problems on `/i/v0/ai`, naming the offending part. The only valid parts are `event` and `event.properties`; anything else is rejected. Per-property blob parts (`event.properties.<name>`) were a discarded experiment and are no longer accepted: media belongs inline in the event JSON, where ingestion offloads it to blob storage.

**Neither** means the multipart framing itself was wrong, or the event part wasn't valid UTF-8 JSON.

Note the deliberate omission: the underlying parser error is not in the details. It can contain arbitrary payload bytes, so it stays in capture's logs.

## `no_ai_spans_ingested`

This one is different: the request succeeded. The exporter got a `200` and no error, and nothing was ingested.

It fires when an OTLP export carried spans but none of them were AI spans. `rawSpanCount` is how many arrived.

Capture keeps a span only if its attributes match a known AI provider convention: `gen_ai.*`, `ai.*`, `eve.*`, `traceloop.*`, `pydantic_ai.*`, or `llm.request.type`. Everything else is dropped as ordinary tracing, which is correct behavior for a mixed batch. This warning means _every_ span in the request was dropped that way.

Almost always one of:

- **OTLP traces are being exported to PostHog wholesale.** A generic tracing setup was pointed at `/i/v0/ai/otel` without filtering, so HTTP and database spans arrive with no AI spans among them. Restrict the exporter to the AI instrumentation, or accept that non-AI batches produce nothing.
- **The LLM instrumentation isn't loaded.** The exporter works, but the library that adds `gen_ai.*` attributes isn't installed or initialized, so the LLM calls emit plain spans. Confirm the AI instrumentation package is registered before the provider client is constructed.
- **A custom or unsupported convention.** Hand-rolled spans using in-house attribute names won't match. Rename them to the `gen_ai.*` semantic conventions.

To see what is actually arriving, pull the spans' attribute keys from your own tracing backend rather than from PostHog. Nothing reached PostHog to inspect.

A mixed batch that contains at least one AI span does **not** warn, so a team seeing this occasionally alongside successful ingestion is sending some batches with no AI activity in them. That is usually benign. Sustained firing with no AI events landing is the case worth acting on.
