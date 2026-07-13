/**
 * Process-level availability probes for the code-execution surface. Kept in a
 * leaf module (imports only `@/lib/env`, mirroring the isolation rationale in
 * `constants.ts`) so the instructions builder can consult the exact predicate
 * the executor enforces without importing the executor — that edge would drag
 * `@posthog/sdk` and the lowering toolchain into every consumer.
 */

import { env } from '@/lib/env'

/**
 * Whether `LocalVmExecutor` may construct here. Fail-closed allowlist,
 * mirroring `resolveFeatureFlagOverrides`: an unset NODE_ENV must not unlock
 * local execution.
 */
export function localVmExecutionSupported(): boolean {
    return env.NODE_ENV === 'development' || env.NODE_ENV === 'test'
}

/**
 * Whether this process can execute arbitrary scripts in a sandbox. `run` and
 * `apply` dispatch everywhere the code-execution flag is on — the no-sandbox
 * fast path serves call-shaped scripts even here (spec §4.2) — but where this
 * is false, everything else gets a targeted sandbox-unavailable error and the
 * instructions advertise the `fast-path` level. `LocalVmExecutor`'s
 * constructor enforces the same predicate — keep them in lockstep. When the
 * hosted substrate grows past the local VM (the Modal sandbox pool, spec
 * §3.3/§3.4), extend this rather than the call sites.
 */
export function sandboxExecutionAvailable(): boolean {
    return localVmExecutionSupported()
}
