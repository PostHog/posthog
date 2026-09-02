# Cymbal, for error tracking

You throw 'em, we catch 'em.

Cymbal owns the HTTP ingress and full processing pipeline (fingerprinting,
suppression, Kafka producers, issue linking). The binary runs in one of three
modes selected by `CYMBAL_MODE` (default `processing`): the processing
pipeline, the `cymbal.resolution.v1` gRPC symbol-resolution service
(`CYMBAL_MODE=resolution`), or the Kafka notification consumer
(`CYMBAL_MODE=notifications`). The notification consumer starts the matching
Temporal lifecycle workflow for every issue-created, issue-reopened, or
issue-spiking notification. Issue-created is capped per team per hour (see
[Issue-created rate limit](#issue-created-rate-limit-notifications-mode)).

## Issue-created rate limit (notifications mode)

Notifications mode caps issue-created workflow starts per team. One Redis token
bucket per team, so a team that exhausts it gets no issue-created workflow, and
therefore no embedding and no alert for new issues, until the bucket refills.

The setting is both the bucket size and the hourly refill. A team that sits idle,
spends the full bucket, then waits out the refill, gets up to twice the setting
inside one rolling hour. The sustained rate is the setting. Size Temporal worker
and embedding capacity against the peak rather than the sustained rate.

Only issue-created is charged. It is the one notification type with no ceiling of
its own, because a high-cardinality fingerprint mints issues as fast as a team
sends events. Reopens need somebody to have resolved the issue first, and spikes
already carry a per-issue Redis cooldown. Issue-created is also the only type
that runs an embedding. A throttled team therefore keeps its reopen and spike
alerts.

The gate sits in the consumer rather than in processing mode, because the
consumer is what starts the workflows. The Kafka payload carries no decision, so
a replayed notification is judged the same way every time. `start_workflow` is
idempotent on the workflow id, so a replay starts nothing, and the token it
charged is credited back. `cymbal_issue_created_rate_limit_refunds` counts those
credits, under an `error` label when the credit itself failed and the team kept
the charge.

A Redis failure while the consumer is running fails open: the notification is
admitted and `cymbal_issue_created_rate_limit_fail_open` goes up, because a
limiter outage must not silence alerts. A Redis that is configured but
unreachable at startup is fatal instead, so a pod cannot come up and quietly run
without the limit it was told to enforce.

The variables are prefixed by the service, while the metrics and the Redis key
are named for what is actually capped. Only issue-created is charged.

| Variable | Default | Effect |
| --- | --- | --- |
| `ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_REDIS_URL` | none | Required. The service does not start without it. |
| `ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_PER_HOUR` | `1000` | Bucket size, and the tokens a team earns back per hour. Zero or less disables the limit. |
| `ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_KEY_PREFIX` | `@posthog/error-tracking-notifications-rate-limiter` | Key namespace. It must differ from the event limiter's prefix. |
| `ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_BUCKET_TTL_SECONDS` | `3600` | Idle buckets expire and free the memory. A value below 3600 is raised to 3600, because a bucket takes an hour to refill and a shorter TTL would loosen the limit. |

The limit covers every team. To size it before it cuts anything, set `PER_HOUR`
far above real traffic, watch `cymbal_issue_created_rate_limit_outcomes`, then
lower it. Setting `PER_HOUR` to zero or less switches the limit off.

Set the Redis URL in every environment before this ships. It carries no default,
so a pod without it fails to start.

That counter carries an `outcome` label of `admitted` or `limited`, never both,
so the two series sum to the notifications the limiter judged.

The bucket lives in
[`src/modes/notifications/token_bucket.rs`](src/modes/notifications/token_bucket.rs).
It is deliberately separate from the per-event limiter in processing mode, which
runs at event volume and charges a variable number of tokens against two fused
keys.

Symbol resolution runs in resolution-mode pods via the
`cymbal.resolution.v1` contract. Processing has no inline fallback.
See the [resolution mode README](src/modes/resolution/README.md) for
configuration and operator guidance.

## Remote resolution behavior

The public HTTP contract stays `POST /process`: callers send an array of
events and receive an equally sized array in the same order, with `null` in a
slot only when the normal cymbal pipeline suppresses that event. The
Node.js error-tracking consumer can keep using its existing DNS routing
and HTTP body-size chunking because remote symbol resolution happens behind
the same cymbal HTTP boundary.

Events are flattened into exception-level `ResolveItem`s, grouped by a
symbol-set routing key when one is available, and submitted over a
bidirectional `Resolve` stream. Items without a symbol-set reference fall back
to the existing per-team key. Each item carries JSON
`metadata` bytes for resolver-specific context such as
`debug_images_json`, and each terminal `ResolveOutcome` is correlated by
item id. Resolution failures do not fall back to inline processing.

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
for dashboard guidance.

Fetched JavaScript sources and external source maps are limited to 25 MB after HTTP decompression by default. Set `SOURCEMAP_MAX_RESPONSE_BYTES` to adjust this limit.

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
