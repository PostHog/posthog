/**
 * Polling cadence schedule for the Redis-backed bus.
 *
 * The schedule is intentionally a tiny, pure data structure rather than a
 * loop or generator — that makes it trivial to unit-test (a few asserts on
 * the output of `nextDelay`) and lets the bus's polling loop stay
 * single-purpose.
 *
 * Cadence chosen to match how users interact with confirmation modals:
 * - The first ~5 seconds, poll fast (200ms). Most clicks land here.
 * - After that, slow to 1s/poll — the user is reading, thinking, or AFK.
 *
 * This is a heuristic, not a science. The numbers can be tuned without
 * any change to the bus contract.
 */

export interface AdaptivePollSchedule {
    /**
     * Compute the delay (ms) before the next poll, given the time elapsed
     * since the await started.
     */
    nextDelay(elapsedMs: number): number
}

export interface AdaptivePollConfig {
    /** Delay during the "hot" window (first {@link hotWindowMs} ms). */
    hotIntervalMs: number
    /** Delay after the hot window. */
    coolIntervalMs: number
    /** Duration of the hot window in ms. */
    hotWindowMs: number
}

export const DEFAULT_ADAPTIVE_POLL_CONFIG: AdaptivePollConfig = {
    hotIntervalMs: 200,
    coolIntervalMs: 1_000,
    hotWindowMs: 5_000,
}

export function createAdaptivePollSchedule(
    config: AdaptivePollConfig = DEFAULT_ADAPTIVE_POLL_CONFIG
): AdaptivePollSchedule {
    validateConfig(config)
    return {
        nextDelay(elapsedMs: number): number {
            if (elapsedMs < 0) {
                return config.hotIntervalMs
            }
            return elapsedMs < config.hotWindowMs ? config.hotIntervalMs : config.coolIntervalMs
        },
    }
}

function validateConfig(config: AdaptivePollConfig): void {
    if (config.hotIntervalMs <= 0 || config.coolIntervalMs <= 0) {
        throw new Error('Poll intervals must be positive')
    }
    if (config.hotWindowMs < 0) {
        throw new Error('Hot window must be non-negative')
    }
    if (config.hotIntervalMs > config.coolIntervalMs) {
        throw new Error(
            'Hot interval must be shorter than cool interval — adaptive polling exists to be faster early, not slower'
        )
    }
}
