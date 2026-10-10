import { AsyncLocalStorage } from 'node:async_hooks'

import type { ConfirmedActionRuntime } from '@/tools/confirmed-action-registry'

export const sdkHost = new AsyncLocalStorage<{ confirmation: ConfirmedActionRuntime }>()

export function getConfirmedActionRuntime(): ConfirmedActionRuntime {
    const runtime = sdkHost.getStore()
    if (!runtime) {
        throw new Error('Call confirmation tools through a PostHog SDK client.')
    }
    return runtime.confirmation
}
