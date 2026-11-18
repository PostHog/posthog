import { useEffect, useRef, useState } from 'react'

export const RECONNECT_NOTICE_DELAY_MS = 10_000
export const RECONNECT_CHECK_TIMEOUT_MS = 5000

export function useDelayedReconnecting(
    reconnecting: boolean,
    scope: unknown,
    checkRecovery: (signal: AbortSignal) => Promise<void>
): boolean {
    const [visibleFor, setVisibleFor] = useState<{ scope: unknown } | null>(null)
    const checkRecoveryRef = useRef(checkRecovery)
    checkRecoveryRef.current = checkRecovery
    useEffect(() => {
        setVisibleFor(null)
        if (!reconnecting) return
        const controller = new AbortController()
        let deadline: ReturnType<typeof setTimeout> | undefined
        const show = (): void => {
            if (controller.signal.aborted) return
            clearTimeout(deadline)
            setVisibleFor({ scope })
            controller.abort()
        }
        const timer = setTimeout(() => {
            deadline = setTimeout(show, RECONNECT_CHECK_TIMEOUT_MS)
            void checkRecoveryRef.current(controller.signal).then(show, show)
        }, RECONNECT_NOTICE_DELAY_MS)
        return () => {
            controller.abort()
            clearTimeout(timer)
            clearTimeout(deadline)
        }
    }, [reconnecting, scope])
    return reconnecting && visibleFor !== null && visibleFor.scope === scope
}
