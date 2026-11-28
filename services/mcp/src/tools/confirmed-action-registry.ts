import { AsyncLocalStorage } from 'node:async_hooks'

import type { PayloadStash, SignedStateCodec } from '@/lib/signed-state'

export interface ConfirmedActionRuntime {
    codec: SignedStateCodec
    stash: PayloadStash
}

/** Embedded calls can interleave. Their signing state must stay with the calling client. */
export const embeddedConfirmations = new AsyncLocalStorage<ConfirmedActionRuntime>()

let installed: ConfirmedActionRuntime | undefined

export function setConfirmedActionRuntime(runtime: ConfirmedActionRuntime | undefined): void {
    installed = runtime
}

export function getConfirmedActionRuntime(): ConfirmedActionRuntime {
    const runtime = embeddedConfirmations.getStore() ?? installed
    if (!runtime) {
        throw new Error(
            'ConfirmedActionRuntime not installed. The confirmed_action paradigm is disabled on this server — ' +
                'set MCP_SIGNED_STATE_KEY to at least 32 bytes and restart. ' +
                '(In tests, call setConfirmedActionRuntime({codec, stash}) before exercising prepare/execute handlers.)'
        )
    }
    return runtime
}
