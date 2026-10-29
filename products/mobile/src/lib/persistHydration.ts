/** Resolves the launch gate after either a successful read or a storage error. */
export function createPersistHydrationGate(): {
    isHydrated: () => boolean
    subscribe: (listener: () => void) => () => void
    settle: () => void
    wait: () => Promise<void>
} {
    let hydrated = false
    let resolveWait: () => void = () => undefined
    const waitPromise = new Promise<void>((resolve) => {
        resolveWait = resolve
    })
    const listeners = new Set<() => void>()
    return {
        isHydrated: () => hydrated,
        subscribe: (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
        settle: () => {
            if (hydrated) {
                return
            }
            hydrated = true
            resolveWait()
            for (const listener of listeners) {
                listener()
            }
        },
        wait: () => waitPromise,
    }
}
