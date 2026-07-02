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
}

export interface ExecuteBatchOptions {
    /** Fan the batch out over a rayon thread pool instead of running sequentially. */
    parallel?: boolean
    /** Step budget per execution (the Rust VM has no wall-clock timeout). */
    maxSteps?: number
}

/**
 * Load process-wide state for the transformation host functions. Idempotent; only the first call
 * takes effect.
 */
export function init(options: InitOptions): void

/**
 * Run one Hog program (bytecode tokens) against many event-globals, off the JS event loop.
 * Returns one structured result per event, in input order.
 */
export function executeBatch(
    program: unknown[],
    events: unknown[],
    options?: ExecuteBatchOptions
): Promise<HogExecResult[]>
