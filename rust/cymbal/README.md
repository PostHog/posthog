# Cymbal, for error tracking

You throw 'em, we catch 'em.

Cymbal owns the HTTP ingress and full processing pipeline (fingerprinting,
suppression, Kafka producers, issue linking). The binary runs in one of two
modes selected by `CYMBAL_MODE` (default `processing`): the processing
pipeline, or the `cymbal.resolution.v1` gRPC symbol-resolution service
(`CYMBAL_MODE=resolution`). Symbol resolution can run either inline inside the
processing binary (default) or be offloaded to resolution-mode pods via the
`cymbal.resolution.v1` contract. The remote path is opt-in via
`CYMBAL_REMOTE_RESOLUTION_ENABLED=true` and has **no silent local fallback**
— see the [resolution mode README](src/modes/resolution/README.md) for
rollout, configuration, and operator guidance.

## Remote resolution behavior

The public HTTP contract stays `POST /process`: callers send an array of
events and receive an equally sized array in the same order, with `null` in a
slot only when the normal cymbal pipeline suppresses that event. The
Node.js error-tracking consumer can keep using its existing DNS/team routing
and HTTP body-size chunking because remote symbol resolution happens behind
the same cymbal HTTP boundary.

When remote resolution is enabled, `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE`
controls a deterministic event-level rollout. Events selected for remote
processing are grouped per team, flattened into exception-level `ResolveItem`s,
and submitted over a bidirectional `Resolve` stream. Each item carries JSON
`metadata` bytes for resolver-specific context such as
`debug_images_json`, and each terminal `ResolveOutcome` is correlated by
item id. Sampled remote attempts do not fall back to local resolution if the
remote pool fails; unsampled events use the inline local exception and frame
resolvers and then rejoin the same properties/grouping/linking pipeline.

Backpressure is result-only on the `Resolve` stream: overload is surfaced as
`ResolveOutcome.Error { kind: ERROR_KIND_OVERLOADED }`, which the cymbal client
reroutes with overload-specific backoff. Pods emit `ResolveOutcome.Accepted`
after they admit an item; cymbal limits concurrent unaccepted routing attempts
with a process-local semaphore and releases the permit when acceptance arrives.
When
`CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MS` is non-zero, the overloaded
endpoint is also excluded from new routing in that cymbal process. Repeated
overloads double the endpoint cooldown up to
`CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MAX_MS`, and a quiet
`CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_DECAY_MS` window resets it.
`LoadEvent` carries freshness, draining, and item-concurrency load (`in_flight` / `max_in_flight`).
Cymbal uses that load as a soft routing bias: busier endpoints are less likely to win the rendezvous-ranked candidate list, while stale or draining endpoints remain excluded.
`CYMBAL_REMOTE_RESOLUTION_ROUTING_JITTER` flattens traffic across the load-adjusted rendezvous-ranked candidate list: `0.0` sends traffic to the top load-adjusted endpoint, `1.0` makes selection load-weighted across candidates, and intermediate values decay by rank.

See [`docs/compatibility.md`](docs/compatibility.md) for the Node consumer
compatibility checklist and [`src/modes/resolution/README.md`](src/modes/resolution/README.md)
for rollout and dashboard guidance.

### Terms

We use a lot of terms in this and other error tracking code, with implied meanings. Here are some of them:

- **Issue**: A group of errors, representing, ideally, one bug.
- **Error**: An event capable of producing an error fingerprint, letting it be grouped into an issue. May or may not have one or more stack traces.
- **Fingerprint**: A unique identifier for class of errors. Generated based on the error type and message, and the stack if we have one (with or without raw frames). Notably, multiple fingerprints might be 1 error, because e.g. our ability to process stack frames (based on available symbol sets) changes over time, or our fingerprinting heuristics get better. We do not encode this "class of errors" notions anywhere - it's just important to remember an "issue" might group multiple fingerprints that all have the same "unprocessed" stack trace, but different "processed" ones, or even just that were received at different time.
- **Stack trace**: You know what a stack trace is. A list of frames, raw or otherwise, most recent call last. It's important to keep in mind that some languages have the notion of `chained exceptions`, which means that a single error can have multiple stack traces.
- **Stack context**: The combination of language, operating system, runtime, dev tools, and whatever else that uniquely identifies a "type" of raw frame.
- **Raw frame**: A context specific, unprocessed frame. For some contexts, this means no symbols, for others, it might have symbols but need some other processing.
- **Frame**: A unified representation of a stack frame. Context, and pretty flexible as a result, this is what we output. Frames have all kinds of fields, and can even signal if they're the result of successful resolving or not.
- **Symbol**: A human-readable representation of the function whose calling caused a frame to be pushed. This is what we try to resolve from raw frames, where we can. Some frames don't have an associated symbol, due to e.g. anonymous closures, etc.
- **Resolving**: The generic term we use for going from a raw frame to a frame. The most important step here is symbolification, which is the process of resolving a symbol from a raw frame. That process varies a lot from context to context.
- **Symbol set**: A bunch of bytes, that can be interpreted in some way, to go from a raw frame to a symbol, provided the frame is "in" the symbol set (the function it represents is part of the set of functions whose symbols are in this set). These are highly context specific.
- **Symbol set reference**: Effectively a "pointer" to a symbol set - or the "name" of a symbol set, if you prefer. Uniquely maps a frame to a symbol set. Raw frames are required to be able to produce one of these. Again, these are highly context specific (they're a URL in frontend javascript, for example).
- **Symbol set store**: Anything that can be given a symbol set reference, and try to give back a vec of bytes. We use a layering pattern to construct a single "base" one of these, and then wrap it in internal storing, caching, etc.
