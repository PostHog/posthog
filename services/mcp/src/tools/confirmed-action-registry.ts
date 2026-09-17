/**
 * Process-level singleton holding the `SignedStateCodec` and `NonceLedger`
 * that generated `confirmed_action` handlers call into.
 *
 * The Hono entrypoint installs these at boot via `setConfirmedActionRuntime`.
 * The CLI registers a builder instead, through
 * `setConfirmedActionRuntimeProvider` — see that function for why.
 * Generated code calls `getConfirmedActionRuntime()` from every prepare/execute
 * handler. Tests can install a custom codec + ledger via `setConfirmedActionRuntime`
 * before exercising the generated code.
 *
 * Pattern matches how UI apps + tool catalogs are wired today — globals
 * installed once, read by many.
 */

import type { NonceLedger, PayloadStash, SignedStateCodec } from '@/lib/signed-state'

export interface ConfirmedActionRuntime {
    codec: SignedStateCodec
    ledger: NonceLedger
    stash: PayloadStash
}

let installed: ConfirmedActionRuntime | undefined
let provider: (() => ConfirmedActionRuntime) | undefined

export function setConfirmedActionRuntime(runtime: ConfirmedActionRuntime | undefined): void {
    installed = runtime
    provider = undefined
}

/**
 * Register a builder that the first prepare/execute call resolves, for a
 * surface where building the runtime costs local I/O that most calls would
 * waste — the CLI reads and writes files, and few of its commands reach a
 * confirmed action. A builder that throws surfaces its own error to the
 * caller, which is how a surface explains the problem in terms its own user
 * controls rather than quoting the server message below.
 */
export function setConfirmedActionRuntimeProvider(build: (() => ConfirmedActionRuntime) | undefined): void {
    provider = build
    installed = undefined
}

export function getConfirmedActionRuntime(): ConfirmedActionRuntime {
    if (!installed && provider) {
        installed = provider()
    }
    if (!installed) {
        throw new Error(
            'ConfirmedActionRuntime not installed. The confirmed_action paradigm is disabled on this server — ' +
                'set MCP_SIGNED_STATE_KEY to at least 32 bytes and restart. ' +
                '(In tests, call setConfirmedActionRuntime({codec, ledger}) before exercising prepare/execute handlers.)'
        )
    }
    return installed
}
