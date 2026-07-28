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
 * Run one Hog program against one event-globals synchronously on the calling thread. This is the
 * primary-execution path for ingestion transformations: it matches the Node VM's synchronous
 * exec, with no threadpool round-trip.
 */
export function executeSync(program: unknown[], globals: unknown, options?: ExecuteSyncOptions): HogExecResult

/**
 * Run one Hog program (bytecode tokens) against many event-globals, off the JS event loop,
 * crossing the FFI boundary once for the whole batch. Returns one result per event, in input
 * order. An event whose globals can't be converted to JSON (e.g. NaN/Infinity numbers) gets a
 * `marshal_error:`-prefixed error result instead of rejecting the whole call.
 */
export function executeBatch(
    program: unknown[],
    events: unknown[],
    options?: ExecuteBatchOptions
): Promise<HogExecResult[]>

/**
 * Validate and token-decode a program once, returning a handle for `executeRegisteredSync`, so a
 * program executed repeatedly isn't re-marshalled and re-decoded per call. Invalid bytecode still
 * gets a handle — executions through it report the validation error.
 */
export function registerProgram(program: unknown[]): number

/**
 * Drop a registered program and free its slot for reuse. Releasing an unknown or already-released
 * handle is a no-op. A handle must not be executed after it is released.
 */
export function releaseProgram(handle: number): void

/** `executeSync` against a program registered with `registerProgram`. */
export function executeRegisteredSync(
    handle: number,
    globals: unknown,
    options?: ExecuteSyncOptions
): HogExecResult

/** Batch variant: one napi crossing for many events, amortizing the marshalling overhead. */
export function executeRegisteredBatchSync(
    handle: number,
    events: unknown[],
    options?: ExecuteSyncOptions
): HogExecResult[]
