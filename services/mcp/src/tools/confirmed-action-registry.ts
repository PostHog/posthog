/**
 * Process-level singleton holding the `SignedStateCodec` and `NonceLedger`
 * that generated `confirmed_action` handlers call into.
 *
 * The Hono entrypoint installs these at boot via `setConfirmedActionRuntime`.
 * Generated code calls `getConfirmedActionRuntime()` from every prepare/execute
 * handler. Tests can install a custom codec + ledger via `setConfirmedActionRuntime`
 * before exercising the generated code.
 *
 * Pattern matches how UI apps + tool catalogs are wired today — globals
 * installed once, read by many.
 */

import type { NonceLedger, SignedStateCodec } from '@/lib/signed-state'

export interface ConfirmedActionRuntime {
    codec: SignedStateCodec
    ledger: NonceLedger
}

let installed: ConfirmedActionRuntime | undefined

export function setConfirmedActionRuntime(runtime: ConfirmedActionRuntime | undefined): void {
    installed = runtime
}

export function getConfirmedActionRuntime(): ConfirmedActionRuntime {
    if (!installed) {
        throw new Error(
            'ConfirmedActionRuntime not installed. The confirmed_action paradigm is disabled on this server — ' +
                'set MCP_SIGNED_STATE_KEY to at least 32 bytes and restart. ' +
                '(In tests, call setConfirmedActionRuntime({codec, ledger}) before exercising prepare/execute handlers.)'
        )
    }
    return installed
}
