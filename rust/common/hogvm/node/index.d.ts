export interface InitOptions {
    /** Path to a GeoLite2/GeoIP2 City mmdb file, enables the geoipLookup host function. */
    mmdbPath?: string
    /** Lowercased substrings matched against user agents by isKnownBotUserAgent. */
    knownBotUaList?: string[]
    /** Exact IPs matched by isKnownBotIp. */
    knownBotIpList?: string[]
}

export interface HogExecResult {
    /** The program's return value; null/undefined when the execution errored. */
    result?: unknown
    error?: string
    durationUs: number
    /** Messages from print() calls, in call order, capped at 24 entries. */
    logs?: string[]
    /** True when print() was called past the cap and messages were dropped. */
    logsTruncated?: boolean
}

export interface ExecuteSyncOptions {
    /** Step budget for the execution (the Rust VM has no wall-clock timeout). */
    maxSteps?: number
}

/**
 * Load process-wide state for the transformation host functions. Idempotent; only the first call
 * takes effect.
 */
export function init(options: InitOptions): void

/**
 * Run one Hog program against one event-globals synchronously on the calling thread. This is the
 * primary-execution path for ingestion transformations: it matches the Node VM's synchronous
 * exec, with no threadpool round-trip.
 */
export function executeSync(program: unknown[], globals: unknown, options?: ExecuteSyncOptions): HogExecResult
