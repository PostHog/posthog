import type { LiveStreamEntry } from './runStreamLogic'

interface LiveStreamRegistryHost {
    __posthogAiLiveStreamControllers?: Set<LiveStreamEntry>
}

// Vite injects `import.meta.hot` in dev and replaces it with undefined in production builds. Typed
// locally because `vite/client` only resolves from the frontend workspace, not from this product.
interface ViteHotContext {
    on: (event: 'vite:afterUpdate' | 'vite:beforeFullReload' | 'vite:beforeUpdate', cb: () => void) => void
}

let registered = false

/**
 * Closes live SSE readers before Vite applies an HMR update, so a dev reload never waits on them.
 *
 * An open SSE response keeps a granian dev worker alive, and granian's reload joins the old worker
 * before spawning its replacement, so a stream nobody closes stalls the whole backend until the kill
 * timeout in bin/start-backend fires. Vite awaits `vite:beforeUpdate` listeners before applying an
 * update, which makes it the one hook early enough to release the worker rather than race it.
 *
 * Every update fires this, including updates that leave `runStreamLogic` itself untouched. Those
 * logics survive the swap with a live thread still on screen, and an aborted signal is the silent
 * teardown path that schedules no reconnect, so aborting alone would stall the run with no way back.
 * They are reopened on `vite:afterUpdate` instead.
 *
 * Registry membership is what decides who gets reopened, because an entry is removed only when its
 * 'event-source' disposable tears down. An entry still present after the swap therefore has a logic
 * that is mounted and still wants a stream. Entries that vanished belong either to a logic that
 * unmounted mid-swap or to a build the swap discarded (re-evaluating `runStreamLogic` installs a
 * fresh registry), and both must stay closed.
 *
 * This lives outside `runStreamLogic` because `import.meta` cannot appear in any module Jest
 * compiles: Sucrase passes it through into CJS and the script then fails to compile with "Cannot use
 * 'import.meta' outside a module", which no runtime environment check can prevent. Jest maps this
 * path to an empty module (see `moduleNameMapper` in frontend/jest.config.ts), so the caller must
 * keep the call itself behind a development check.
 */
export function registerHmrStreamAbort(): void {
    const hot = (import.meta as ImportMeta & { hot?: ViteHotContext }).hot
    // An HMR swap that re-evaluates only the caller would otherwise stack a second set of listeners
    // on this module's still-live hot context.
    if (!hot || registered) {
        return
    }
    registered = true

    const registryHost = globalThis as LiveStreamRegistryHost
    let pendingReopen: LiveStreamEntry[] = []

    const abortAll = (): LiveStreamEntry[] => {
        const entries = [...(registryHost.__posthogAiLiveStreamControllers ?? [])]
        entries.forEach((entry) => entry.controller.abort())
        return entries
    }

    hot.on('vite:beforeUpdate', () => {
        pendingReopen = abortAll()
    })

    hot.on('vite:afterUpdate', () => {
        const entries = pendingReopen
        pendingReopen = []
        const current = registryHost.__posthogAiLiveStreamControllers
        entries.forEach((entry) => {
            if (current?.has(entry)) {
                entry.reopen()
            }
        })
    })

    // A full reload discards the page anyway, but releasing the worker before it starts means the new
    // page's first requests aren't queued behind a backend still waiting on the old connection.
    hot.on('vite:beforeFullReload', () => {
        pendingReopen = []
        abortAll()
    })
}
