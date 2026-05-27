import { logger as defaultLogger, type Logger } from '../logger'

/**
 * Lightweight async-op timing helper.
 *
 * Wrap any operation and pino emits a structured `event: 'timing'` log
 * line with `op`, `durationMs`, and `ok`. In tests the runner subprocess
 * logs to a file the harness can tail + parse; in production the same
 * lines flow to Loki and can be aggregated into "p95 of bundle.download"
 * style charts without per-service plumbing.
 *
 * Designed to layer rather than replace:
 *   - Already-rich operations (the SDK, ass-server) keep their own logs.
 *   - This adds a deterministic marker for the spans the team cares
 *     about most — bundle hops, sandbox lifecycle, LLM turns, queue
 *     pickup latency — so a single `grep '"event":"timing"'` answers
 *     "where did the time go?" for any session.
 *
 * Why not OpenTelemetry: OTel is the right answer once we want
 * distributed traces across services, but it's a multi-service infra
 * lift (collector, exporter, sampling). This gives us 80% of the value
 * with zero infra. Migrate to spans later by replacing the pino emit.
 *
 * Usage:
 *   const bundle = await withTiming(
 *     { op: 'bundle.download', sessionId, key },
 *     () => bundleStore.downloadBundle(key, sha),
 *   )
 */
export interface TimingContext {
    /** Dotted op name, e.g. `bundle.download` or `runtime.turn`. */
    op: string
    /** Free-form attributes. Logged as top-level fields, not nested. */
    [key: string]: unknown
}

export async function withTiming<T>(ctx: TimingContext, fn: () => Promise<T>, log: Logger = defaultLogger): Promise<T> {
    const start = process.hrtime.bigint()
    try {
        const result = await fn()
        const durationMs = Number(process.hrtime.bigint() - start) / 1_000_000
        log.info({ event: 'timing', ok: true, durationMs, ...ctx }, `timing: ${ctx.op}`)
        return result
    } catch (err) {
        const durationMs = Number(process.hrtime.bigint() - start) / 1_000_000
        log.info({ event: 'timing', ok: false, durationMs, ...ctx }, `timing: ${ctx.op} (failed)`)
        throw err
    }
}

/** Sync counterpart — use when the wrapped op isn't async (rare in this codebase). */
export function withTimingSync<T>(ctx: TimingContext, fn: () => T, log: Logger = defaultLogger): T {
    const start = process.hrtime.bigint()
    try {
        const result = fn()
        const durationMs = Number(process.hrtime.bigint() - start) / 1_000_000
        log.info({ event: 'timing', ok: true, durationMs, ...ctx }, `timing: ${ctx.op}`)
        return result
    } catch (err) {
        const durationMs = Number(process.hrtime.bigint() - start) / 1_000_000
        log.info({ event: 'timing', ok: false, durationMs, ...ctx }, `timing: ${ctx.op} (failed)`)
        throw err
    }
}
