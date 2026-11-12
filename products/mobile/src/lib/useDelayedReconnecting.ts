import { useEffect, useState } from 'react'

export const RECONNECT_NOTICE_DELAY_MS = 10_000

export function useDelayedReconnecting(reconnecting: boolean, scope: unknown): boolean {
    const [visibleFor, setVisibleFor] = useState<{ scope: unknown } | null>(null)
    useEffect(() => {
        setVisibleFor(null)
        if (!reconnecting) return
        const timer = setTimeout(() => setVisibleFor({ scope }), RECONNECT_NOTICE_DELAY_MS)
        return () => clearTimeout(timer)
    }, [reconnecting, scope])
    return reconnecting && visibleFor !== null && visibleFor.scope === scope
}
