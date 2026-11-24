import { useEffect, useState } from 'react'

import { subscribeToTicker } from 'lib/components/TZLabel'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'

/**
 * The current time, re-rendering the caller when the minute changes while the page is visible. The
 * inbox list does not poll, so a countdown would otherwise stay at the time the row first rendered.
 */
export function useMinuteClock(enabled: boolean): number {
    const { isVisible } = usePageVisibility()
    const [now, setNow] = useState(() => Date.now())

    useEffect(() => {
        if (!enabled || !isVisible) {
            return
        }
        const tick = (): void => {
            const current = Date.now()
            setNow((previous) => (Math.floor(previous / 60_000) === Math.floor(current / 60_000) ? previous : current))
        }
        tick()
        return subscribeToTicker(tick)
    }, [enabled, isVisible])

    return now
}
