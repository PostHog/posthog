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
    jsonLd?: { rootTypes: string[]; fullSnapshotTimestamp?: number }
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
    jsonLdEventCount: number
    events: AnonymizeEventMeta[]
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
    collectedImages: CollectedImageBatch | null
    collectedUrls: CollectedUrlBatch | null
    dedupedImageCount?: number
    dedupedUrlCount?: number
    /** Distinct registrable domains among the collected URLs, counted before the dedup drop. */
    collectedUrlDomainCount?: number
}

export interface RefDedupCacheStats {
    entries: number
    evictions: number
    /** Sampled misses on a ref that a cache of twice the capacity would still have held. */
    wouldHit: number
    wouldMiss: number
}

/** The entries live outside the V8 heap, so a full cache adds nothing for a major GC to mark. A capacity of 0 turns dedup off. */
export class RefDedupCache {
    /** The addon's handle. Only this package reads it. */
    readonly nativeHandle: unknown

    constructor(capacity: number) {
        this.nativeHandle = native.refDedupCacheNew(capacity)
    }

    stats(): RefDedupCacheStats {
        return native.refDedupCacheStats(this.nativeHandle)
    }
}

interface NativeBatch {
    handle: unknown
    count: number
    firstRef: string
}

export interface ClaimedImages {
    refs: string[]
    images: Buffer[]
    bytes: number
}

/** Every ref in the batch has the namespace of `firstRef`, so one check of `firstRef` covers them all. */
export class CollectedImageBatch {
    private readonly nativeHandle: unknown
    readonly count: number
    readonly firstRef: string

    constructor(batch: NativeBatch) {
        this.nativeHandle = batch.handle
        this.count = batch.count
        this.firstRef = batch.firstRef
    }

    static fromImages(namespace: string, images: { hash: string; bytes: Buffer }[]): CollectedImageBatch | null {
        const batch: NativeBatch | null = native.imageBatchNew(
            namespace,
            images.map(({ hash }) => hash),
            images.map(({ bytes }) => bytes)
        )
        return batch ? new CollectedImageBatch(batch) : null
    }

    /** Moves out the images whose refs no earlier claim marked. A second claim throws. */
    claim(cache: RefDedupCache): ClaimedImages {
        return native.imageBatchClaim(this.nativeHandle, cache.nativeHandle)
    }

    release(cache: RefDedupCache): void {
        native.imageBatchRelease(this.nativeHandle, cache.nativeHandle)
    }
}

export interface UrlRecordOptions {
    /** The entries with these refs stay out of the records but stay marked in the cache. */
    excludedRefs: string[]
    sessionId: string | null
    firstSeenAtMs: number
    /** A single job above this still gets a record of its own. */
    maxRecordBytes: number
    maxRecordUrls: number
}

export interface UrlRecords {
    keys: string[]
    values: Buffer[]
    urlCounts: Uint32Array
    urlByteLengths: Uint32Array
    domainCount: number
}

/** Every ref in the batch has the namespace of `firstRef`, so one check of `firstRef` covers them all. */
export class CollectedUrlBatch {
    private readonly nativeHandle: unknown
    readonly count: number
    readonly firstRef: string

    constructor(batch: NativeBatch) {
        this.nativeHandle = batch.handle
        this.count = batch.count
        this.firstRef = batch.firstRef
    }

    static fromUrls(
        referenceNamespace: string | null,
        urls: { hash: string; url: string; domain: string }[]
    ): CollectedUrlBatch | null {
        const batch: NativeBatch | null = native.urlBatchNew(
            referenceNamespace ?? undefined,
            urls.map(({ hash }) => hash),
            urls.map(({ url }) => url),
            urls.map(({ domain }) => domain)
        )
        return batch ? new CollectedUrlBatch(batch) : null
    }

    /** Keeps the transport URLs that no earlier claim marked in this time bucket. A second claim throws. */
    claim(cache: RefDedupCache, timeBucket: number): number {
        return native.urlBatchClaim(this.nativeHandle, cache.nativeHandle, timeBucket)
    }

    uniqueRefs(): string[] {
        return native.urlBatchUniqueRefs(this.nativeHandle)
    }

    buildRecords(options: UrlRecordOptions): UrlRecords {
        return native.urlBatchBuildRecords(
            this.nativeHandle,
            options.excludedRefs,
            options.sessionId ?? undefined,
            options.firstSeenAtMs,
            options.maxRecordBytes,
            options.maxRecordUrls
        )
    }

    release(cache: RefDedupCache): void {
        native.urlBatchRelease(this.nativeHandle, cache.nativeHandle)
    }
}

/**
 * The produce lanes' caches, consulted inside the anonymize call without marking. An image or URL
 * whose ref the cache holds is left out of the result, so it never reaches the JS heap. The caller
 * still claims what comes back before it produces.
 */
export interface ProducedRefDedup {
    images?: RefDedupCache
    urls?: RefDedupCache
    urlTimeBucket?: number
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
 * Non-empty `teamId` + `contentKey` enable image collection using the raw team ID and per-team
 * content HMAC key. The master secret stays with the caller. Inlined images are replaced
 * with `image:<teamId>:<hash>` refs (hash = keyed HMAC of the bytes) instead of the inline
 * blur, and the original bytes come back in `collectedImages` for the caller to produce to the
 * scrub topic.
 *
 * `urlKey` enables the URL-collection lane independently. It is the global URL HMAC key. A remote
 * image's `src` keeps the media placeholder, a namespaced sibling attribute carries its ref, and
 * its original URL comes back in `collectedUrls` for the caller to hand to the fetch lane.
 * `referenceNamespace` scopes URL refs as `imageurl:<namespace>:<hash>`; omitting it produces
 * `imageurl:<hash>`. For v2, pass `v2:<raw team id>:<YYYY-MM>` as both `teamId` and `referenceNamespace`.
 *
 * The two lanes are independent: either, both, or neither. Only `contentKey` needs `teamId`.
 *
 * `producedRefDedup` leaves out the collected images and URLs that an earlier message already produced.
 */
export async function anonymizeKafkaPayload(
    payload: Buffer,
    contentEncoding?: string | null,
    teamId?: string | null,
    contentKey?: string | null,
    urlKey?: string | null,
    referenceNamespace?: string | null,
    producedRefDedup?: ProducedRefDedup
): Promise<AnonymizeKafkaPayloadResult> {
    const { imageBatch, urlBatch, ...result } = await native.anonymizeKafkaPayload(
        payload,
        contentEncoding ?? undefined,
        teamId ?? undefined,
        contentKey ?? undefined,
        urlKey ?? undefined,
        referenceNamespace ?? undefined,
        producedRefDedup?.images?.nativeHandle,
        producedRefDedup?.urls?.nativeHandle,
        producedRefDedup?.urlTimeBucket
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
    return {
        ...result,
        timings,
        collectedImages: imageBatch ? new CollectedImageBatch(imageBatch) : null,
        collectedUrls: urlBatch ? new CollectedUrlBatch(urlBatch) : null,
    }
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

/** The labels of the Rust `Decline` enum. The fetch lane reports them as metric reasons. */
export type UrlPolicyDecline =
    | 'too_long'
    | 'not_absolute'
    | 'bad_scheme'
    | 'bad_port'
    | 'no_host'
    | 'non_public_host'
    | 'credential'
    | 'invalid_query'
    | 'tracking_beacon'

/**
 * The canonical forms of a URL the policy accepts, or the rule that refused it. `unwanted` is true
 * when the URL is well formed and safe but nobody wants it fetched, so a queue consumer drops only
 * that job instead of rejecting the record that carries it.
 */
export type UrlPolicyVerdict =
    | { ok: true; url: CanonicalUrl }
    | { ok: false; decline: UrlPolicyDecline; unwanted: boolean }

export function tryCanonicalizeUrl(url: string): UrlPolicyVerdict {
    const result = native.tryCanonicalizeUrl(url)
    if (typeof result.decline === 'string') {
        return {
            ok: false,
            decline: result.decline,
            unwanted: result.unwanted === true,
        }
    }
    return { ok: true, url: result }
}

export function canonicalizeUrl(url: string): CanonicalUrl | null {
    const verdict = tryCanonicalizeUrl(url)
    return verdict.ok ? verdict.url : null
}
