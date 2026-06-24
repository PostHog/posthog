# Durable streaming: what we have and what is missing

This is a concept-level assessment of the agent-proxy live event plane against the
high-level ideas of durable streaming: resumability, ordering, idempotent append,
durable closure and gap awareness. It is **not** a wire-conformance check against the
durable-streams.com protocol. agent-proxy stays byte-identical to the Python proxy
during the cutover, so it cannot share that protocol's wire format, and that is by
design. What follows is purely about the guarantees the streaming layer provides and
where it falls short, regardless of how they are framed on the wire.

Reference concepts:

- <https://durablestreams.com/building-a-server>
- <https://durablestreams.com/building-a-client>
- <https://github.com/durable-streams/durable-streams/blob/main/PROTOCOL.md>

## What we have

- **Resumability.** A client reconnects from its last position (`Last-Event-ID`) and the
  server replays forward from there. This is the core durable-streaming property and it
  is solid. See the read leg in `src/hono/app.ts` and `streamTaskRunEvents` in
  `src/hono/sse-handler.ts`.
- **Stable, ordered positions.** Every event has a monotonic id (the Redis stream id);
  events are delivered in a strict, stable order. See `src/lib/redis-stream.ts`.
- **Catch-up then live.** A reader gets history from the start, or `?start=latest` to skip
  to the tail, then seamlessly tails live from the same connection. The two modes are
  fused rather than separate endpoints.
- **No-skip and no-duplicate delivery within the retention window.** Resume is exclusive
  of the last id, so inside the live window a client neither re-receives nor skips events.
- **Idempotent, ordered append.** The ingest `seq` enforces contiguous ordering (a gap is
  rejected) and a replayed `seq` is deduplicated rather than re-appended, so the producer
  can retry safely. This is effectively exactly-once on the write side for a single
  producer. See `writeEventWithSequence` in `src/lib/redis-stream.ts`.
- **Completion consistency.** Closing the stream verifies the final sequence matches what
  was accepted, so the stream cannot be marked complete past a hole. See
  `markCompleteAfterSequence`.
- **Durable, observable EOF.** The `stream-end` sentinel plus the persisted `completed`
  marker mean a late reader still learns the stream ended, and the client honors it to
  stop reconnecting.
- **Liveness and reconnect robustness.** Keepalives, reconnect backoff, a cumulative
  retry budget and a "keepalive proves recovery" reset. The client distinguishes
  transport cuts from backend errors (in the `cloud-task` watcher on the client side).
- **Backpressure to slow readers.** The SSE writer awaits each chunk
  (`responseStream.write`), so a slow consumer naturally throttles the read loop.
- **Multi-reader fan-out.** Several clients can independently tail the same run, each with
  its own cursor and its own dedicated Redis connection.

## What is missing or partial

Ranked by how much it matters for the current use case (watching a live agent run).

1. **Gap awareness (the real hole).** The server **detects** when a reader's resume point
   has been trimmed out of the window (`resumePointTrimmed` / `detectResumeGap` in
   `src/lib/redis-stream.ts`, surfaced as the `stream:resume_gap` metric) but it does
   **not tell the reader**. It silently continues from the oldest surviving event. So a
   client that reconnects after a long gap, or watches a long run, can silently miss a
   span of events and never know. Durable streaming's whole point is that the reader
   either receives every event or is explicitly told it lost some. This is already a known
   deferral: S3 hydration on resume gap is out of scope for now (see the `ResumeGap`
   comment in `src/lib/types.ts` and `DESIGN.md`). Closing it means either a
   client-visible "you missed events from A to B" signal, a backfill from durable storage,
   or both.
2. **Bounded retention.** "Durable" here means roughly a 6h TTL plus a ~20k event
   `MAXLEN` (`STREAM_TTL_SECONDS`, `STREAM_MAX_LENGTH` in `src/lib/constants.ts`), after
   which data is gone. That bound is the cause of gap awareness above. It is fine for
   watching a run live, but not for replaying a run's stream much later. If long replay
   becomes a goal, this is the lever.
3. **No "caught up to the tail" signal.** A reader cannot tell when it transitions from
   replaying history to being live at the tail. This is minor for a live UI, which just
   keeps tailing, but it is a real durable-streaming concept that is not exposed.
4. **No producer fencing.** The `seq` protocol gives ordering and deduplication for one
   writer, but nothing fences out a second or zombie writer to the same run (for example a
   retried or duplicated sandbox). We rely on "one sandbox per run" by construction. If
   that assumption can break, two producers could interleave and we would only catch it as
   sequence gaps, not as "you are not the active writer."
5. **Not needed for this use case, noted for completeness.** Stream forking, durable
   multi-consumer subscriptions (webhooks or pull-wake) and consumer-group coordination.
   These are durable-streaming features we do not have and almost certainly do not want
   here.

## Summary

| Concept                                      | Status                                    |
| -------------------------------------------- | ----------------------------------------- |
| Resume from last position                    | Have                                      |
| Stable ordered positions                     | Have                                      |
| Catch-up then live tail                      | Have                                      |
| No-skip / no-duplicate within window         | Have                                      |
| Idempotent, ordered append (single producer) | Have                                      |
| Completion consistency                       | Have                                      |
| Durable, observable EOF                      | Have                                      |
| Keepalive, reconnect robustness              | Have                                      |
| Backpressure to slow readers                 | Have                                      |
| Multi-reader fan-out                         | Have                                      |
| Gap awareness on trimmed resume              | **Missing** (detected, not signalled)     |
| Retention beyond ~6h / ~20k                  | **Partial** (bounded, then dropped)       |
| Caught-up-to-tail signal                     | Missing                                   |
| Producer fencing across writers              | Partial (single-producer by construction) |
| Forking / subscriptions / consumer groups    | Missing (not needed)                      |

We have resumability, ordering, idempotent append and durable closure, which is the meat
of durable streaming. The two gaps that actually matter are **gap awareness** (the silent
skip on trimmed resume) and the **bounded retention** behind it. Everything else missing
is either cosmetic (the caught-up signal) or out of scope (forking, subscriptions). The
important one is already on the roadmap as deferred S3 hydration.
