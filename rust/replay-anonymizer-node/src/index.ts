/* eslint-disable @typescript-eslint/no-var-requires */
// The native addon is built from `src/lib.rs` and copied to `index.node` at the package root.
const native = require('../index.node')

export interface AllowListsInput {
    /** Words kept verbatim by the text scrubber (ASCII-case-insensitive). */
    text: string[]
    /** URL path segments/params kept verbatim by the URL scrubber. */
    url: string[]
}

/** Per emitted JSONL line, in line order. */
export interface AnonymizeEventMeta {
    /** The event's `timestamp` (epoch ms; can be fractional). */
    ts: number
    /** Bitmask of the FLAG_* bits in `snapshot.rs` (mirrored as PRE_SERIALIZED_FLAG_* in the consumer). */
    flags: number
    /** Post-scrub `hrefFrom(event)` (`data.href` / `data.payload.href`, trimmed), when present. */
    href?: string
}

/** One collected original image: `offset..offset+len` in {@link AnonymizeKafkaPayloadResult.images}. */
export interface AnonymizeImageEntry {
    /** First 22 base64url chars of `HMAC-SHA256(contentKey, bytes)` (`hashImageBytes` in content-ref.ts). */
    hash: string
    offset: number
    len: number
}

/** One collected remote image URL, ready for the fetch lane. */
export interface AnonymizeUrlEntry {
    /** First 22 base64url chars of `HMAC-SHA256(urlKey, dedupUrl)`, where the dedup URL is the
     *  canonical URL minus its volatile parameters. The namespaced ref attribute ends with this. */
    hash: string
    /** The canonical URL with every parameter intact — what the fetcher requests. A signed URL only
     *  works in this form, which is why it is not the value the hash was taken over. */
    url: string
    /** The host the request goes to. robots.txt and the connection limit are scoped to this. */
    host: string
    /** The registrable domain of `host`. The fetch topic keys on this, so every URL of one operator
     *  lands on one partition and one pod holds its rate budget without a distributed lock. */
    domain: string
}

export interface AnonymizeImageSourceCount {
    source: 'css' | 'html'
    property: string
    kind: 'inline' | 'url'
    count: number
}

/** Envelope + per-event metadata parsed from {@link AnonymizeKafkaPayloadResult.meta}. */
export interface AnonymizeMeta {
    distinctId: string
    /** Raw `$session_id` — normalization stays in TS. */
    sessionId: string
    /** `$window_id ?? ''`. */
    windowId: string
    snapshotSource: string | null
    snapshotLibrary: string | null
    /** Min/max valid-event timestamps (epoch ms). */
    startTs: number
    endTs: number
    /** rrweb/console@1 plugin events by level. */
    consoleLogCount: number
    consoleWarnCount: number
    consoleErrorCount: number
    events: AnonymizeEventMeta[]
    /** Collected original images (hash-sorted); present only when the collection lane was enabled and images were collected. */
    images?: AnonymizeImageEntry[]
    /** Collected remote image URLs (hash-sorted); present only when the URL lane was enabled and URLs were collected. */
    urls?: AnonymizeUrlEntry[]
    /** Collected ref occurrences by bounded replay location, property, and inline or URL lane. */
    imageSources?: AnonymizeImageSourceCount[]
    /** Counts by reason for the URLs the collector refused. Absent when it refused none. */
    urlDeclines?: { reason: string; count: number }[]
}

/**
 * Phase timings for one {@link anonymizeKafkaPayload} call, reported on success and failure alike
 * (including contained panics). All offsets are monotonic nanoseconds from the moment the addon
 * was invoked on the JS thread; a `null` boundary means the phase was never reached.
 */
export interface AnonymizeTimings {
    /** Threadpool pickup — this offset IS the libuv queue wait. */
    taskStartNs: number | null
    decompressStartNs: number | null
    decompressEndNs: number | null
    scrubStartNs: number | null
    scrubEndNs: number | null
    /** Accumulated cv de/recompression time across all events in the message. */
    cvTotalNs: number
    cvCount: number
    /** Accumulated image blur/pixelate time (cache misses only). */
    blurTotalNs: number
    blurCount: number
    /**
     * The op in flight when processing stopped: `done` on success, else the phase or op
     * (`queued` | `decompress` | `scrub` | `cv` | `blur` | `serialize_meta`) that was running.
     */
    lastOp: string
}

export interface AnonymizeKafkaPayloadResult {
    /** True if the message could not be anonymized — the caller must drop or DLQ it (fail-closed). */
    failed: boolean
    /**
     * Failure classification when `failed`, matching the TS parse step's dlq/drop reasons:
     * `invalid_json` | `invalid_message_payload` | `received_non_snapshot_message` |
     * `message_contained_no_valid_rrweb_events` | `anonymize_failed`.
     */
    reason: string | null
    /** Failure detail when `failed`, else `null`. */
    error: string | null
    /** Scrubbed JSONL block lines (`["<windowId>",<event>]\n` per valid event), ready to write. */
    lines: Buffer | null
    /** JSON-serialized {@link AnonymizeMeta}. */
    meta: string | null
    /**
     * Which implementation produced the output (differential-tested identical). `tree` means the
     * whole-message parse fallback fired; the label is an A/B / fallback-rate signal.
     */
    route: 'stream' | 'tree' | null
    /** Phase timings; present on success and failure alike. `null` only if serialization failed. */
    timings: AnonymizeTimings | null
    /** Original bytes of the collected images, concatenated in `meta.images` order; null when none. */
    images: Buffer | null
}

/** Initialize the process-wide allow lists. Call once at startup before {@link anonymizeKafkaPayload}. */
export function initAnonymizer(allow: AllowListsInput): void {
    native.initAnonymizer(JSON.stringify(allow))
}

/**
 * Anonymize a replay Kafka payload (`{"distinct_id": ..., "data": "<event json>"}`). Rust owns the
 * decompression (lz4 via the `content-encoding` header, gzip via magic bytes), the parse, the
 * scrub, and the serialize; only the raw bytes cross the FFI boundary. CPU work — including the
 * decompression — runs off the Node event loop.
 *
 * `cv` payloads re-emit as zstd; the reader dispatches on magic bytes.
 *
 * Non-empty `pseudoTeam` + `contentKey` (the per-team HMAC pseudonym and content-hash key — never
 * the raw team id or master secret) enable the image-collection lane: inlined images are replaced
 * with `image:<pseudoTeam>:<hash>` refs (hash = keyed HMAC of the bytes) instead of the inline
 * blur, and the original bytes come back in `images`/`meta.images` for the caller to produce to
 * the scrub topic.
 *
 * `urlKey` enables the URL-collection lane independently. It is the global URL HMAC key. A remote
 * image's `src` keeps the media placeholder, a namespaced sibling attribute carries its ref, and
 * its original URL comes back in `meta.urls` for the caller to hand to the fetch lane.
 *
 * The two lanes are independent: either, both, or neither. Only `contentKey` needs `pseudoTeam`.
 */
export async function anonymizeKafkaPayload(
    payload: Buffer,
    contentEncoding?: string | null,
    pseudoTeam?: string | null,
    contentKey?: string | null,
    urlKey?: string | null
): Promise<AnonymizeKafkaPayloadResult> {
    const result = await native.anonymizeKafkaPayload(
        payload,
        contentEncoding ?? undefined,
        pseudoTeam ?? undefined,
        contentKey ?? undefined,
        urlKey ?? undefined
    )
    // Timings are best-effort telemetry: a malformed timings blob must never fail the message.
    let timings: AnonymizeTimings | null = null
    if (typeof result.timings === 'string') {
        try {
            timings = JSON.parse(result.timings)
        } catch {
            timings = null
        }
    }
    return { ...result, timings }
}

/**
 * The politeness unit for a host: the registrable domain, or the host itself when it has none.
 *
 * The fetch lane rate limits by this value and the fetch topic keys on it, so both must get the
 * same answer from one public suffix list, which is why the value comes from the Rust crate. The
 * private section of that list keeps `user.github.io` and `d111.cloudfront.net` out of a shared
 * budget with the other tenants of the same provider.
 *
 * An IP literal has no registrable domain and comes back unchanged, because the address is the
 * operator.
 */
export function politenessKey(host: string): string {
    return native.politenessKey(host)
}

/**
 * Whether the fetch lane may send a request to a host.
 *
 * The collector applies this rule before a URL reaches the topic. A redirect target has not been
 * through it, so the fetcher calls the same function rather than deriving a second answer.
 *
 * It refuses a private or reserved address, a single-label name, and a name under a suffix that
 * resolves only inside one network, which is the split-horizon DNS case.
 */
export function isPublicHost(host: string): boolean {
    return native.isPublicHost(host)
}

export interface CanonicalUrl {
    fetch: string
    dedup: string
    host: string
    domain: string
}

export function canonicalizeUrl(url: string): CanonicalUrl | null {
    return native.canonicalizeUrl(url)
}
